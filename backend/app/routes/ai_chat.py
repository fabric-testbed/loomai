"""Streaming agentic AI assistant — proxies to FABRIC LLMs with tool calling."""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
import os
import re
import sys
import traceback
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.ai_assets import parse_markdown_asset
from app.http_pool import ai_client
from app.settings_manager import get_fabric_api_key as _get_ai_api_key, get_nrp_api_key as _get_nrp_api_key

logger = logging.getLogger(__name__)

router = APIRouter()

AI_SERVER_URL = "https://ai.fabric-testbed.net"  # Fallback; prefer _ai_server_url()

def _ai_server_url() -> str:
    from app.settings_manager import get_ai_server_url
    return get_ai_server_url()

def _nrp_server_url() -> str:
    from app.settings_manager import get_nrp_server_url
    return get_nrp_server_url()
_MAX_TOOL_ERRORS_PER_TURN = 8  # failed tool calls in one turn before we stop and summarize
_MAX_TOOL_ROUNDS = 100  # emergency backstop; normal stopping comes from
                        # no-progress detection and per-turn budget guards.
_MIN_PROFILE_INPUT_TOKENS = 8192
_MAX_OUTPUT_CONTEXT_FRACTION = 0.25
_RESOURCE_TOOL_CONTEXT_LIMIT = 16000
_SLICE_QUERY_CONTEXT_LIMIT = 6000
_MAX_REASONING_OUTPUT_TOKENS = 32768

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_AI_TOOLS_DIR = os.path.join(_APP_ROOT, "ai-tools")
_FABRIC_AI_MD_PATH = os.path.join(_AI_TOOLS_DIR, "shared", "FABRIC_AI.md")
_AGENTS_DIR = os.path.join(_AI_TOOLS_DIR, "shared", "agents")

# FABlib API ground truth: authoritative method reference that lists real
# methods and common hallucinations. Injected into the system prompt for
# FABRIC/FABlib code-generation requests to prevent qwen3-coder from inventing
# non-existent FABlib methods (verified hallucination issue from live probes).
_FABLIB_REF_PATH = os.path.join(
    _AI_TOOLS_DIR, "fablib-examples", "experiments", "fablib_api_reference.py"
)
_fablib_ref_cache: str | None = None


def _load_fablib_ref() -> str:
    """Return the FABlib API reference file content (cached in memory)."""
    global _fablib_ref_cache
    if _fablib_ref_cache is None:
        try:
            with open(_FABLIB_REF_PATH) as f:
                _fablib_ref_cache = f.read()
        except OSError:
            _fablib_ref_cache = ""
    return _fablib_ref_cache


def _reprofile_for_model(profile: dict, model_name: str, use_full_llm_mode: bool) -> tuple[dict, list[dict], int]:
    """Rebuild the context-budget part of *profile* for *model_name*.

    Used when the request falls back to another model mid-turn: the window,
    output cap, tool budget and tool support are per model, while the user's
    generation settings (temperature, top_p, reasoning effort) carry over.
    Returns (profile, tools_for_model, tool_token_estimate).
    """
    from app.chat_context import (
        estimate_tool_schema_tokens, filter_tool_schemas, get_model_profile,
    )
    bare = model_name.split(":")[-1] if ":" in model_name else model_name  # same rule as the request path
    ctx = _FABRIC_CONTEXT_DEFAULTS.get(bare) or _NRP_CONTEXT_DEFAULTS.get(bare)
    fresh = get_model_profile(model_name, context_length=ctx)
    merged = dict(profile)
    for key in ("context_window", "summarize_at", "tier", "system_prompt",
                "tool_result_max", "max_tools", "supports_tools"):
        if key in fresh:
            merged[key] = fresh[key]
    # Never ask a smaller model for more output than it can produce.
    merged["max_output"] = min(int(profile.get("max_output") or fresh["max_output"]), int(fresh["max_output"]))
    max_tools = len(TOOL_SCHEMAS) if use_full_llm_mode else merged["max_tools"]
    tools = filter_tool_schemas(TOOL_SCHEMAS, max_tools)
    tool_tokens = estimate_tool_schema_tokens(tools) if merged.get("supports_tools", True) else 0
    logger.info("Re-profiled for fallback model %s: tier=%s window=%s tools=%d",
                model_name, merged.get("tier"), merged.get("context_window"), len(tools))
    return merged, tools, tool_tokens


def _get_model_type(model_key: str) -> str:
    """Look up model_type ('chat', 'responses', 'non-chat') from cached model data.

    Checks FABRIC, NRP, and custom provider entries in discovered_models.
    Defaults to "chat" if not found (safe fallback).
    """
    from app.settings_manager import load_settings, normalize_ai_endpoint_style
    try:
        settings = load_settings()
        ai_settings = settings.get("ai", {})
        discovered = ai_settings.get("discovered_models", {})
        # Strip provider prefix to get bare model id
        provider_prefix = ""
        bare = model_key
        if ":" in model_key:
            provider_prefix, _, bare = model_key.partition(":")
        if provider_prefix and provider_prefix not in {"fabric", "nrp"}:
            for provider in ai_settings.get("custom_providers", []) or []:
                if isinstance(provider, dict) and provider.get("name") == provider_prefix:
                    configured_style = normalize_ai_endpoint_style(provider.get("endpoint_style"))
                    if configured_style != "auto":
                        return configured_style
                    break
            custom = discovered.get("custom", {})
            if isinstance(custom, dict):
                for m in custom.get(provider_prefix, []) or []:
                    if isinstance(m, dict) and m.get("id") == bare:
                        return m.get("model_type") or m.get("endpoint_style") or "chat"
            return "chat"
        # Check fabric and nrp lists
        provider_keys = [provider_prefix] if provider_prefix in {"fabric", "nrp"} else ["fabric", "nrp"]
        for provider_key in provider_keys:
            provider_models = discovered.get(provider_key, [])
            if isinstance(provider_models, list):
                for m in provider_models:
                    if isinstance(m, dict) and m.get("id") == bare:
                        return m.get("model_type", "chat")
    except Exception:
        pass
    if _looks_like_responses_model(model_key):
        return "responses"
    return "chat"


def _looks_like_responses_model(model_key: str) -> bool:
    """Return True for model ids known to require OpenAI Responses shape."""
    model_lower = (model_key or "").lower()
    bare = model_lower.split(":")[-1]
    responses_patterns = (
        "gpt-5.5",
        "gpt-5-responses",
        "responses",
    )
    return any(pattern in bare for pattern in responses_patterns)


def _optional_float(body: dict, key: str, *, minimum: float, maximum: float) -> float | None:
    """Read an optional numeric request field and clamp it to provider-safe bounds."""
    raw = body.get(key)
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def _optional_int(body: dict, key: str, *, minimum: int, maximum: int) -> int | None:
    """Read an optional integer request field and clamp it to provider-safe bounds."""
    raw = body.get(key)
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def _normalize_reasoning_effort(value: Any) -> str | None:
    """Normalize provider reasoning-effort controls."""
    if isinstance(value, dict):
        value = value.get("value", value.get("default", value.get("effort")))
    if value is None or value == "":
        return None
    lowered = str(value).strip().lower().replace("_", "-")
    aliases = {
        "minimum": "minimal",
        "maximum": "max",
    }
    lowered = aliases.get(lowered, lowered)
    if lowered in {"minimal", "low", "medium", "high", "max"}:
        return lowered
    return None


def _model_lookup_key(profile: dict, capability_profile: dict | None = None) -> str:
    return str(
        profile.get("model")
        or (capability_profile or {}).get("model_key")
        or ""
    ).lower()


def _is_glm5_model(profile: dict, capability_profile: dict | None = None) -> bool:
    model_key = _model_lookup_key(profile, capability_profile)
    return "glm-5" in model_key or "glm5" in model_key


def _apply_reasoning_effort_defaults(
    profile: dict,
    capability_profile: dict | None,
    adjustments: list[dict[str, Any]],
) -> None:
    """Apply model-specific reasoning controls that preserve visible output."""
    if profile.get("reasoning_effort"):
        return
    if not _is_glm5_model(profile, capability_profile):
        return
    profile["reasoning_effort"] = "high"
    profile["reasoning_effort_source"] = "loomai_default"
    adjustments.append({
        "field": "reasoning_effort",
        "source": "model_default",
        "profile_value": "provider_default_max",
        "applied_value": "high",
        "reason": (
            "lowered GLM-5 reasoning effort from the provider default so "
            "hidden thinking is less likely to consume the visible answer"
        ),
    })


def _apply_reasoning_controls(
    body: dict[str, Any],
    profile: dict,
    model_api_type: str,
    *,
    disabled: bool = False,
) -> None:
    """Add provider reasoning controls to a request body when configured."""
    if disabled:
        return
    effort = _normalize_reasoning_effort(profile.get("reasoning_effort"))
    if not effort:
        return
    if model_api_type == "responses":
        reasoning = body.get("reasoning")
        if not isinstance(reasoning, dict):
            reasoning = {}
        else:
            reasoning = dict(reasoning)
        reasoning["effort"] = effort
        body["reasoning"] = reasoning
    else:
        body["reasoning_effort"] = effort


def _request_has_reasoning_controls(body: dict[str, Any]) -> bool:
    return "reasoning_effort" in body or "reasoning" in body


def _is_reasoning_control_error(error_text: str) -> bool:
    lowered = error_text.lower()
    if "reasoning_effort" in lowered:
        return True
    if "reasoning" not in lowered:
        return False
    return any(
        marker in lowered
        for marker in (
            "not supported",
            "unsupported",
            "unknown",
            "unrecognized",
            "extra_forbidden",
            "not permitted",
        )
    )


def _adjust_generation_budget(
    profile: dict,
    capability_profile: dict | None,
    adjustments: list[dict[str, Any]],
    *,
    max_output_source: str = "profile",
) -> None:
    """Keep output reservations from consuming the model's whole input window."""
    try:
        context_window = int(profile.get("context_window") or 0)
        max_output = int(profile.get("max_output") or 0)
    except (TypeError, ValueError):
        return
    if context_window <= 0 or max_output <= 0:
        return

    source = max_output_source
    if source == "profile" and capability_profile and capability_profile.get("max_output_tokens") == max_output:
        source = "capability_profile"

    profile_input = None
    if capability_profile:
        try:
            profile_input = int(capability_profile.get("max_input_tokens") or 0)
        except (TypeError, ValueError):
            profile_input = None
    if profile_input is not None and 0 < profile_input < _MIN_PROFILE_INPUT_TOKENS:
        adjustments.append({
            "field": "max_input_tokens",
            "source": "capability_profile",
            "profile_value": profile_input,
            "applied_value": None,
            "reason": (
                f"rejected below {_MIN_PROFILE_INPUT_TOKENS} token minimum; "
                "latest user message and tool evidence must remain in input"
            ),
        })
        profile_input = None

    if (
        _is_reasoning_budget_model(profile, capability_profile)
        and max_output_source != "request"
        and context_window > _MIN_PROFILE_INPUT_TOKENS
    ):
        reasoning_output = min(
            _MAX_REASONING_OUTPUT_TOKENS,
            max(1024, context_window - _MIN_PROFILE_INPUT_TOKENS),
        )
        if max_output < reasoning_output:
            profile["max_output"] = reasoning_output
            adjustments.append({
                "field": "max_output_tokens",
                "source": source,
                "profile_value": max_output,
                "applied_value": reasoning_output,
                "reason": (
                    "raised for reasoning model so internal thinking does not "
                    "consume the entire visible-answer budget"
                ),
            })
            max_output = reasoning_output
        effective_input = max(0, context_window - max_output)
        if profile_input and profile_input > effective_input:
            adjustments.append({
                "field": "max_input_tokens",
                "source": "capability_profile",
                "profile_value": profile_input,
                "applied_value": effective_input,
                "reason": (
                    "rebalanced for reasoning model; visible output budget "
                    "takes priority while preserving the input floor"
                ),
            })
            profile_input = effective_input
        profile["summarize_at"] = max(float(profile.get("summarize_at") or 0.0), 1.0)
        profile["reasoning_budget_mode"] = "output_preferred"

    safe_output_cap = max(1024, context_window - _MIN_PROFILE_INPUT_TOKENS)
    if profile_input and profile_input + max_output > context_window:
        safe_output_cap = max(1024, min(safe_output_cap, context_window - profile_input))
    elif max_output > context_window - _MIN_PROFILE_INPUT_TOKENS:
        safe_output_cap = max(1024, min(
            int(context_window * _MAX_OUTPUT_CONTEXT_FRACTION),
            context_window - _MIN_PROFILE_INPUT_TOKENS,
        ))
    else:
        return

    if max_output > safe_output_cap:
        profile["max_output"] = safe_output_cap
        adjustments.append({
            "field": "max_output_tokens",
            "source": source,
            "profile_value": max_output,
            "applied_value": safe_output_cap,
            "reason": (
                "reduced to preserve input budget for system prompt, tools, "
                "and the newest user turn"
            ),
        })


def _is_reasoning_budget_model(profile: dict, capability_profile: dict | None) -> bool:
    """Return true for models whose reasoning tokens consume output budget."""
    if profile.get("is_reasoning"):
        return True
    if capability_profile and capability_profile.get("reasoning_model"):
        return True
    model_key = _model_lookup_key(profile, capability_profile)
    if any(pattern in model_key for pattern in ("glm-5", "glm5", "nemotron")):
        return True
    tier = str(
        profile.get("orchestration_tier")
        or (capability_profile or {}).get("orchestration_tier")
        or ""
    ).lower()
    return "reason" in tier


def _build_responses_input(conversation: list[dict]) -> tuple[str, list[dict]]:
    """Convert chat-completions messages into Responses API input items.

    Returns (instructions, input_items) where instructions is extracted from
    the system message and input_items are the remaining messages converted
    to the Responses API format.
    """
    instructions = ""
    input_items: list[dict] = []
    seen_function_call_ids: set[str] = set()
    for msg in conversation:
        # Items already in Responses API format (have "type" but no "role",
        # or have type=function_call/function_call_output) — pass through as-is.
        msg_type = msg.get("type", "")
        if msg_type == "reasoning":
            input_items.append(_responses_reasoning_item(msg))
            continue
        if msg_type == "function_call":
            item = _responses_function_call_item(msg)
            call_id = item.get("call_id", "")
            if call_id:
                seen_function_call_ids.add(call_id)
            input_items.append(item)
            continue
        if msg_type == "function_call_output":
            call_id = msg.get("call_id", "")
            if call_id and call_id in seen_function_call_ids:
                input_items.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": msg.get("output", ""),
                })
            else:
                logger.warning(
                    "Dropping orphan Responses function_call_output with call_id=%s",
                    call_id or "<missing>",
                )
            continue
        if msg_type == "message" and "role" in msg:
            input_items.append(msg)
            continue

        # Convert chat-completions format messages
        role = msg.get("role", "")
        if role == "system":
            instructions = msg.get("content", "")
        elif role == "user":
            input_items.append({
                "type": "message",
                "role": "user",
                "content": msg.get("content", ""),
            })
        elif role == "assistant":
            # Check for tool_calls in assistant message
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                # Emit text content first if present
                text = msg.get("content")
                if text:
                    input_items.append({
                        "type": "message",
                        "role": "assistant",
                        "content": text,
                    })
                # Each tool call becomes a function_call item
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    item = _responses_function_call_item({
                        "type": "function_call",
                        "call_id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", "{}"),
                    })
                    call_id = item.get("call_id", "")
                    if call_id:
                        seen_function_call_ids.add(call_id)
                    input_items.append(item)
            else:
                input_items.append({
                    "type": "message",
                    "role": "assistant",
                    "content": msg.get("content", ""),
                })
        elif role == "tool":
            call_id = msg.get("tool_call_id", "")
            if call_id and call_id in seen_function_call_ids:
                input_items.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": msg.get("content", ""),
                })
            else:
                logger.warning(
                    "Dropping orphan Responses tool output with call_id=%s",
                    call_id or "<missing>",
                )
    return instructions, input_items


def _responses_reasoning_item(item: dict[str, Any]) -> dict[str, Any]:
    """Return a provider reasoning item exactly enough for Responses replay."""
    replay = dict(item)
    replay["type"] = "reasoning"
    return replay


def _responses_function_call_item(item: dict[str, Any]) -> dict[str, Any]:
    """Return the Responses API function_call item fields worth replaying."""
    call_id = item.get("call_id") or item.get("id") or ""
    replay: dict[str, Any] = {
        "type": "function_call",
        "call_id": call_id,
        "name": item.get("name", ""),
        "arguments": item.get("arguments", "{}"),
    }
    if item.get("id"):
        replay["id"] = item["id"]
    if item.get("status"):
        replay["status"] = item["status"]
    return replay


def _build_responses_body(
    model: str,
    conversation: list[dict],
    profile: dict,
    tools_for_model: list[dict],
    tools_disabled: bool,
    temperature_disabled: bool = False,
    reasoning_controls_disabled: bool = False,
) -> dict:
    """Build request body for the OpenAI Responses API (/v1/responses)."""
    instructions, input_items = _build_responses_input(conversation)
    body: dict[str, Any] = {
        "model": model,
        "input": input_items,
        "max_output_tokens": profile["max_output"],
    }
    if not temperature_disabled:
        body["temperature"] = profile["temperature"]
    if profile.get("top_p") is not None:
        body["top_p"] = profile["top_p"]
    if instructions:
        body["instructions"] = instructions
    if not tools_disabled and profile.get("supports_tools", True) and tools_for_model:
        body["tools"] = tools_for_model
    _apply_reasoning_controls(
        body,
        profile,
        "responses",
        disabled=reasoning_controls_disabled,
    )
    return body


def _parse_responses_output(output_items: list[dict]) -> tuple[str, list[dict]]:
    """Parse Responses API output into (text, tool_calls).

    Returns text content and a list of tool_calls in chat-completions format
    for compatibility with existing tool execution code.
    """
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    pending_reasoning_items: list[dict[str, Any]] = []
    for item in output_items:
        item_type = item.get("type", "")
        if item_type == "reasoning":
            pending_reasoning_items.append(_responses_reasoning_item(item))
        elif item_type == "message":
            for c in item.get("content", []):
                if c.get("type") in ("output_text", "text"):
                    text_parts.append(c.get("text", ""))
        elif item_type == "function_call":
            call_id = item.get("call_id", "")
            raw_item = _responses_function_call_item(item)
            tool_call = {
                "id": call_id,
                "type": "function",
                "_responses_item": raw_item,
                "function": {
                    "name": item.get("name", ""),
                    "arguments": item.get("arguments", "{}"),
                },
            }
            if pending_reasoning_items:
                tool_call["_responses_prelude_items"] = pending_reasoning_items
                pending_reasoning_items = []
            tool_calls.append(tool_call)
    return "".join(text_parts), tool_calls


# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------
_system_prompt_cache: str | None = None
_agents_cache: dict[str, dict] | None = None
_RESOURCE_EVIDENCE_CACHE: dict[str, dict[str, Any]] = {}
_RESOURCE_EVIDENCE_LIMIT = 50


def invalidate_agents_cache() -> None:
    """Clear the agents cache so the next load picks up changes."""
    global _agents_cache
    _agents_cache = None


def _load_system_prompt() -> str:
    global _system_prompt_cache
    if _system_prompt_cache is None:
        try:
            with open(_FABRIC_AI_MD_PATH, "r") as f:
                _system_prompt_cache = f.read()
        except Exception:
            _system_prompt_cache = "You are a helpful FABRIC testbed assistant."
    return _system_prompt_cache


def _cache_resource_evidence(source: str, raw: Any) -> str:
    """Keep raw FABRIC resource evidence out of LLM context but available to logs."""
    evidence_id = f"fabric-resource-query/{uuid.uuid4().hex[:12]}"
    _RESOURCE_EVIDENCE_CACHE[evidence_id] = {
        "source": source,
        "captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "raw": raw,
    }
    while len(_RESOURCE_EVIDENCE_CACHE) > _RESOURCE_EVIDENCE_LIMIT:
        oldest = next(iter(_RESOURCE_EVIDENCE_CACHE))
        _RESOURCE_EVIDENCE_CACHE.pop(oldest, None)
    logger.info("Captured raw FABRIC resource evidence %s from %s", evidence_id, source)
    return f"cache://{evidence_id}"


def _available_components(row: dict[str, Any]) -> dict[str, int]:
    """Extract positive available component counts from heterogeneous rows."""
    components: dict[str, int] = {}
    for key, value in row.items():
        key_lower = key.lower()
        if not key_lower.endswith("_available"):
            continue
        if key_lower in {"cores_available", "ram_available", "disk_available", "gpu_available"}:
            continue
        try:
            count = int(value or 0)
        except (TypeError, ValueError):
            continue
        if count > 0:
            components[key[:-10]] = count

    raw_components = row.get("components") or row.get("component_info") or {}
    if isinstance(raw_components, dict):
        for name, info in raw_components.items():
            count = 0
            if isinstance(info, dict):
                count = info.get("available") or info.get("free") or 0
            else:
                count = info or 0
            try:
                count_int = int(count or 0)
            except (TypeError, ValueError):
                continue
            if count_int > 0:
                components[str(name)] = count_int
    return dict(sorted(components.items()))


def _merge_component_counts(*component_sets: dict[str, int]) -> dict[str, int]:
    """Merge component availability maps by model name."""
    merged: dict[str, int] = {}
    for component_set in component_sets:
        for name, count in component_set.items():
            try:
                count_int = int(count or 0)
            except (TypeError, ValueError):
                continue
            if count_int > 0:
                merged[str(name)] = merged.get(str(name), 0) + count_int
    return dict(sorted(merged.items()))


def _site_available_components(site: dict[str, Any]) -> dict[str, int]:
    """Extract site component availability, including host-level details."""
    site_components = _available_components(site)
    hosts_detail = site.get("hosts_detail")
    if not isinstance(hosts_detail, list):
        return site_components

    host_components: dict[str, int] = {}
    for host in hosts_detail:
        if isinstance(host, dict):
            host_components = _merge_component_counts(host_components, _available_components(host))
    components: dict[str, int] = {}
    for name in sorted(set(site_components) | set(host_components)):
        components[name] = max(site_components.get(name, 0), host_components.get(name, 0))
    return {name: count for name, count in components.items() if count > 0}


def _filter_gpu_components(components: dict[str, int]) -> dict[str, int]:
    """Return only GPU component availability entries."""
    return {
        name: count
        for name, count in components.items()
        if str(name).upper().startswith("GPU")
    }


def _compact_site_inventory(raw_sites: list[dict[str, Any]], *, max_rows: int = 100) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for site in raw_sites:
        if not isinstance(site, dict):
            continue
        notable_components = _site_available_components(site)
        gpu_components = _filter_gpu_components(notable_components)
        rows.append({
            "site": site.get("name") or site.get("site"),
            "state": site.get("state"),
            "hosts": site.get("hosts") or site.get("host_count"),
            "cores_available": site.get("cores_available"),
            "ram_available_gb": site.get("ram_available"),
            "disk_available_gb": site.get("disk_available"),
            "gpus": sum(gpu_components.values()),
            "gpu_components": gpu_components,
            "has_available_gpus": bool(gpu_components),
            "notable_components": notable_components,
        })

    def _sort_key(row: dict[str, Any]) -> tuple:
        state_rank = 0 if str(row.get("state", "")).lower() in {"active", "ok"} else 1
        cores = row.get("cores_available") or 0
        ram = row.get("ram_available_gb") or 0
        try:
            cores_i = int(cores)
        except (TypeError, ValueError):
            cores_i = 0
        try:
            ram_i = int(ram)
        except (TypeError, ValueError):
            ram_i = 0
        return (state_rank, -cores_i, -ram_i, str(row.get("site") or ""))

    rows.sort(key=_sort_key)
    evidence_ref = _cache_resource_evidence("resources.list_sites", raw_sites)
    return {
        "query_id": evidence_ref.rsplit("/", 1)[-1],
        "source": "resources.list_sites",
        "captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "summary": {
            "site_count": len(rows),
            "active_site_count": sum(1 for r in rows if str(r.get("state", "")).lower() in {"active", "ok"}),
            "gpu_site_count": sum(1 for r in rows if r.get("has_available_gpus")),
            "gpu_total_available": sum(int(r.get("gpus") or 0) for r in rows),
            "returned_rows": min(len(rows), max_rows),
        },
        "rows": rows[:max_rows],
        "all_sites": [r["site"] for r in rows if r.get("site")],
        "gpu_sites": [r["site"] for r in rows if r.get("site") and r.get("has_available_gpus")],
        "raw_evidence_ref": evidence_ref,
        "truncated": len(rows) > max_rows,
        "omitted_site_count": max(0, len(rows) - max_rows),
    }


def _compact_host_inventory(raw_hosts: Any, site_name: str, *, max_rows: int = 500) -> dict[str, Any]:
    host_rows = raw_hosts
    if isinstance(raw_hosts, dict):
        host_rows = raw_hosts.get("hosts") or raw_hosts.get("data") or []
    if not isinstance(host_rows, list):
        host_rows = []

    rows: list[dict[str, Any]] = []
    for host in host_rows:
        if not isinstance(host, dict):
            continue
        notable_components = _available_components(host)
        gpu_components = _filter_gpu_components(notable_components)
        rows.append({
            "host": host.get("name") or host.get("host") or host.get("hostname"),
            "site": host.get("site") or site_name,
            "state": host.get("state"),
            "cores_available": host.get("cores_available"),
            "ram_available_gb": host.get("ram_available"),
            "disk_available_gb": host.get("disk_available"),
            "gpus": sum(gpu_components.values()),
            "gpu_components": gpu_components,
            "has_available_gpus": bool(gpu_components),
            "notable_components": notable_components,
        })
    rows.sort(key=lambda r: (
        str(r.get("site") or ""),
        -(int(r.get("cores_available") or 0) if str(r.get("cores_available") or "0").isdigit() else 0),
        str(r.get("host") or ""),
    ))
    evidence_ref = _cache_resource_evidence("resources.list_site_hosts", raw_hosts)
    return {
        "query_id": evidence_ref.rsplit("/", 1)[-1],
        "source": "resources.list_site_hosts",
        "captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "site": site_name,
        "summary": {
            "host_count": len(rows),
            "gpu_host_count": sum(1 for r in rows if r.get("has_available_gpus")),
            "gpu_total_available": sum(int(r.get("gpus") or 0) for r in rows),
            "returned_rows": min(len(rows), max_rows),
        },
        "rows": rows[:max_rows],
        "all_returned_hosts": [r["host"] for r in rows[:max_rows] if r.get("host")],
        "raw_evidence_ref": evidence_ref,
        "truncated": len(rows) > max_rows,
        "omitted_host_count": max(0, len(rows) - max_rows),
    }


_PROGRESS_ONLY_RE = re.compile(
    r"\b(i'll|i will|let me|next i|i would|i need to|checking|inspect|query)\b",
    re.IGNORECASE,
)
_RESOURCE_TERMS_RE = re.compile(r"\b(site|host|cores?|ram|disk|available|resources?|slice)\b", re.IGNORECASE)
_INVALID_TERMS_RE = re.compile(r"\b(invalid|not found|unknown|unrecognized|not a valid)\b", re.IGNORECASE)
_GENERIC_IDENTIFIER_TERMS = {
    "CPU",
    "CPUS",
    "FABRIC",
    "FPGA",
    "FPGAS",
    "GB",
    "GIB",
    "GPU",
    "GPUS",
    "NIC",
    "NICS",
    "RAM",
    "SSH",
    "VM",
    "VMS",
}


def _fabric_query_validation_scope(
    user_message: str,
    agent_id: str | None,
    tool_names: list[str],
    *,
    explicit_agent_controls_context: bool = False,
) -> bool:
    msg = (user_message or "").lower()
    if explicit_agent_controls_context:
        return False
    if agent_id == "fabric-query-reporter":
        return True
    if not _is_fabric_information_query(user_message, None):
        return False
    if any(t in {"query_sites", "get_site_hosts", "list_slices"} for t in tool_names):
        return any(k in msg for k in ("site", "host", "resource", "available", "availability", "slice", "invalid", "not_a"))
    return False


def _is_fabric_information_query(user_message: str, intent_tool: str | None) -> bool:
    """Detect FABRIC read-only information queries for strict-query routing."""
    msg = (user_message or "").lower()
    if not msg:
        return False
    if intent_tool in {"query_sites", "get_site_hosts", "list_slices", "get_slice"}:
        return True
    mutation_terms = (
        "create", "add ", "submit", "delete", "renew", "modify", "deploy",
        "provision", "install", "run ", "write", "upload", "start ", "stop ",
    )
    if any(term in msg for term in mutation_terms):
        return False
    query_terms = (
        "available", "availability", "resources", "site", "sites", "host",
        "hosts", "slice status", "my slices", "list slices", "invalid",
        "not found", "unknown", "not_a_fabric_site", "not-a-real-host",
    )
    return any(term in msg for term in query_terms)


def _is_fabric_resource_generation_query(user_message: str, intent_tool: str | None) -> bool:
    """Detect FABRIC resource-table queries for D3 generation defaults."""
    msg = (user_message or "").lower()
    if intent_tool in {"query_sites", "get_site_hosts"}:
        return True
    if intent_tool in {"list_slices", "get_slice"}:
        return False
    if not _is_fabric_information_query(user_message, intent_tool):
        return False
    resource_terms = (
        "available", "availability", "resource", "resources", "site", "sites",
        "host", "hosts", "cores", "ram", "memory", "disk", "gpu", "fpga",
        "nic", "component", "components",
    )
    return any(term in msg for term in resource_terms)


def _model_in_final_answer_retry_scope(model_key: str, scope: str) -> bool:
    """Apply deployment-plan retry scope."""
    if scope == "all":
        return True
    model_lower = (model_key or "").lower()
    useful_patterns = (
        "qwen3-coder-30b",
        "qwen3",
        "gpt-5.5",
        "kimi-k2.6",
        "minimax-m2",
    )
    return any(pattern in model_lower for pattern in useful_patterns)


def _extract_user_identifiers(user_message: str) -> list[str]:
    identifiers = set(re.findall(r"\b[A-Z][A-Z0-9_:-]{2,}\b", user_message or ""))
    identifiers.update(re.findall(r"\b[a-z0-9][a-z0-9.-]*\.fabric-testbed\.net\b", user_message or "", re.IGNORECASE))
    identifiers.update(re.findall(r"\bnot-[a-z0-9.-]+\b", user_message or "", re.IGNORECASE))
    return sorted(
        ident for ident in identifiers
        if ident.upper() not in _GENERIC_IDENTIFIER_TERMS
    )


def _safe_json_loads(value: str) -> Any:
    try:
        return json.loads(value) if value else None
    except (json.JSONDecodeError, TypeError):
        return None


def _numeric_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def _requested_result_limit(user_message: str, *, default: int = 20) -> int:
    msg = user_message or ""
    patterns = (
        r"\b(?:top|first|limit(?:ed)? to|up to|max(?:imum)? of)\s+(\d{1,3})\b",
        r"\b(\d{1,3})\s+(?:hosts?|sites?|slices?)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, msg, re.IGNORECASE)
        if match:
            try:
                return max(1, min(100, int(match.group(1))))
            except ValueError:
                pass
    return default


def _host_resource_field(user_message: str) -> str | None:
    msg = (user_message or "").lower()
    if "ram" in msg or "memory" in msg:
        return "ram_available_gb"
    if "disk" in msg or "storage" in msg:
        return "disk_available_gb"
    if "core" in msg or "cpu" in msg or "vcpus" in msg:
        return "cores_available"
    return None


def _host_threshold_value(user_message: str) -> float | None:
    msg = user_message or ""
    patterns = (
        r"(?:>=|at\s+least|minimum|min(?:imum)?|more\s+than|over)\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*(?:gb|gib|cores?|cpus?|vcpus?)",
    )
    for pattern in patterns:
        match = re.search(pattern, msg, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
    return None


def _is_host_threshold_query(user_message: str) -> bool:
    msg = (user_message or "").lower()
    if "host" not in msg:
        return False
    return any(term in msg for term in (
        "threshold", "at least", "minimum", "min ", ">=", "more than",
        "over ", "cores", "core", "ram", "memory", "disk", "storage",
        "available", "availability",
    ))


def _extract_host_rows(tool_outputs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tool_name, result in tool_outputs:
        if tool_name != "get_site_hosts":
            continue
        data = _safe_json_loads(result)
        host_rows: Any = []
        if isinstance(data, dict):
            host_rows = data.get("rows") or data.get("hosts") or data.get("data") or []
        elif isinstance(data, list):
            host_rows = data
        if not isinstance(host_rows, list):
            continue
        for row in host_rows:
            if not isinstance(row, dict):
                continue
            host_name = row.get("host") or row.get("name") or row.get("hostname")
            if not host_name:
                continue
            rows.append(_normalize_host_resource_row(row))
    return rows


def _normalize_host_resource_row(
    row: dict[str, Any],
    *,
    site_name: str | None = None,
    site_state: str | None = None,
) -> dict[str, Any]:
    """Normalize host rows to the compact resource field names."""
    normalized = dict(row)
    host_name = row.get("host") or row.get("name") or row.get("hostname")
    if host_name:
        normalized["host"] = host_name
    if site_name and not normalized.get("site"):
        normalized["site"] = site_name
    if site_state and not normalized.get("state"):
        normalized["state"] = site_state
    if "ram_available_gb" not in normalized and "ram_available" in row:
        normalized["ram_available_gb"] = row.get("ram_available")
    if "disk_available_gb" not in normalized and "disk_available" in row:
        normalized["disk_available_gb"] = row.get("disk_available")
    if "notable_components" not in normalized:
        normalized["notable_components"] = _available_components(row)
    return normalized


def _matching_host_threshold_rows(
    tool_outputs: list[tuple[str, str]],
    user_message: str,
) -> list[dict[str, Any]]:
    if not _is_host_threshold_query(user_message):
        return []
    rows = _extract_host_rows(tool_outputs)
    if not rows:
        return []
    resource_field = _host_resource_field(user_message)
    threshold_value = _host_threshold_value(user_message)
    if resource_field and threshold_value is not None:
        rows = [
            row for row in rows
            if (_numeric_value(row.get(resource_field)) or 0.0) >= threshold_value
        ]
    if resource_field:
        rows.sort(key=lambda row: (
            -(_numeric_value(row.get(resource_field)) or 0.0),
            str(row.get("site") or ""),
            str(row.get("host") or row.get("name") or row.get("hostname") or ""),
        ))
    limit = _requested_result_limit(user_message)
    return rows[:limit]


def _expected_host_terms(
    tool_outputs: list[tuple[str, str]],
    user_message: str,
) -> list[str]:
    rows = _matching_host_threshold_rows(tool_outputs, user_message)
    terms: list[str] = []
    seen: set[str] = set()
    for row in rows:
        host_name = str(row.get("host") or row.get("name") or row.get("hostname") or "")
        if host_name and host_name.lower() not in seen:
            seen.add(host_name.lower())
            terms.append(host_name)
    return terms


def _format_host_threshold_rows(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for idx, row in enumerate(rows, start=1):
        host = row.get("host") or row.get("name") or row.get("hostname") or "unknown-host"
        site = row.get("site") or "unknown-site"
        state = row.get("state") or "unknown"
        cores = row.get("cores_available")
        ram = row.get("ram_available_gb")
        disk = row.get("disk_available_gb")
        lines.append(
            f"{idx}. {host} at {site}: state={state}, "
            f"cores_available={cores}, ram_available_gb={ram}, disk_available_gb={disk}"
        )
    return "\n".join(lines)


def _host_threshold_completion_block(
    tool_outputs: list[tuple[str, str]],
    user_message: str,
) -> str:
    rows = _matching_host_threshold_rows(tool_outputs, user_message)
    if not rows:
        return ""
    return (
        "LoomAI completed host-threshold enumeration from collected tool results:\n"
        + _format_host_threshold_rows(rows)
    )


async def _collect_host_threshold_inventory(user_message: str) -> str:
    """Collect cross-site host rows for threshold queries before model output."""
    from app.routes.resources import list_site_hosts, list_sites

    sites = await list_sites(max_age=0)
    resource_field = _host_resource_field(user_message)
    threshold_value = _host_threshold_value(user_message)
    requested_limit = _requested_result_limit(user_message)
    all_rows: list[dict[str, Any]] = []
    site_count = 0
    site_errors: dict[str, str] = {}

    if not isinstance(sites, list):
        sites = []

    for site in sites:
        if not isinstance(site, dict):
            continue
        site_name = str(site.get("name") or site.get("site") or "").strip()
        if not site_name:
            continue
        site_count += 1
        site_state = str(site.get("state") or "")
        host_rows = site.get("hosts_detail")
        if not isinstance(host_rows, list):
            try:
                host_rows = await list_site_hosts(site_name)
            except Exception as exc:
                site_errors[site_name] = str(exc)[:160]
                host_rows = []
        if not isinstance(host_rows, list):
            continue
        for host in host_rows:
            if not isinstance(host, dict):
                continue
            normalized = _normalize_host_resource_row(
                host,
                site_name=site_name,
                site_state=site_state,
            )
            if normalized.get("host"):
                all_rows.append(normalized)

    matching_rows = list(all_rows)
    if resource_field and threshold_value is not None:
        matching_rows = [
            row for row in matching_rows
            if (_numeric_value(row.get(resource_field)) or 0.0) >= threshold_value
        ]
    if resource_field:
        matching_rows.sort(key=lambda row: (
            -(_numeric_value(row.get(resource_field)) or 0.0),
            str(row.get("site") or ""),
            str(row.get("host") or ""),
        ))

    returned_rows = matching_rows[:requested_limit]
    payload = {
        "source": "resources.host_threshold_prefetch",
        "captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "summary": {
            "site_count": site_count,
            "host_count": len(all_rows),
            "matching_host_count": len(matching_rows),
            "returned_rows": len(returned_rows),
            "requested_limit": requested_limit,
            "resource_field": resource_field,
            "threshold_value": threshold_value,
        },
        "rows": returned_rows,
        "all_returned_hosts": [row["host"] for row in returned_rows if row.get("host")],
        "truncated": len(matching_rows) > len(returned_rows),
        "omitted_host_count": max(0, len(matching_rows) - len(returned_rows)),
    }
    if site_errors:
        payload["site_errors"] = site_errors
    return json.dumps(payload, default=str)


def _expected_slice_terms(tool_outputs: list[tuple[str, str]], user_message: str) -> list[str]:
    if "slice" not in (user_message or "").lower():
        return []
    limit = _requested_result_limit(user_message)
    terms: list[str] = []
    seen: set[str] = set()
    for tool_name, result in tool_outputs:
        if tool_name != "list_slices":
            continue
        data = _safe_json_loads(result)
        slice_rows = data.get("slices") if isinstance(data, dict) else data
        if not isinstance(slice_rows, list):
            continue
        for row in slice_rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or row.get("id") or "")
            if name and name.lower() not in seen:
                seen.add(name.lower())
                terms.append(name)
            if len(terms) >= limit:
                return terms
    return terms


def _missing_terms(answer: str, terms: list[str]) -> list[str]:
    answer_lower = (answer or "").lower()
    return [term for term in terms if term.lower() not in answer_lower]


def _validate_fabric_query_final_answer(
    answer: str,
    user_message: str,
    tool_names: list[str],
    tool_outputs: list[tuple[str, str]] | None = None,
    *,
    require_final_answer_marker: bool = True,
) -> list[str]:
    reasons: list[str] = []
    stripped = (answer or "").strip()
    msg_lower = (user_message or "").lower()
    tool_outputs = tool_outputs or []
    if not stripped:
        reasons.append("empty final answer")
        return reasons
    if _PROGRESS_ONLY_RE.search(stripped) and not _RESOURCE_TERMS_RE.search(stripped):
        reasons.append("progress-only answer")
    if require_final_answer_marker and "FINAL ANSWER" not in stripped.upper():
        reasons.append("missing FINAL ANSWER marker")

    identifiers = _extract_user_identifiers(user_message)
    if identifiers:
        missing = [ident for ident in identifiers if ident.lower() not in stripped.lower()]
        if missing:
            reasons.append(f"missing user identifier(s): {', '.join(missing[:3])}")
    if any(k in msg_lower for k in ("invalid", "not_a", "not-a-real", "fake", "unknown")):
        if not _INVALID_TERMS_RE.search(stripped):
            reasons.append("missing invalid/not-found language")
    if any(t in {"query_sites", "get_site_hosts"} for t in tool_names):
        if not _RESOURCE_TERMS_RE.search(stripped):
            reasons.append("missing resource/site/host terms after resource tools")
    expected_hosts = _expected_host_terms(tool_outputs, user_message)
    if expected_hosts:
        missing_hosts = _missing_terms(stripped, expected_hosts)
        if missing_hosts:
            reasons.append(
                "missing benchmark-visible host(s): "
                + ", ".join(missing_hosts[:20])
            )
    expected_slices = _expected_slice_terms(tool_outputs, user_message)
    if expected_slices:
        missing_slices = _missing_terms(stripped, expected_slices)
        if missing_slices:
            reasons.append(
                "missing slice name(s): "
                + ", ".join(missing_slices[:20])
            )
    return reasons


def _retry_expected_terms(tool_outputs: list[tuple[str, str]], user_message: str) -> str:
    parts: list[str] = []
    host_rows = _matching_host_threshold_rows(tool_outputs, user_message)
    if host_rows:
        parts.append(
            "Host rows that must be enumerated exactly:\n"
            + _format_host_threshold_rows(host_rows)
        )
    slices = _expected_slice_terms(tool_outputs, user_message)
    if slices:
        parts.append("Slice names that must be enumerated: " + ", ".join(slices[:20]))
    return "\n".join(parts)


def _build_fabric_query_retry_prompt(
    validation_reasons: list[str],
    expected_terms: str,
    *,
    best_effort_without_contract: bool = False,
) -> str:
    expected_terms_block = f"\n{expected_terms}" if expected_terms else ""
    if best_effort_without_contract:
        return (
            "Your previous response was empty under the strict FABRIC query "
            "response contract. Do not use the strict FINAL ANSWER contract on "
            "this retry, and do not run more tools. Using only the tool results "
            "already available in this conversation, give a concise best-effort "
            "answer in normal prose with exact site names, host names, resource "
            "counts, invalid identifiers, tools used, and caveats when present. "
            "For host threshold queries, enumerate EVERY benchmark-visible host "
            "up to the requested limit from the collected tool rows; do not give "
            "examples or a site-only summary. "
            f"Validation issues: {'; '.join(validation_reasons)}"
            f"{expected_terms_block}"
        )
    return (
        "Your previous response was incomplete for this FABRIC query. "
        "Do not run more tools. Using only the tool results already "
        "available in this conversation, return only the FINAL ANSWER "
        "with exact site names, host names, resource counts, invalid "
        "identifiers, tools used, and caveats. For host threshold "
        "queries, enumerate EVERY benchmark-visible host up to the "
        "requested limit from the collected tool rows; do not give "
        "examples or a site-only summary. "
        f"Validation issues: {'; '.join(validation_reasons)}"
        f"{expected_terms_block}"
    )


_SUCCESS_CLAIM_RE = re.compile(
    r"\b(success|successful|succeeded|working|works|verified|ready|reachable|passed|complete|completed|done)\b",
    re.IGNORECASE,
)


def _compact_command_output(text: Any, *, max_chars: int = 320) -> str:
    """Return a short, single-line command-output snippet for final answers."""
    value = str(text or "").strip()
    if not value:
        return ""
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    snippet = " | ".join(lines[:5])
    if len(snippet) > max_chars:
        snippet = snippet[: max_chars - 3].rstrip() + "..."
    return snippet


def _verification_evidence_lines(tool_outputs: list[tuple[str, str]]) -> list[str]:
    """Extract real command-output proof lines from verification tool results."""
    lines: list[str] = []
    for tool_name, result in tool_outputs:
        data = _safe_json_loads(result)
        if not isinstance(data, dict):
            continue
        if tool_name == "configure_networking":
            for ping in data.get("pings") or []:
                if not isinstance(ping, dict) or not ping.get("ok"):
                    continue
                stdout = _compact_command_output(ping.get("stdout"))
                stderr = _compact_command_output(ping.get("stderr"))
                output = stdout or stderr
                if not output:
                    continue
                source = ping.get("source_node") or "source"
                target = ping.get("target_node") or ping.get("target_ip") or "target"
                target_ip = ping.get("target_ip") or "unknown-ip"
                command = ping.get("command") or "ping"
                network = ping.get("network") or "network"
                lines.append(
                    f"- configure_networking {source}->{target} ({network}, {target_ip}) "
                    f"`{command}`: {output}"
                )
        elif tool_name == "ssh_execute":
            stdout = _compact_command_output(data.get("stdout"))
            stderr = _compact_command_output(data.get("stderr"))
            output = stdout or stderr
            if not output:
                continue
            node = data.get("node_name") or "node"
            command = data.get("command") or "ssh_execute"
            label = "stdout" if stdout else "stderr"
            lines.append(f"- ssh_execute {node} `{command}` {label}: {output}")
        elif tool_name == "get_background_run_output":
            output = _compact_command_output(data.get("output"))
            if not output:
                continue
            run_id = data.get("run_id") or "run"
            status = data.get("status") or "unknown"
            lines.append(f"- get_background_run_output {run_id} status={status}: {output}")
    return lines[:6]


def _apply_verification_evidence_guard(
    answer: str,
    tool_outputs: list[tuple[str, str]],
) -> tuple[str, bool, bool]:
    """Prepend concrete verification evidence before operational success claims.

    Returns ``(answer, guard_applied, evidence_appended)``. ``guard_applied``
    means the non-streaming final answer should be used so a second streaming
    call cannot drift away from the checked evidence.
    """
    final_text = (answer or "").strip()
    if not final_text or not _SUCCESS_CLAIM_RE.search(final_text):
        return answer, False, False

    evidence_lines = _verification_evidence_lines(tool_outputs)
    if not evidence_lines:
        return answer, False, False

    if "verification evidence" in final_text.lower():
        return final_text, True, False

    evidence_block = "Verification evidence:\n" + "\n".join(evidence_lines)
    return f"{evidence_block}\n\n{final_text}", True, True


_TOOL_CALL_PLACEHOLDER = (
    "I am running the requested tools and will answer using their results."
)


def _build_empty_visible_final_retry_prompt(
    tool_outputs: list[tuple[str, str]],
) -> str:
    """Prompt a model to recover after returning no visible final answer."""
    evidence_lines = _verification_evidence_lines(tool_outputs)
    evidence_block = (
        "\n\nVerification evidence already captured:\n" + "\n".join(evidence_lines)
        if evidence_lines else ""
    )
    return (
        "Your previous response had no visible final answer after tool execution. "
        "Do not run more tools. Using only the tool results already available in "
        "this conversation, give the user a concise final answer. If you claim "
        "success, include the real command output or verification evidence before "
        "the success claim."
        f"{evidence_block}"
    )


def _synthesize_empty_visible_answer(tool_outputs: list[tuple[str, str]]) -> str:
    """Create a minimal fallback answer when an LLM stays visibly silent."""
    evidence_lines = _verification_evidence_lines(tool_outputs)
    if evidence_lines:
        return (
            "The model returned no visible final answer after tool execution. "
            "Here is the captured verification evidence:\n"
            + "\n".join(evidence_lines)
        )
    tool_names = [name for name, _ in tool_outputs if name]
    if not tool_names:
        return ""
    recent = ", ".join(tool_names[-6:])
    return (
        "The model returned no visible final answer after tool execution. "
        f"Tools completed in this turn: {recent}. Review the tool result cards "
        "above for the exact outputs."
    )


def _tool_context_limit(
    tool_name: str,
    user_message: str,
    profile: dict,
    *,
    compact_resource_tools_enabled: bool,
    background: bool = False,
) -> int:
    if tool_name in {"query_sites", "get_site_hosts"} and compact_resource_tools_enabled:
        return max(profile["tool_result_max"], _RESOURCE_TOOL_CONTEXT_LIMIT)
    if tool_name == "list_slices":
        if "slice" in (user_message or "").lower() and not background:
            return max(profile["tool_result_max"], _SLICE_QUERY_CONTEXT_LIMIT)
        return 300
    if tool_name == "search_examples":
        return max(profile["tool_result_max"], 6000)
    return profile["tool_result_max"]


def _parse_agent_file(fpath: str) -> dict[str, str] | None:
    """Parse a single agent .md file into {name, description, prompt}."""
    try:
        with open(fpath, "r") as f:
            content = f.read()
        parsed = parse_markdown_asset(content)
        name = str(parsed.metadata.get("name", ""))
        desc = str(parsed.metadata.get("description", ""))
        if not name and not desc:
            return None
        return {"name": name, "description": desc, "prompt": parsed.body}
    except Exception:
        return None


def _load_agents() -> dict[str, dict]:
    """Load agents from built-in dir, then overlay user-custom agents on top."""
    global _agents_cache
    if _agents_cache is not None:
        return _agents_cache

    agents: dict[str, dict] = {}

    # 1. Load built-in agents
    if os.path.isdir(_AGENTS_DIR):
        for fname in sorted(os.listdir(_AGENTS_DIR)):
            if not fname.endswith(".md"):
                continue
            agent_id = fname[:-3]
            if agent_id in ("ai-tools-evaluator",):
                continue
            parsed = _parse_agent_file(os.path.join(_AGENTS_DIR, fname))
            if parsed:
                agents[agent_id] = {"name": parsed["name"] or agent_id, "description": parsed["description"], "prompt": parsed["prompt"]}

    # 2. Overlay user-custom agents
    try:
        from app.settings_manager import get_storage_dir
        custom_dir = os.path.join(get_storage_dir(), ".loomai", "agents")
        if os.path.isdir(custom_dir):
            for fname in sorted(os.listdir(custom_dir)):
                if not fname.endswith(".md"):
                    continue
                agent_id = fname[:-3]
                if agent_id in ("ai-tools-evaluator",):
                    continue
                parsed = _parse_agent_file(os.path.join(custom_dir, fname))
                if parsed:
                    agents[agent_id] = {"name": parsed["name"] or agent_id, "description": parsed["description"], "prompt": parsed["prompt"]}
    except Exception:
        logger.warning("Failed to load custom agents", exc_info=True)

    _agents_cache = agents
    return agents


def _active_agent_system_block(agent_id: str, agent: dict[str, Any], *, explicit: bool) -> str:
    """Return a system-prompt block for an active agent."""
    heading = "Selected Agent" if explicit else "Active Agent"
    authority = (
        "These selected-agent instructions are authoritative for this request. "
        "If later LoomAI runtime context, retrieved context, prefetched data, or "
        "default query-reporter instructions conflict with this agent or the "
        "user's explicit output format, follow this agent and the user."
        if explicit
        else "Follow this agent for the current request."
    )
    return (
        f"## {heading}: {agent.get('name') or agent_id}\n\n"
        f"{authority}\n\n"
        f"{agent.get('prompt') or ''}"
    )


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_slices",
            "description": "List all FABRIC slices for the current user with their state, site, and node count.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_slice",
            "description": "Get detailed information about a specific slice including all nodes, networks, and interfaces.",
            "parameters": {
                "type": "object",
                "properties": {"slice_name": {"type": "string", "description": "Name of the slice"}},
                "required": ["slice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_sites",
            "description": "Query FABRIC sites and their available resources (cores, RAM, disk, GPUs). Returns live availability.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_site_hosts",
            "description": "Get detailed per-host resource availability for a specific site.",
            "parameters": {
                "type": "object",
                "properties": {"site_name": {"type": "string", "description": "FABRIC site name (e.g. RENC, UCSD)"}},
                "required": ["site_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_slice",
            "description": (
                "Create a new empty DRAFT ONLY. This does not provision VMs; "
                "call submit_slice() to provision when the conversation has "
                "authorized submit/deploy/provision or a create-and-verify goal. "
                "If the user requests a lease duration, pass lease_hours so "
                "submit preserves it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name for the new slice"},
                    "lease_hours": {
                        "type": "integer",
                        "description": "Requested lease duration in hours, e.g. 6 for a 6-hour benchmark slice.",
                    },
                    "confirm_new_slice": {
                        "type": "boolean",
                        "description": (
                            "Set true only when the user explicitly asks for an additional "
                            "slice after this conversation already created one."
                        ),
                        "default": False,
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_node",
            "description": "Add a VM node to a draft slice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the draft slice"},
                    "node_name": {"type": "string", "description": "Name for the new node"},
                    "site": {"type": "string", "description": "FABRIC site name (e.g. RENC, UCSD)"},
                    "cores": {"type": "integer", "description": "Number of CPU cores (default 2)", "default": 2},
                    "ram": {"type": "integer", "description": "RAM in GB (default 8)", "default": 8},
                    "disk": {"type": "integer", "description": "Disk in GB (default 10)", "default": 10},
                    "image": {"type": "string", "description": "OS image (default: default_ubuntu_22)", "default": "default_ubuntu_22"},
                },
                "required": ["slice_name", "node_name", "site"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_component",
            "description": "Add a network component (NIC) to a node in a draft slice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the draft slice"},
                    "node_name": {"type": "string", "description": "Name of the node"},
                    "component_name": {"type": "string", "description": "Name for the component (e.g. nic1)"},
                    "model": {"type": "string", "description": "Component model: NIC_Basic, NIC_ConnectX_5, NIC_ConnectX_6, GPU_Tesla_T4, GPU_RTX6000, GPU_A30, GPU_A40, NVME_P4510, FPGA_Xilinx_U280"},
                },
                "required": ["slice_name", "node_name", "component_name", "model"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_fabnet",
            "description": (
                "Attach FABNetv4 or FABNetv6 to a single node in a draft slice. "
                "THIS IS THE CORRECT TOOL FOR MULTI-SITE FABNET CONNECTIVITY. "
                "Call once per node — FABRIC automatically creates a per-site "
                "network and routes between sites via its backbone. Handles "
                "NIC attachment, interface creation, and automatic IP assignment. "
                "Do NOT use add_network(type='FABNetv4') for multi-site — a single "
                "FABNetv4 network cannot span more than one site (FABRIC returns "
                "'Service cannot span N sites. Limit: 1.')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the draft slice"},
                    "node_name": {"type": "string", "description": "Name of the node to attach"},
                    "net_type": {
                        "type": "string",
                        "description": "Address family: IPv4 for FABNetv4, IPv6 for FABNetv6",
                        "enum": ["IPv4", "IPv6"],
                        "default": "IPv4",
                    },
                },
                "required": ["slice_name", "node_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_network",
            "description": (
                "Add a network service to a draft slice and connect node interfaces to it. "
                "Hard limits: L2Bridge is one site; L2STS is exactly two sites; "
                "L2PTP is exactly two interfaces; FABNetv4/v6/Ext services are "
                "one site only and can attach up to 255 VMs. For multi-site "
                "FABNet L3, call add_fabnet once per node or create one FABNet "
                "service per site; never create one FABNet network mixing sites."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the draft slice"},
                    "network_name": {"type": "string", "description": "Name for the network"},
                    "type": {
                        "type": "string",
                        "description": "Network type",
                        "enum": ["L2Bridge", "L2PTP", "L2STS", "FABNetv4", "FABNetv6", "FABNetv4Ext", "FABNetv6Ext", "PortMirror"],
                    },
                    "interfaces": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of interface names to connect (format: nodeName-componentName-pN, e.g. node1-nic1-p1)",
                    },
                },
                "required": ["slice_name", "network_name", "type", "interfaces"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_slice",
            "description": (
                "Submit a draft slice to FABRIC for provisioning. Pass "
                "lease_hours when the user requested a capped lease. For "
                "authorized create-and-verify goals, set "
                "wait_for_stableok=true and background=true, then poll "
                "get_job_status until the submit job is ready before the "
                "final answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice to submit"},
                    "lease_hours": {
                        "type": "integer",
                        "description": "Requested lease duration in hours, e.g. 6 for a 6-hour benchmark slice.",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Optional explicit lease end timestamp in ISO format.",
                    },
                    "wait": {
                        "type": "boolean",
                        "description": "Compatibility alias for wait_for_stableok.",
                        "default": False,
                    },
                    "wait_for_stableok": {
                        "type": "boolean",
                        "description": "Wait for provisioning to reach StableOK/Active before returning.",
                        "default": False,
                    },
                    "background": {
                        "type": "boolean",
                        "description": (
                            "Start submit/wait as a detached backend job and "
                            "return a job_id immediately. Use for long "
                            "wait_for_stableok provisioning, then poll "
                            "get_job_status."
                        ),
                        "default": False,
                    },
                },
                "required": ["slice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_job_status",
            "description": (
                "Poll a background LoomAI job returned by "
                "submit_slice(background=true). Wait until ready before "
                "claiming provisioning, networking, or verification succeeded."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job id returned by a background tool call"},
                    "wait_seconds": {
                        "type": "integer",
                        "description": "Optional long-poll wait before returning status (0-300 seconds).",
                        "default": 0,
                    },
                    "poll_interval": {
                        "type": "number",
                        "description": "Polling interval while wait_seconds is active (default 2 seconds).",
                        "default": 2,
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "configure_networking",
            "description": (
                "Configure post-StableOK VM data-plane networking for a slice. "
                "Use this after submit/provisioning reaches StableOK for private "
                "L2 and FABNetv4 multi-node workflows. It assigns deterministic "
                "private L2 IPs when needed, runs FABlib post_boot_config for "
                "FABNet, adds FABNetv4 10.128.0.0/10 routes, and can verify by "
                "pinging target IP addresses instead of VM hostnames."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the StableOK slice"},
                    "run_post_boot": {
                        "type": "boolean",
                        "description": "Run FABlib post_boot_config before route/ping checks (default true)",
                        "default": True,
                    },
                    "configure_l2": {
                        "type": "boolean",
                        "description": "Assign private L2 interface IPs (default true)",
                        "default": True,
                    },
                    "configure_fabnet": {
                        "type": "boolean",
                        "description": "Configure FABNetv4 IPs/routes when present (default true)",
                        "default": True,
                    },
                    "verify": {
                        "type": "boolean",
                        "description": "Run IP-target ping verification and return stdout evidence (default true)",
                        "default": True,
                    },
                    "l2_subnet_base": {
                        "type": "string",
                        "description": "Base IPv4 subnet for generated private L2 addresses; additional L2 networks increment from it.",
                        "default": "192.168.100.0/24",
                    },
                    "ping_count": {
                        "type": "integer",
                        "description": "ICMP echo count for verification pings (default 3)",
                        "default": 3,
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Per-node command timeout in seconds (default 120, max 1800)",
                        "default": 120,
                    },
                },
                "required": ["slice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_slice",
            "description": "Delete a FABRIC slice.",
            "parameters": {
                "type": "object",
                "properties": {"slice_name": {"type": "string", "description": "Name of the slice to delete"}},
                "required": ["slice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "renew_slice",
            "description": "Renew a slice lease. Use hours/lease_hours for short capped leases such as 6 hours.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice to renew"},
                    "hours": {"type": "integer", "description": "Number of hours from now for the renewed lease end"},
                    "lease_hours": {"type": "integer", "description": "Alias for hours"},
                    "days": {"type": "integer", "description": "Number of days to extend when an hourly cap is not requested"},
                    "end_date": {"type": "string", "description": "Explicit lease end timestamp in ISO format"},
                },
                "required": ["slice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_templates",
            "description": "List available weaves that can be loaded as new slices.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_template",
            "description": "Load a weave as a new draft slice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "template_name": {"type": "string", "description": "Name (dir_name) of the template to load"},
                    "slice_name": {"type": "string", "description": "Name for the new slice created from the template"},
                },
                "required": ["template_name", "slice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clone_slice",
            "description": (
                "Clone an existing FABRIC slice or draft as a new DRAFT slice. "
                "This copies topology and boot configuration only; call "
                "submit_slice() when the user has authorized provisioning."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name or UUID of the source slice/draft"},
                    "new_name": {"type": "string", "description": "Name for the cloned draft slice"},
                },
                "required": ["slice_name", "new_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_as_template",
            "description": "Save a slice as a reusable template.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice to save as template"},
                    "template_name": {"type": "string", "description": "Name for the template"},
                    "description": {"type": "string", "description": "Description of the template"},
                },
                "required": ["slice_name", "template_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_node",
            "description": "Remove a node from a draft slice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the draft slice"},
                    "node_name": {"type": "string", "description": "Name of the node to remove"},
                },
                "required": ["slice_name", "node_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_network",
            "description": "Remove a network from a draft slice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the draft slice"},
                    "network_name": {"type": "string", "description": "Name of the network to remove"},
                },
                "required": ["slice_name", "network_name"],
            },
        },
    },
    # --- File Operations (container filesystem) ---
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file on the container filesystem. Creates parent directories as needed. Use for creating artifacts, scripts, config files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within user storage (e.g. 'my_artifacts/my_weave/weave.sh')"},
                    "content": {"type": "string", "description": "File content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the content of a file on the container filesystem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within user storage"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories at a path on the container filesystem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within user storage (empty string for root)", "default": ""},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "Create a directory on the container filesystem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path for the new directory within user storage"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_path",
            "description": "Delete a file or directory on the container filesystem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within user storage to delete"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python_script",
            "description": (
                "Run a Python script from the container user storage area and "
                "return stdout/stderr. Use this for local data analysis after "
                "writing or collecting result files. The script path and cwd "
                "must stay inside user storage; no shell is used."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to a .py script inside user storage"},
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Command-line arguments passed to the script",
                        "default": [],
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Optional working directory relative to user storage; defaults to the script directory",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Execution timeout in seconds (default 120, max 1800)",
                        "default": 120,
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_jupyter_notebook",
            "description": (
                "Execute a Jupyter notebook (.ipynb) from container user "
                "storage without launching JupyterLab. Use this after writing "
                "or collecting analysis notebooks. The notebook path, output "
                "path, and cwd must stay inside user storage."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to a .ipynb notebook inside user storage"},
                    "output_path": {
                        "type": "string",
                        "description": "Optional relative path for the executed notebook; defaults to overwriting path.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Optional working directory relative to user storage; defaults to the notebook directory",
                    },
                    "kernel_name": {
                        "type": "string",
                        "description": "Kernel name to use (default python3)",
                        "default": "python3",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Per-cell execution timeout in seconds (default 120, max 1800)",
                        "default": 120,
                    },
                },
                "required": ["path"],
            },
        },
    },
    # --- Artifact Management ---
    {
        "type": "function",
        "function": {
            "name": "list_artifacts",
            "description": "List all local artifacts (weaves, VM templates, recipes, notebooks) in the user's artifact directory.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_artifact",
            "description": (
                "Read-only static validation for a local artifact or inline weave payload before running or "
                "publishing. Checks marker JSON, args shape, run_script consistency, shell progress/error "
                "handling, and results/ output path conventions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_name": {"type": "string", "description": "Directory name of the local artifact to validate"},
                    "weave_json": {"type": "object", "description": "Optional inline weave.json content"},
                    "vm_template_json": {"type": "object", "description": "Optional inline vm-template.json content"},
                    "recipe_json": {"type": "object", "description": "Optional inline recipe.json content"},
                    "scripts": {"type": "object", "description": "Optional inline script files keyed by relative path"},
                    "files": {"type": "object", "description": "Optional inline files keyed by relative path"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "publish_artifact",
            "description": "Publish a local artifact to the FABRIC Artifact Manager marketplace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_name": {"type": "string", "description": "Directory name of the local artifact to publish"},
                    "title": {"type": "string", "description": "Human-readable title for the artifact"},
                    "description": {"type": "string", "description": "Description of the artifact", "default": ""},
                    "tags": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "chameleon",
                                "education",
                                "example",
                                "experiment",
                                "experiment pattern",
                                "loomai:recipe",
                                "loomai:vm",
                                "loomai:weave",
                                "reproducible research",
                                "tutorial",
                            ],
                        },
                        "description": "Artifact Manager tags. Use only values returned by /api/artifacts/valid-tags.",
                        "default": [],
                    },
                    "visibility": {"type": "string", "enum": ["author", "project", "public"], "description": "Who can see the artifact (default: author)", "default": "author"},
                },
                "required": ["dir_name", "title"],
            },
        },
    },
    # --- Slice Operations ---
    {
        "type": "function",
        "function": {
            "name": "refresh_slice",
            "description": "Refresh a slice's state from FABRIC. Updates node states, IPs, and other runtime info.",
            "parameters": {
                "type": "object",
                "properties": {"slice_name": {"type": "string", "description": "Name of the slice to refresh"}},
                "required": ["slice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_slice",
            "description": "Validate a slice topology for issues (errors, warnings) before submission.",
            "parameters": {
                "type": "object",
                "properties": {"slice_name": {"type": "string", "description": "Name of the slice to validate"}},
                "required": ["slice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_node",
            "description": "Update properties of a node in a draft slice (site, cores, RAM, disk, image).",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the draft slice"},
                    "node_name": {"type": "string", "description": "Name of the node to update"},
                    "site": {"type": "string", "description": "New site assignment"},
                    "cores": {"type": "integer", "description": "New CPU core count"},
                    "ram": {"type": "integer", "description": "New RAM in GB"},
                    "disk": {"type": "integer", "description": "New disk in GB"},
                    "image": {"type": "string", "description": "New OS image name"},
                },
                "required": ["slice_name", "node_name"],
            },
        },
    },
    # --- VM Operations (SSH) ---
    {
        "type": "function",
        "function": {
            "name": "ssh_execute",
            "description": (
                "Execute a command on a VM node via SSH. The slice must be in "
                "StableOK state. Default timeout is 600s (10 min) which covers "
                "apt update + apt install of ~20 packages. For very long "
                "operations (kernel upgrade, large package sets, docker pulls), "
                "set timeout up to 1800s (30 min)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice"},
                    "node_name": {"type": "string", "description": "Name of the node"},
                    "command": {"type": "string", "description": "Shell command to execute on the VM. For non-interactive apt use DEBIAN_FRONTEND=noninteractive and apt-get -y -qq."},
                    "timeout": {"type": "integer", "description": "Command timeout in seconds (default 600, max 1800)", "default": 600},
                },
                "required": ["slice_name", "node_name", "command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reboot_and_wait",
            "description": (
                "Reboot a VM node and wait for SSH to become reachable again. "
                "Use this in 'reboot if needed' workflows: first check "
                "`test -f /var/run/reboot-required` with ssh_execute; if "
                "present, call this tool, then continue with post-reboot steps. "
                "Returns status 'reachable' with elapsed seconds, or "
                "'unreachable' if the node doesn't come back within the "
                "timeout (default 300s, max 1500s). Safe to call per-node in "
                "multi-node workflows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice"},
                    "node_name": {"type": "string", "description": "Name of the node to reboot"},
                    "timeout": {
                        "type": "integer",
                        "description": "Max seconds to wait for SSH to return (default 300, max 1500)",
                        "default": 300,
                    },
                },
                "required": ["slice_name", "node_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_vm_file",
            "description": "Write content to a file on a VM node via SFTP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice"},
                    "node_name": {"type": "string", "description": "Name of the node"},
                    "path": {"type": "string", "description": "Absolute path on the VM (e.g. /home/ubuntu/script.sh)"},
                    "content": {"type": "string", "description": "File content to write"},
                },
                "required": ["slice_name", "node_name", "path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_vm_file",
            "description": (
                "Read a small text file from a VM node. For large result files "
                "or datasets, use download_file_bulk to copy the file into "
                "container storage, then analyze it with run_python_script."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice"},
                    "node_name": {"type": "string", "description": "Name of the node"},
                    "path": {"type": "string", "description": "Absolute path on the VM to read"},
                },
                "required": ["slice_name", "node_name", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "download_file_bulk",
            "description": (
                "Download a potentially large file from a VM node into "
                "container user storage without inlining the whole file in "
                "chat. Returns local path, size, and a small text preview."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice"},
                    "node_name": {"type": "string", "description": "Name of the node"},
                    "remote_path": {"type": "string", "description": "Absolute path on the VM to download"},
                    "dest_dir": {
                        "type": "string",
                        "description": "Destination directory relative to user storage",
                        "default": "downloads",
                    },
                    "filename": {
                        "type": "string",
                        "description": "Optional local filename; defaults to the remote basename",
                    },
                    "preview_bytes": {
                        "type": "integer",
                        "description": "Bytes of text preview to return (default 4096, max 32000)",
                        "default": 4096,
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Outer download timeout in seconds (default 600, max 1800)",
                        "default": 600,
                    },
                },
                "required": ["slice_name", "node_name", "remote_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_tunnel",
            "description": (
                "Create or reuse a browser-accessible SSH tunnel to a web "
                "service running on a VM node. Use after the service is "
                "running and you know its port."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice containing the VM"},
                    "node_name": {"type": "string", "description": "Name of the VM node"},
                    "port": {"type": "integer", "description": "Remote service port on the VM, e.g. 80 or 8888"},
                    "protocol": {
                        "type": "string",
                        "description": "Protocol spoken by the VM service",
                        "enum": ["http", "https"],
                        "default": "http",
                    },
                },
                "required": ["slice_name", "node_name", "port"],
            },
        },
    },
    # --- Recipe Operations ---
    {
        "type": "function",
        "function": {
            "name": "list_recipes",
            "description": "List available VM recipes that can be applied to running nodes.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_recipe",
            "description": (
                "Apply a VM recipe to a running node. This uploads any recipe "
                "scripts, executes matching recipe steps for the node image, "
                "and returns compact progress/output evidence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "recipe_name": {"type": "string", "description": "Recipe artifact name or directory name"},
                    "slice_name": {"type": "string", "description": "Name of the slice containing the node"},
                    "node_name": {"type": "string", "description": "Name of the target VM node"},
                },
                "required": ["recipe_name", "slice_name", "node_name"],
            },
        },
    },
    # --- JupyterLab ---
    {
        "type": "function",
        "function": {
            "name": "manage_jupyter",
            "description": "Start, stop, or check status of the JupyterLab environment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["start", "stop", "status"], "description": "Action to perform on JupyterLab"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the internet using DuckDuckGo. Returns titles, URLs, and snippets for each result. Use this to find documentation, tutorials, troubleshooting guides, or any information from the web.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query string"},
                    "max_results": {"type": "integer", "description": "Maximum number of results to return (default 5, max 10)", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": "Fetch and extract the main text content from a webpage URL. Use this after web_search to read the full content of a promising result. Returns plain text (HTML tags stripped).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch"},
                    "max_length": {"type": "integer", "description": "Maximum characters to return (default 4000)", "default": 4000},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_background_run",
            "description": "Start a weave script as a background run that survives browser disconnects. Returns a run_id for polling status and output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "weave_dir_name": {"type": "string", "description": "Directory name of the weave (e.g. 'My_Weave')"},
                    "script": {"type": "string", "description": "Script to run (default 'auto' resolves from weave.json)", "default": "auto"},
                    "slice_name": {"type": "string", "description": "Slice name to pass to the script (optional)", "default": ""},
                },
                "required": ["weave_dir_name", "script"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_background_runs",
            "description": "List all background runs (active and completed) with their status, timestamps, and weave info.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_background_run_output",
            "description": "Get output from a background run. Pass offset=0 for all output, or the last offset for incremental reads.",
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "string", "description": "The run ID returned by start_background_run"},
                    "offset": {"type": "integer", "description": "Byte offset to read from (0 for all output)", "default": 0},
                },
                "required": ["run_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_background_run",
            "description": "Stop a running background run.",
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "string", "description": "The run ID to stop"},
                },
                "required": ["run_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_weave",
            "description": "Create a new FABRIC weave experiment. YOU MUST provide script_content with a complete Python script that uses FABlib to create, provision, and configure the slice. The script must have start(slice_name), stop(slice_name), and monitor(slice_name) functions. Include exactly as many VMs, networks, components (GPUs, SmartNICs, etc.), and software installs as the experiment requires. Use node.execute() to install software and run experiments after provisioning. If you omit script_content, a basic template is generated. NOTE: This is for FABRIC only. To package a SPHERE experiment as a weave, use package_sphere_experiment instead — create_weave produces a generic FABRIC weave that cannot be sent to a SPHERE XDC.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Weave name (used as directory name)"},
                    "description": {"type": "string", "description": "What this weave does (1-2 sentences)"},
                    "num_nodes": {"type": "integer", "description": "Number of VMs (fallback if no script_content)", "default": 2},
                    "site": {"type": "string", "description": "FABRIC site or 'auto' (fallback if no script_content)", "default": "auto"},
                    "network_type": {"type": "string", "description": "Network type (fallback if no script_content): 'L2Bridge' or 'FABNetv4'", "default": "L2Bridge"},
                    "script_content": {"type": "string", "description": "REQUIRED: Complete Python experiment script with start/stop/monitor functions using FABlib. Create the right number of nodes, networks, and components for the experiment. Install software via node.execute(). See FABRIC_AI.md for FABlib API examples."},
                    "include_notebooks": {"type": "boolean", "description": "Include Jupyter notebook (default: true)", "default": True},
                    "include_node_tools": {"type": "boolean", "description": "Include node setup scripts (default: false)", "default": False},
                    "include_data_folder": {"type": "boolean", "description": "Include data/ folder (default: false)", "default": False},
                    "node_tools_content": {"type": "string", "description": "Shell script content for node setup (e.g. 'sudo apt install iperf3')"},
                    "notebook_description": {"type": "string", "description": "What the notebook should cover"},
                    "weave_md": {"type": "string", "description": "Custom weave.md spec content (leave empty to auto-generate)"},
                },
                "required": ["name", "script_content"],
            },
        },
    },
    # --- Chameleon Cloud tools ---
    {
        "type": "function",
        "function": {
            "name": "list_chameleon_leases",
            "description": "List Chameleon Cloud leases (reservations) with status, site, and dates. Optionally filter by site.",
            "parameters": {
                "type": "object",
                "properties": {"site": {"type": "string", "description": "Chameleon site (e.g. CHI@TACC, CHI@UC). Omit to list all."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_chameleon_instances",
            "description": "List running Chameleon Cloud instances (servers) with status, IP, and site.",
            "parameters": {
                "type": "object",
                "properties": {"site": {"type": "string", "description": "Chameleon site to query. Omit for all sites."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_chameleon_sites",
            "description": "List Chameleon Cloud sites (CHI@TACC, CHI@UC, etc.) with configuration status and location.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "chameleon_site_images",
            "description": "List available OS images at a Chameleon site.",
            "parameters": {
                "type": "object",
                "properties": {"site": {"type": "string", "description": "Chameleon site (e.g. CHI@TACC)"}},
                "required": ["site"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_chameleon_lease",
            "description": "Create a new Chameleon lease (reservation) for bare-metal nodes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "site": {"type": "string", "description": "Chameleon site (e.g. CHI@TACC)"},
                    "name": {"type": "string", "description": "Lease name"},
                    "node_type": {"type": "string", "description": "Node type (e.g. compute_haswell, gpu_p100)"},
                    "node_count": {"type": "integer", "description": "Number of nodes", "default": 1},
                    "duration_hours": {"type": "integer", "description": "Duration in hours", "default": 4},
                },
                "required": ["site", "name", "node_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_chameleon_lease",
            "description": "Delete a Chameleon lease.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lease_id": {"type": "string", "description": "Lease ID to delete"},
                    "site": {"type": "string", "description": "Chameleon site"},
                },
                "required": ["lease_id", "site"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_chameleon_instance",
            "description": "Launch a Chameleon instance (server) on an existing lease.",
            "parameters": {
                "type": "object",
                "properties": {
                    "site": {"type": "string", "description": "Chameleon site"},
                    "name": {"type": "string", "description": "Instance name"},
                    "lease_id": {"type": "string", "description": "Lease ID to use"},
                    "reservation_id": {"type": "string", "description": "Reservation ID from the lease"},
                    "image_id": {"type": "string", "description": "OS image ID or name (e.g. CC-Ubuntu22.04)"},
                },
                "required": ["site", "name", "image_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_chameleon_instance",
            "description": "Terminate a Chameleon instance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instance_id": {"type": "string", "description": "Instance ID to terminate"},
                    "site": {"type": "string", "description": "Chameleon site"},
                },
                "required": ["instance_id", "site"],
            },
        },
    },
    # --- Chameleon Slice tools (LoomAI abstraction) ---
    {
        "type": "function",
        "function": {
            "name": "list_chameleon_slices",
            "description": "List Chameleon slices (LoomAI's grouping of Chameleon servers). Each slice groups bare-metal instances into a logical experiment unit.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deploy_chameleon_slice",
            "description": "Deploy a Chameleon slice draft — creates leases, launches instances, configures networking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string", "description": "Draft ID to deploy"},
                    "hours": {"type": "integer", "description": "Lease duration in hours", "default": 4},
                },
                "required": ["draft_id"],
            },
        },
    },
    # --- Federated slice tools (cross-testbed) ---
    {
        "type": "function",
        "function": {
            "name": "list_composite_slices",
            "description": "List federated slices — cross-testbed groupings that connect FABRIC and Chameleon slices.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_composite_slice",
            "description": "Get details of a federated slice including its FABRIC and Chameleon member slices.",
            "parameters": {
                "type": "object",
                "properties": {"slice_id": {"type": "string", "description": "Federated slice ID"}},
                "required": ["slice_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_composite_slice",
            "description": "Create a new federated slice to group FABRIC and Chameleon slices together.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Name for the federated slice"}},
                "required": ["name"],
            },
        },
    },
    # --- SPHERE / MergeTB tools ---
    {
        "type": "function",
        "function": {
            "name": "sphere_status",
            "description": "SPHERE/MergeTB integration status: enabled, configured, and the default project.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_sphere_experiments",
            "description": "List SPHERE experiments in the project with name, description, and creator.",
            "parameters": {
                "type": "object",
                "properties": {"project": {"type": "string", "description": "SPHERE project. Omit for the configured default."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_sphere_experiment",
            "description": "Create a SPHERE experiment. Name must be lowercase letters and digits only (no hyphens/underscores/uppercase), max 63 chars.",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment": {"type": "string", "description": "Experiment name (lowercase alnum, e.g. 'myexp')"},
                    "description": {"type": "string", "description": "Human-readable description"},
                    "project": {"type": "string", "description": "SPHERE project. Omit for default."},
                },
                "required": ["experiment"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "push_sphere_model",
            "description": "Push a mergexp Python topology model to a SPHERE experiment. Always tag the push (e.g. 'v1') — model revisions have no ordering, so tags are the only reliable reference for realize.",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment": {"type": "string", "description": "Experiment name"},
                    "model": {"type": "string", "description": "mergexp Python source (from mergexp import *; net = Network(...); ...; experiment(net))"},
                    "tag": {"type": "string", "description": "Tag for this revision (e.g. 'v1')"},
                    "project": {"type": "string", "description": "SPHERE project. Omit for default."},
                },
                "required": ["experiment", "model", "tag"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_sphere_realizations",
            "description": "List SPHERE realizations with derived state (complete/failed/pending), error, node/link counts, and expiry.",
            "parameters": {
                "type": "object",
                "properties": {"project": {"type": "string", "description": "SPHERE project. Omit for default."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sphere_realize",
            "description": "Realize a SPHERE experiment — reserve testbed resources for a tagged model revision. Follow with sphere_materialize once the realization state is 'complete'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment": {"type": "string", "description": "Experiment name"},
                    "realization": {"type": "string", "description": "Realization name (e.g. 'r0')"},
                    "tag": {"type": "string", "description": "Model tag to realize (matches push_sphere_model tag)"},
                    "duration": {"type": "string", "description": "Reservation duration (e.g. '24h'). Omit for default."},
                    "project": {"type": "string", "description": "SPHERE project. Omit for default."},
                },
                "required": ["experiment", "realization", "tag"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sphere_materialize",
            "description": "Materialize a realized SPHERE experiment — power on, image, and wire the nodes. Poll get_sphere_materialization until HighestStatus is 'Success'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment": {"type": "string", "description": "Experiment name"},
                    "realization": {"type": "string", "description": "Realization name"},
                    "project": {"type": "string", "description": "SPHERE project. Omit for default."},
                },
                "required": ["experiment", "realization"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sphere_materialization",
            "description": "Get SPHERE materialization status. Ready when taskSummary.HighestStatus == 'Success' (typically a few minutes after materialize).",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment": {"type": "string", "description": "Experiment name"},
                    "realization": {"type": "string", "description": "Realization name"},
                    "project": {"type": "string", "description": "SPHERE project. Omit for default."},
                },
                "required": ["experiment", "realization"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sphere_dematerialize",
            "description": "Dematerialize a SPHERE experiment — power off its nodes (always confirm with user!). The realization stays reserved.",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment": {"type": "string", "description": "Experiment name"},
                    "realization": {"type": "string", "description": "Realization name"},
                    "project": {"type": "string", "description": "SPHERE project. Omit for default."},
                },
                "required": ["experiment", "realization"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sphere_relinquish",
            "description": "Relinquish a SPHERE realization — release the resource reservation (always confirm with user!). Dematerialize first if materialized.",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment": {"type": "string", "description": "Experiment name"},
                    "realization": {"type": "string", "description": "Realization name"},
                    "project": {"type": "string", "description": "SPHERE project. Omit for default."},
                },
                "required": ["experiment", "realization"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_sphere_xdcs",
            "description": "List SPHERE XDCs (jump containers used to reach experiment nodes) with readiness and attachments.",
            "parameters": {
                "type": "object",
                "properties": {"project": {"type": "string", "description": "SPHERE project. Omit for default."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_sphere_xdc",
            "description": (
                "Create a SPHERE XDC (jump container used to reach experiment nodes). "
                "XDC name must be bare and match ^[a-z][a-z0-9]{0,62}$ (lowercase letters/digits "
                "only; no hyphens, underscores, uppercase, or .project suffix). In non-personal "
                "projects (e.g. fabricsphere) the type MUST be 'shared' — personal XDCs are rejected. "
                "One shared XDC can serve many realizations, so prefer reusing an existing shared XDC "
                "(list_sphere_xdcs) over creating a new one. After creating, use attach_sphere_xdc to "
                "wire it to a realization."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "xdc": {"type": "string", "description": "XDC name (bare, lowercase alnum, ^[a-z][a-z0-9]{0,62}$)"},
                    "type": {"type": "string", "enum": ["shared", "personal"], "description": "XDC type. Must be 'shared' in non-personal projects. Defaults to 'shared'."},
                    "project": {"type": "string", "description": "SPHERE project. Omit for default."},
                },
                "required": ["xdc"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "attach_sphere_xdc",
            "description": "Attach a SPHERE XDC to a realization so its nodes become reachable (SSH goes jump host -> XDC -> node). XDC name is bare (no .project suffix).",
            "parameters": {
                "type": "object",
                "properties": {
                    "xdc": {"type": "string", "description": "XDC name (bare, lowercase alnum)"},
                    "experiment": {"type": "string", "description": "Experiment name"},
                    "realization": {"type": "string", "description": "Realization name"},
                    "project": {"type": "string", "description": "SPHERE project. Omit for default."},
                },
                "required": ["xdc", "experiment", "realization"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detach_sphere_xdc",
            "description": "Detach a SPHERE XDC from a realization. XDC name is bare (no .project suffix).",
            "parameters": {
                "type": "object",
                "properties": {
                    "xdc": {"type": "string", "description": "XDC name (bare, lowercase alnum)"},
                    "experiment": {"type": "string", "description": "Experiment name"},
                    "realization": {"type": "string", "description": "Realization name"},
                    "project": {"type": "string", "description": "SPHERE project. Omit for default."},
                },
                "required": ["xdc", "experiment", "realization"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_sphere_xdc",
            "description": (
                "Delete a SPHERE XDC. Destructive — confirm with the user first, and check it is not "
                "still attached to a realization (detach first). XDC name is bare (no .project suffix)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "xdc": {"type": "string", "description": "XDC name (bare, lowercase alnum)"},
                    "project": {"type": "string", "description": "SPHERE project. Omit for default."},
                },
                "required": ["xdc"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "package_sphere_experiment",
            "description": (
                "Package a SPHERE experiment + realization into a reproducible "
                "'sphere-experiment-v1' weave in My Artifacts (regenerated mergexp "
                "model + starter analysis notebook + per-node setup scripts + weave.json). "
                "This is the ONLY correct way to make a SPHERE weave — NEVER use create_weave "
                "for SPHERE (that produces a generic FABRIC weave that cannot be sent to an XDC). "
                "Requires the experiment to already have a realization (preferred) or a pushed "
                "model. After packaging, the weave shows up in Libraries and can be sent to an "
                "XDC (Notebook tab) or published."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment": {"type": "string", "description": "Experiment name"},
                    "name": {"type": "string", "description": "Weave name (e.g. 'netsec1-detector')"},
                    "realization": {"type": "string", "description": "Realization to package (default 'r0'); its materialized topology is preferred over the raw model."},
                    "description": {"type": "string", "description": "Short description of what the experiment does"},
                    "scripts": {
                        "type": "array",
                        "description": "Per-node setup scripts bundled into the weave; the notebook pushes/runs them on nodes.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Script filename (e.g. 'detector.py')"},
                                "target": {"type": "string", "description": "Node name to run on, or 'all'"},
                                "content": {"type": "string", "description": "Script source code"},
                            },
                            "required": ["name", "target", "content"],
                        },
                    },
                    "include_notebook": {"type": "boolean", "description": "Include the auto-generated starter analysis notebook (default true). Ignored if 'notebook' is provided."},
                    "notebook": {
                        "type": "array",
                        "description": "OPTIONAL: your own notebook as an ordered list of cells; replaces the auto-generated starter. It MUST run the experiment end-to-end, not just analyze — a freshly materialized realization has NO data yet, so an analysis-only notebook finds nothing. Order the cells: (1) connect to nodes via the XDC, (2) deploy & start the setup scripts (e.g. launch detector.py on the gateway) and verify they run, (3) generate/trigger the traffic or workload under study, (4) collect the produced output (e.g. alerts.jsonl) back to the XDC, (5) load/summarize/plot. Never assume the output file already exists.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "cell_type": {"type": "string", "enum": ["code", "markdown"], "description": "Cell type"},
                                "source": {"type": "string", "description": "Cell contents (Python for code cells, Markdown for markdown cells)"},
                            },
                            "required": ["cell_type", "source"],
                        },
                    },
                    "project": {"type": "string", "description": "SPHERE project. Omit for default."},
                },
                "required": ["experiment", "name"],
            },
        },
    },
    # --- FABlib examples RAG ---
    {
        "type": "function",
        "function": {
            "name": "search_examples",
            "description": "Search FABlib code examples by keyword. Returns matching examples with their full source code included. Do NOT call read_file on the results — the code is already in the response. Examples: 'fabnetv4', 'gpu', 'l2 network', 'weave lifecycle', 'iperf'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords (e.g. 'fabnetv4 cross-site', 'gpu rtx6000', 'l2 bridge network')"},
                },
                "required": ["query"],
            },
        },
    },
    # --- FABRIC infrastructure metrics (proxied to the fabric-metrics MCP) ---
    # Three routing tools instead of the server's 17, so the remote surface
    # costs three slots against the per-model tool budget. They mirror the
    # server's own contract: list_metric_topics -> pick a topic + variant ->
    # query_infrastructure_metrics.
    {
        "type": "function",
        "function": {
            "name": "list_metric_topics",
            "description": (
                "List the FABRIC infrastructure-metrics topics (cpu, memory, disk, "
                "filesystem, network, sockets, netstat, system, time, temperature, "
                "link_status, link_traffic, port_traffic) with the variants and "
                "parameters each accepts. Call this FIRST to route a metrics question, "
                "then call query_infrastructure_metrics with the topic and variant it "
                "names. Never invent a topic or variant."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_metric_param_options",
            "description": (
                "List the allowed live values for one parameter of a metrics topic — "
                "e.g. the node names, switch devices, or interfaces that currently "
                "report data. Use it when you need a concrete value for a "
                "query_infrastructure_metrics parameter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic name, e.g. 'cpu' or 'link_traffic'"},
                    "param": {"type": "string", "description": "Parameter to enumerate, e.g. 'node', 'src_rack', 'interface'"},
                },
                "required": ["topic", "param"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_infrastructure_metrics",
            "description": (
                "Query live FABRIC infrastructure metrics from the Grafana/Prometheus "
                "dashboards — node CPU, memory, disk, filesystem, network, sockets, "
                "system, temperature, and switch link/port traffic. Pick 'topic' and "
                "'variant' from list_metric_topics; never write PromQL. Use "
                "topic='list_sites' with no variant to list the FABRIC rack codes that "
                "have node data. This reports on FABRIC infrastructure health, not on "
                "the user's own VMs — for in-slice metrics use the monitoring tools."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Topic from list_metric_topics, e.g. 'cpu', 'temperature', 'link_traffic', 'list_sites'",
                    },
                    "variant": {
                        "type": "string",
                        "description": "Variant for that topic, exactly as list_metric_topics spells it. Omit only for 'list_sites'/'list_topics'.",
                    },
                    "args": {
                        "type": "object",
                        "description": (
                            "Topic parameters, e.g. {\"node\": \"ncsa\"} for node topics or "
                            "{\"src_rack\": \"ncsa\", \"dst_rack\": \"cern\"} for link traffic. "
                            "Optional range keys: start, end, step, mode."
                        ),
                        "additionalProperties": True,
                    },
                },
                "required": ["topic"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution — calls existing backend functions
# ---------------------------------------------------------------------------

def _run_sync(func, *args, **kwargs) -> Any:
    """Run a sync function and return its result (for use in async context)."""
    return func(*args, **kwargs)


def _is_transient_provider_status(status_code: int | None) -> bool:
    """Return true for provider statuses worth retrying with backoff."""
    return status_code is not None and 500 <= int(status_code) <= 599


_TOOLS_UNSUPPORTED_RE = re.compile(
    r"(?:tool(?:s|[_ -]choice|[_ -]calling|[_ -]use)?|function(?:s|[_ -]calling|_call)?)"
    r"[^.\n]{0,40}(?:not supported|unsupported|not available|not allowed|not enabled|"
    r"does not support|doesn't support|unknown parameter|unrecognized|invalid parameter|requires --)"
    r"|(?:not support|does not support|doesn't support|unsupported)[^.\n]{0,40}(?:tool|function)"
    r"|(?:invalid|unknown|unrecognized|unsupported|unexpected) (?:parameter|argument|field|key)s?[^.\n]{0,20}(?:tool|function)",
    re.IGNORECASE,
)
# Message-ordering errors mention tools too but mean "fix the conversation",
# not "this model cannot call tools".
_TOOL_SEQUENCE_RE = re.compile(
    r"must (?:follow|be a response to)|tool_call_id|tool message|preceding message|role 'tool'|"
    r"messages with role",
    re.IGNORECASE,
)


def _error_says_tools_unsupported(error_text: str) -> bool:
    """True when a provider 4xx means the model cannot take a ``tools``
    parameter at all, as opposed to any error that happens to contain the
    word "tool" (the old check), which disabled tools for the turn on a
    tool-message ordering error and told the user the model had no tool
    support."""
    text = error_text or ""
    if _TOOL_SEQUENCE_RE.search(text):
        return False
    return bool(_TOOLS_UNSUPPORTED_RE.search(text))


def _provider_error_payload(status_code: int, error_text: str, retry_count: int = 0) -> dict[str, Any]:
    """Build a structured SSE error payload for provider failures."""
    transient = _is_transient_provider_status(status_code)
    return {
        "error": f"LLM error {status_code}: {error_text[:300]}",
        "error_type": "transient" if transient else "permanent",
        "retryable": transient,
        "provider_status": status_code,
        "provider_retry_count": retry_count,
    }


async def _post_llm_json_with_retries(
    endpoint: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    timeout: float = 300.0,
    max_retries: int = 2,
) -> tuple[httpx.Response, int]:
    """POST to an LLM endpoint, retrying transient 5xx responses."""
    retry_count = 0
    while True:
        resp = await ai_client.post(endpoint, headers=headers, json=body, timeout=timeout)
        if not _is_transient_provider_status(resp.status_code) or retry_count >= max_retries:
            return resp, retry_count
        retry_count += 1
        delay = min(0.05 * (2 ** (retry_count - 1)), 0.5)
        logger.info(
            "LLM provider returned transient status %s; retrying attempt %s/%s after %.2fs",
            resp.status_code,
            retry_count,
            max_retries,
            delay,
        )
        await asyncio.sleep(delay)


def _is_token_expired_error(status_code: int | None, text: str) -> bool:
    """Detect FABRIC auth/token expiry in tool errors."""
    lower = (text or "").lower()
    if not lower:
        return False
    has_auth_status = status_code in {401, 403} or "401" in lower or "403" in lower
    has_token_language = "token" in lower or "credential" in lower or "oauth" in lower
    has_expiry_language = (
        "expired" in lower
        or "expiration" in lower
        or "unauthorized" in lower
        or "forbidden" in lower
        or "invalid_grant" in lower
    )
    return has_auth_status and has_token_language and has_expiry_language


def _tool_result_is_token_expired(result: str) -> bool:
    """Return true if a JSON/text tool result carries token-expiry evidence."""
    if not result:
        return False
    status_code: int | None = None
    text = result
    try:
        data = json.loads(result)
        if isinstance(data, dict):
            raw_status = data.get("status_code") or data.get("status")
            try:
                status_code = int(raw_status) if raw_status is not None else None
            except (TypeError, ValueError):
                status_code = None
            pieces = [
                str(data.get("error") or ""),
                str(data.get("detail") or ""),
                str(data.get("message") or ""),
                str(data.get("error_code") or ""),
            ]
            text = " ".join(p for p in pieces if p) or result
    except Exception:
        pass
    return _is_token_expired_error(status_code, text)


def _token_expired_event(tool_name: str, detail: str = "") -> dict[str, Any]:
    """Build a clear token-expired SSE payload."""
    return {
        "event": "TOKEN_EXPIRED",
        "error_code": "TOKEN_EXPIRED",
        "error": "FABRIC token expired or unauthorized. Please re-login and retry the request.",
        "tool": tool_name,
        "detail": detail[:500],
    }


_NO_PROGRESS_VOLATILE_KEYS = {
    "age",
    "cache_age",
    "cached_at",
    "created",
    "created_at",
    "duration",
    "duration_ms",
    "elapsed",
    "elapsed_ms",
    "finished_at",
    "last_updated",
    "request_id",
    "started_at",
    "timestamp",
    "updated_at",
}


# Tools that genuinely poll a long-running background job. The exemption below
# is keyed on the tool NAME, not on a bare "status" field: plenty of unrelated
# results say status="running" to mean READY -- ai_terminal returns it for a web
# service that is already serving -- and telling a user to "check back in a few
# minutes" for something already up is worse than the message being fixed.
_RUN_POLLING_TOOLS = {"get_background_run_output", "get_job_status"}


def _is_still_running_poll(result: Any, tool_name: str = "") -> bool:
    """True when a run-polling tool reports work still in progress.

    Used to tell a healthy long-running poll apart from a genuinely stuck
    tool, so the two can be reported differently. Restricted to
    _RUN_POLLING_TOOLS on purpose -- see the note there.
    """
    if tool_name not in _RUN_POLLING_TOOLS:
        return False
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (ValueError, TypeError):
            return False
    if not isinstance(result, dict):
        return False
    return str(result.get("status") or "").lower() in {"running", "pending", "starting"}


def _normalize_tool_fingerprint_value(value: Any) -> Any:
    """Return a stable value for repeated-tool/no-progress comparison."""
    if isinstance(value, dict):
        return {
            str(key): _normalize_tool_fingerprint_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key).lower() not in _NO_PROGRESS_VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_normalize_tool_fingerprint_value(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value.strip())[:16000]
    return value


def _json_fingerprint(value: Any) -> str:
    """JSON-stable fingerprint for tool args/results."""
    normalized = _normalize_tool_fingerprint_value(value)
    try:
        return json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        return str(normalized)


def _tool_call_fingerprint(tool_name: str, args: dict[str, Any]) -> str:
    """Fingerprint a tool call by name and normalized arguments."""
    return f"{tool_name}:{_json_fingerprint(args or {})}"


def _tool_result_fingerprint(result: str) -> str:
    """Fingerprint a tool result while ignoring purely volatile metadata."""
    if not result:
        return ""
    try:
        parsed = json.loads(result)
    except Exception:
        return _json_fingerprint(result)
    return _json_fingerprint(parsed)


def _record_tool_progress(
    tracker: dict[str, dict[str, Any]],
    tool_name: str,
    args: dict[str, Any],
    result: str,
    *,
    limit: int = 3,
) -> dict[str, Any] | None:
    """Track repeated identical tool calls and return stop metadata if stuck."""
    call_key = _tool_call_fingerprint(tool_name, args)
    result_key = _tool_result_fingerprint(result)
    previous = tracker.get(call_key)
    if previous and previous.get("result") == result_key:
        count = int(previous.get("count") or 0) + 1
    else:
        count = 1
    tracker[call_key] = {
        "result": result_key,
        "count": count,
    }
    if count < max(2, int(limit or 3)):
        return None
    if _is_still_running_poll(result, tool_name):
        # Still bounded — the model cannot wait, so more polling is pointless.
        # But this is a healthy long job, not a stuck tool, and saying
        # "result did not change" makes users read it as a failed run.
        return {
            "reason": "still_running",
            "tool": tool_name,
            "repeat_count": count,
            "message": (
                f"Stopped polling {tool_name} after {count} calls — the run is "
                "still in progress, which is expected for a long weave."
            ),
        }
    return {
        "reason": "no_progress",
        "tool": tool_name,
        "repeat_count": count,
        "message": (
            f"Stopped after {count} identical {tool_name} calls with the "
            "same arguments and unchanged result."
        ),
    }


def _estimated_turn_cost(tokens: int, cost_per_1k_tokens_usd: float) -> float:
    """Return estimated cost for tokens when a local rate is configured."""
    if cost_per_1k_tokens_usd <= 0:
        return 0.0
    return (max(0, tokens) / 1000.0) * cost_per_1k_tokens_usd


def _single_sse_response(payload: dict[str, Any]) -> StreamingResponse:
    """Return a StreamingResponse containing one JSON SSE event."""
    return StreamingResponse(
        iter([f"data: {json.dumps(payload)}\n\n".encode()]),
        media_type="text/event-stream",
    )


def _chat_config_exception(error_code: str, message: str, *, provider: str) -> HTTPException:
    """Return a non-200 chat configuration error before SSE streaming starts."""
    return HTTPException(
        status_code=503,
        detail={
            "error": error_code,
            "message": message,
            "provider": provider,
        },
    )


async def _collect_sse_json_events(response: StreamingResponse, *, max_events: int = 80) -> dict[str, Any]:
    """Consume an internal SSE response and return compact JSON event history."""
    events: list[dict[str, Any]] = []
    final_event: dict[str, Any] = {}

    async for chunk in response.body_iterator:
        text = chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else str(chunk)
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if not payload:
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                event = {"event": "raw", "message": payload}
            if event.get("event") == "done":
                final_event = event
            events.append(event)
            if len(events) > max_events:
                events = events[-max_events:]

    status = final_event.get("status")
    if not status:
        status = "completed" if events else "unknown"
    summary: dict[str, Any] = {
        "status": status,
        "events": events,
    }
    if final_event:
        summary["final_event"] = final_event
    if "results" in final_event:
        summary["results"] = final_event["results"]
    return summary


# FABlib examples index (loaded once, cached)
_examples_index: list[dict] | None = None

def _load_examples_index() -> list[dict]:
    """Load the FABlib examples index from disk."""
    global _examples_index
    if _examples_index is not None:
        return _examples_index
    index_path = os.path.join(_APP_ROOT, "ai-tools", "fablib-examples", "INDEX.json")
    if not os.path.isfile(index_path):
        _examples_index = []
        return _examples_index
    with open(index_path) as f:
        _examples_index = json.load(f)
    return _examples_index


async def _search_examples(query: str) -> str:
    """Search FABlib examples by keyword matching on title, tags, and description."""
    index = _load_examples_index()
    if not index:
        return json.dumps({"results": [], "note": "No examples index found"})

    keywords = query.lower().split()
    scored: list[tuple[int, dict]] = []

    for entry in index:
        score = 0
        searchable = f"{entry.get('title', '')} {' '.join(entry.get('tags', []))} {entry.get('description', '')}".lower()
        for kw in keywords:
            if kw in searchable:
                score += 1
            # Bonus for tag match (more specific)
            if kw in [t.lower() for t in entry.get('tags', [])]:
                score += 1
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: -x[0])

    examples_dir = os.path.join(_APP_ROOT, "ai-tools", "fablib-examples")
    results = []
    total_content_chars = 0
    content_budget = 5000  # Total chars for all inline content

    for score, entry in scored:
        item = {
            "file": entry["file"],
            "title": entry["title"],
            "description": entry["description"],
            "tags": entry.get("tags", []),
        }
        # Include file content for top results that fit in the budget
        if total_content_chars < content_budget:
            fpath = os.path.join(examples_dir, entry["file"])
            if os.path.isfile(fpath):
                try:
                    with open(fpath) as ef:
                        content = ef.read()
                    remaining = content_budget - total_content_chars
                    if len(content) > remaining:
                        content = content[:remaining] + "\n# ... (truncated)"
                    item["content"] = content
                    total_content_chars += len(content)
                except Exception:
                    pass
        results.append(item)
        if len(results) >= 8:
            break

    total = len(scored)
    note = f"Found {total} examples, showing top {len(results)}"
    return json.dumps({"query": query, "results": results, "note": note})


async def _create_weave_tool(args: dict) -> str:
    """Create a complete weave directory with all required files."""
    from app.user_context import get_user_storage
    import re

    name = args["name"]
    description = args.get("description", "") or f"FABRIC experiment: {name}"
    script_content = args.get("script_content", "")
    num_nodes = args.get("num_nodes", 2)
    site = args.get("site", "auto")
    network_type = args.get("network_type", "L2Bridge")

    # Sanitize name for directory
    dir_name = re.sub(r'[^\w\-]', '_', name).strip('_')
    if not dir_name:
        return json.dumps({"error": "Invalid weave name"})

    base = get_user_storage()
    weave_dir = os.path.join(base, "my_artifacts", dir_name)
    if os.path.exists(weave_dir):
        return json.dumps({"error": f"Weave '{dir_name}' already exists"})

    os.makedirs(weave_dir, exist_ok=True)
    created_files = []

    # weave.json
    py_name = re.sub(r'[^\w]', '_', name.lower()).strip('_')
    weave_config = {
        "run_script": "weave.sh",
        "log_file": "weave.log",
        "name": name,
        "description": description,
        "category": "weave",
        "args": [
            {"name": "SLICE_NAME", "label": "Slice Name", "type": "string",
             "required": True, "default": dir_name.lower().replace('_', '-'),
             "description": "Name for the FABRIC slice"},
        ],
    }
    with open(os.path.join(weave_dir, "weave.json"), "w") as f:
        json.dump(weave_config, f, indent=2)
    created_files.append("weave.json")

    # weave.sh — standard orchestrator
    weave_sh = f'''#!/bin/bash
set -e

SLICE_NAME="${{SLICE_NAME:-{dir_name.lower().replace('_', '-')}}}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cleanup() {{
    echo "### PROGRESS: Stopping experiment..."
    python3 "$SCRIPT_DIR/{py_name}.py" stop "$SLICE_NAME"
    echo "### PROGRESS: Cleanup complete"
    exit 0
}}
trap cleanup SIGTERM SIGINT

echo "### PROGRESS: Starting experiment '$SLICE_NAME'..."
python3 "$SCRIPT_DIR/{py_name}.py" start "$SLICE_NAME"

echo "### PROGRESS: Experiment running. Monitoring..."
while true; do
    python3 "$SCRIPT_DIR/{py_name}.py" monitor "$SLICE_NAME"
    if [ $? -ne 0 ]; then
        echo "### PROGRESS: Monitor detected an issue, stopping..."
        cleanup
    fi
    sleep 30 &
    wait $!
done
'''
    with open(os.path.join(weave_dir, "weave.sh"), "w") as f:
        f.write(weave_sh)
    os.chmod(os.path.join(weave_dir, "weave.sh"), 0o755)
    created_files.append("weave.sh")

    # Python experiment script — uses num_nodes, site, and network_type
    if not script_content:
        slice_default = dir_name.lower().replace('_', '-')
        site_arg = f'"{site}"' if site and site != "auto" else "None"

        # Build node creation code
        node_lines = []
        nic_lines = []
        for i in range(1, num_nodes + 1):
            node_lines.append(
                f'    node{i} = slice_obj.add_node(name="node{i}", site={site_arg}, cores=2, ram=8, disk=10, image="default_ubuntu_22")'
            )
            if num_nodes >= 2 and network_type:
                nic_lines.append(f'    iface{i} = node{i}.add_component(model="NIC_Basic", name="nic1").get_interfaces()[0]')

        nodes_code = "\n".join(node_lines)
        nics_code = "\n".join(nic_lines) if nic_lines else ""

        # Build network code
        net_code = ""
        if num_nodes >= 2 and network_type:
            iface_list = ", ".join(f"iface{i}" for i in range(1, num_nodes + 1))
            if network_type in ("FABNetv4", "IPv4"):
                net_code = f'    slice_obj.add_l3network(name="net1", interfaces=[{iface_list}], type="IPv4")'
            else:
                net_code = f'    slice_obj.add_l2network(name="net1", interfaces=[{iface_list}], type="{network_type}")'

        total_steps = 3 if num_nodes == 1 else 4
        step = 1

        script_content = f'''#!/usr/bin/env python3
"""
{name} — FABRIC Experiment Lifecycle Script

{num_nodes}-node FABRIC slice managed with the FABlib Python API.
Edit this file to customize the topology, add nodes, networks, and software.

Usage:
  python3 {py_name}.py start <slice-name>   # Create and provision
  python3 {py_name}.py stop  <slice-name>   # Tear down
  python3 {py_name}.py monitor <slice-name> # Health check

FABlib docs: https://fabric-testbed.github.io/fabrictestbed-extensions/
"""

import os
import sys


def _max_lease_hours_from_env():
    raw = os.environ.get("FABRIC_MAX_LEASE_HOURS", "").strip()
    if not raw:
        return None
    try:
        hours = int(raw)
    except ValueError:
        print("### PROGRESS: Ignoring invalid FABRIC_MAX_LEASE_HOURS=%r" % raw)
        return None
    return hours if hours > 0 else None


def _submit_with_lease_policy(slice_obj):
    max_lease_hours = _max_lease_hours_from_env()
    if max_lease_hours:
        print("### PROGRESS: Applying lease cap: %s hours" % max_lease_hours)
        slice_obj.submit(lease_in_hours=max_lease_hours)
    else:
        slice_obj.submit()


def start(slice_name: str):
    """Create and provision a {num_nodes}-node FABRIC slice."""
    from fabrictestbed_extensions.fablib.fablib import FablibManager
    fablib = FablibManager()

    print(f"### PROGRESS: Step {step}/{total_steps} — Creating slice '{{slice_name}}'...")
    slice_obj = fablib.new_slice(name=slice_name)

    # Add {num_nodes} node{"s" if num_nodes > 1 else ""}
{nodes_code}
'''
        if nics_code:
            step2 = step + 1
            script_content += f'''
    # Add NICs and network
    print("### PROGRESS: Step {step2}/{total_steps} — Adding network...")
{nics_code}
{net_code}
'''

        submit_step = total_steps - 1
        ssh_step = total_steps
        script_content += f'''
    # Submit and wait
    print("### PROGRESS: Step {submit_step}/{total_steps} — Submitting slice (3-5 minutes)...")
    _submit_with_lease_policy(slice_obj)
    print("### PROGRESS: Step {ssh_step}/{total_steps} — Waiting for SSH access...")
    slice_obj.wait_ssh(progress=True)

    # Re-fetch slice — node objects from add_node() go stale after submit
    slice_obj = fablib.get_slice(name=slice_name)

    # Configure networking
    slice_obj.post_boot_config()

    print()
    print(f"### PROGRESS: READY! Slice '{{slice_name}}' is provisioned.")
    for n in slice_obj.get_nodes():
        print(f"  {{n.get_name()}}: {{n.get_management_ip()}} ({{n.get_site()}})")
    print()
    print("  SSH: ssh -F /home/fabric/work/fabric_config/ssh_config <management_ip>")


def stop(slice_name: str):
    """Delete the slice and free all FABRIC resources."""
    from fabrictestbed_extensions.fablib.fablib import FablibManager
    fablib = FablibManager()
    print(f"### PROGRESS: Deleting slice '{{slice_name}}'...")
    try:
        slice_obj = fablib.get_slice(name=slice_name)
        slice_obj.delete()
        print("### PROGRESS: Slice deleted.")
    except Exception as e:
        print(f"### PROGRESS: Could not delete (may already be gone): {{e}}")


def monitor(slice_name: str):
    """Check slice health. Exit 1 on failure (triggers cleanup in weave.sh)."""
    from fabrictestbed_extensions.fablib.fablib import FablibManager
    fablib = FablibManager()
    try:
        slice_obj = fablib.get_slice(name=slice_name)
        state = str(slice_obj.get_state())
        if "StableOK" not in state:
            print(f"WARNING: Slice state is {{state}}")
            sys.exit(1)
        for node in slice_obj.get_nodes():
            stdout, _ = node.execute("echo ok", quiet=True)
            if "ok" not in stdout:
                raise Exception(f"Node {{node.get_name()}} not responding")
        print(f"### PROGRESS: Healthy — {{state}}")
    except Exception as e:
        print(f"ERROR: {{e}}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {py_name}.py {{start|stop|monitor}} SLICE_NAME")
        sys.exit(1)
    action, name = sys.argv[1], sys.argv[2]
    {{"start": start, "stop": stop, "monitor": monitor}}[action](name)
'''
    with open(os.path.join(weave_dir, f"{py_name}.py"), "w") as f:
        f.write(script_content)
    created_files.append(f"{py_name}.py")

    # .weaveignore
    with open(os.path.join(weave_dir, ".weaveignore"), "w") as f:
        f.write("# Files excluded from publishing\ndata/\nresults/\n*.csv\n*.key\nsecrets/\n.ipynb_checkpoints/\nweave.log\n")
    created_files.append(".weaveignore")

    # weave.log — empty log file (populated when the weave runs)
    with open(os.path.join(weave_dir, "weave.log"), "w") as f:
        f.write("")
    created_files.append("weave.log")

    # weave.md — human-readable specification and description of the weave.
    # Users can edit this file and ask LoomAI to update the weave accordingly.
    # LoomAI reads this file as the baseline specification when modifying the weave.
    weave_md_content = args.get("weave_md", "")
    if not weave_md_content:
        weave_md_content = f"""# {name}

{description}

## Overview

A single-node FABRIC slice. Edit this file to customize, then ask LoomAI
to "update the weave called {dir_name} based on weave.md".

## Files

| File | Description |
|------|-------------|
| `{py_name}.py` | Python lifecycle script (start/stop/monitor) using FABlib |
| `{py_name}.ipynb` | Jupyter notebook for interacting with the slice |
| `weave.sh` | Shell orchestrator — runs the Python script, handles Stop button |
| `weave.json` | Metadata, run config, and argument definitions |
| `weave.md` | This file — weave specification (edit to update the weave) |

## Specification

Edit this section to describe what you want. Then ask LoomAI to update.

### Nodes
- 1 node: 2 cores, 8GB RAM, 10GB disk, site=auto (FABRIC picks)
- Image: default_ubuntu_22

### Network
- (none — add networks here if needed, e.g. "L2Bridge between 2 nodes" or "FABNetv4 for cross-site")

### Software
- (none — add packages here, e.g. "install iperf3 and htop on all nodes")

### Lifecycle
- **start**: Create slice with 1 node, submit, wait for SSH
- **stop**: Delete slice
- **monitor**: Check slice state is StableOK, verify SSH
"""
    with open(os.path.join(weave_dir, "weave.md"), "w") as f:
        f.write(weave_md_content)
    created_files.append("weave.md")

    # --- Optional extras ---

    # data/ folder for results collection
    if args.get("include_data_folder"):
        data_dir = os.path.join(weave_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, ".gitkeep"), "w") as f:
            f.write("")
        with open(os.path.join(data_dir, "README.md"), "w") as f:
            f.write(f"# Data\n\nExperiment results for {name}.\n\nThis folder is excluded from publishing via `.weaveignore`.\n")
        created_files.append("data/README.md")

    # node_tools/ folder for scripts copied to VMs
    if args.get("include_node_tools"):
        tools_dir = os.path.join(weave_dir, "node_tools")
        os.makedirs(tools_dir, exist_ok=True)
        setup_content = args.get("node_tools_content", "")
        if not setup_content:
            setup_content = f"""#!/bin/bash
# Setup script for {name} — copied to each VM and executed
set -e

echo "Updating packages..."
sudo apt-get update -qq

echo "Installing tools..."
# Add your package installations here:
# sudo apt-get install -y -qq iperf3 htop

echo "Setup complete."
"""
        with open(os.path.join(tools_dir, "setup.sh"), "w") as f:
            f.write(setup_content)
        os.chmod(os.path.join(tools_dir, "setup.sh"), 0o755)
        created_files.append("node_tools/setup.sh")

    # Jupyter notebook — simple single-node FABlib starter at weave root
    if args.get("include_notebooks", True):  # Always include notebook by default
        nb_desc = args.get("notebook_description", f"Interact with the {name} slice")
        slice_default = dir_name.lower().replace('_', '-')
        notebook = {
            "cells": [
                {"cell_type": "markdown", "metadata": {}, "source": [
                    f"# {name}\n",
                    f"\n",
                    f"{nb_desc}\n",
                    f"\n",
                    f"Run the weave first (`weave.sh`) to provision the slice, then use this notebook.\n",
                ]},
                {"cell_type": "markdown", "metadata": {}, "source": [
                    "## 1. Load the Slice\n",
                ]},
                {"cell_type": "code", "metadata": {}, "source": [
                    "from fabrictestbed_extensions.fablib.fablib import FablibManager\n",
                    "\n",
                    "fablib = FablibManager()\n",
                    f"SLICE_NAME = '{slice_default}'\n",
                    "\n",
                    "slice_obj = fablib.get_slice(name=SLICE_NAME)\n",
                    "print(f'Slice: {slice_obj.get_name()} — {slice_obj.get_state()}')\n",
                ], "outputs": [], "execution_count": None},
                {"cell_type": "markdown", "metadata": {}, "source": [
                    "## 2. Node Details\n",
                ]},
                {"cell_type": "code", "metadata": {}, "source": [
                    "for node in slice_obj.get_nodes():\n",
                    "    print(f'{node.get_name()}: {node.get_management_ip()} ({node.get_site()})')\n",
                    "    print(f'  SSH: {node.get_ssh_command()}')\n",
                ], "outputs": [], "execution_count": None},
                {"cell_type": "markdown", "metadata": {}, "source": [
                    "## 3. Run a Command\n",
                ]},
                {"cell_type": "code", "metadata": {}, "source": [
                    "node = slice_obj.get_nodes()[0]\n",
                    "stdout, stderr = node.execute('hostname && uname -a')\n",
                    "print(stdout)\n",
                ], "outputs": [], "execution_count": None},
                {"cell_type": "markdown", "metadata": {}, "source": [
                    "## 4. Clean Up\n",
                ]},
                {"cell_type": "code", "metadata": {}, "source": [
                    "# Uncomment to delete the slice:\n",
                    "# slice_obj.delete()\n",
                    "# print('Slice deleted.')\n",
                ], "outputs": [], "execution_count": None},
            ],
            "metadata": {
                "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                "language_info": {"name": "python", "version": "3.11.0"},
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        nb_filename = f"{py_name}.ipynb"
        with open(os.path.join(weave_dir, nb_filename), "w") as f:
            json.dump(notebook, f, indent=1)
        created_files.append(nb_filename)

    return json.dumps({
        "status": "created",
        "dir_name": dir_name,
        "path": f"my_artifacts/{dir_name}/",
        "files": created_files,
    })


def _tool_summary(name: str, args: dict, result: str) -> str:
    """Generate a concise one-line summary of a tool execution result."""
    try:
        data = json.loads(result) if result else None
    except (json.JSONDecodeError, TypeError):
        data = None

    if name == "list_slices" and isinstance(data, list):
        from collections import Counter
        states = Counter(s.get("state", "?") for s in data)
        parts = [f"{v} {k}" for k, v in states.most_common()]
        return f"Found {len(data)} slice{'s' if len(data) != 1 else ''}" + (f" ({', '.join(parts)})" if parts else "")

    if name == "query_sites" and isinstance(data, list):
        available = [s for s in data if s.get("cores_available", 0) > 0]
        return f"{len(data)} sites ({len(available)} with available cores)"

    if name == "query_sites" and isinstance(data, dict):
        summary = data.get("summary", {})
        site_count = summary.get("site_count", len(data.get("rows", [])))
        returned = summary.get("returned_rows", len(data.get("rows", [])))
        return f"{site_count} sites summarized ({returned} rows returned)"

    if name == "get_site_hosts" and isinstance(data, dict):
        summary = data.get("summary", {})
        host_count = summary.get("host_count", len(data.get("rows", [])))
        returned = summary.get("returned_rows", len(data.get("rows", [])))
        site = data.get("site") or args.get("site_name", "?")
        return f"{host_count} hosts at {site} summarized ({returned} rows returned)"

    if name == "create_slice" and isinstance(data, dict):
        return f"Created draft '{data.get('name', '?')}'"

    if name == "submit_slice":
        sname = args.get("slice_name", "?")
        if isinstance(data, dict) and data.get("job_id"):
            return f"Started submit job {data.get('job_id')} for '{sname}'"
        return f"Submitted '{sname}' for provisioning"

    if name == "get_job_status" and isinstance(data, dict):
        job_id = data.get("job_id") or args.get("job_id", "?")
        status = data.get("status", "?")
        sname = data.get("slice_name") or data.get("name") or "job"
        return f"Job {job_id} for '{sname}' is {status}"

    if name == "delete_slice":
        sname = args.get("slice_name", "?")
        return f"Deleted '{sname}'"

    if name == "renew_slice":
        sname = args.get("slice_name", "?")
        return f"Renewed '{sname}'"

    if name == "add_node" and isinstance(data, dict):
        return f"Added node '{data.get('name', '?')}' at {args.get('site', '?')}"

    if name == "add_network":
        return f"Added network '{args.get('network_name', '?')}'"

    if name == "configure_networking" and isinstance(data, dict):
        pings = data.get("pings") or []
        ok_pings = sum(1 for ping in pings if ping.get("ok"))
        return f"Configured networking for '{args.get('slice_name', '?')}' ({ok_pings}/{len(pings)} ping checks passed)"

    if name == "ssh_execute":
        node = args.get("node_name", "?")
        if isinstance(data, dict):
            exit_code = data.get("exit_code", "?")
            return f"Ran on {node} (exit {exit_code})"
        return f"Ran on {node}"

    if name == "get_slice" and isinstance(data, dict):
        state = data.get("state", "?")
        nodes = len(data.get("nodes", []))
        return f"'{data.get('name', '?')}' — {state}, {nodes} node{'s' if nodes != 1 else ''}"

    if name == "load_template":
        tname = args.get("template_name", "?")
        return f"Loaded template '{tname}'"

    # Chameleon tools
    if name == "list_chameleon_leases" and isinstance(data, list):
        active = sum(1 for l in data if l.get("status") == "ACTIVE")
        return f"Found {len(data)} leases ({active} active)"

    if name == "list_chameleon_instances" and isinstance(data, list):
        return f"Found {len(data)} instances"

    if name == "list_chameleon_sites" and isinstance(data, list):
        configured = sum(1 for s in data if s.get("configured"))
        return f"{len(data)} sites ({configured} configured)"

    if name == "chameleon_site_images" and isinstance(data, list):
        return f"{len(data)} images available"

    if name == "create_chameleon_lease" and isinstance(data, dict):
        return f"Created lease '{data.get('name', '?')}'"

    if name == "create_chameleon_instance" and isinstance(data, dict):
        return f"Launched instance '{data.get('name', '?')}'"

    if name in ("delete_chameleon_lease", "delete_chameleon_instance"):
        return "Deleted"

    if name == "list_chameleon_slices" and isinstance(data, list):
        active = sum(1 for s in data if s.get("state") in ("Active", "Deployed"))
        return f"Found {len(data)} Chameleon slices ({active} active)"

    if name == "deploy_chameleon_slice" and isinstance(data, dict):
        leases = len(data.get("leases", []))
        return f"Deployed draft — {leases} lease{'s' if leases != 1 else ''} created"

    if name == "sphere_status" and isinstance(data, dict):
        if not data.get("enabled"):
            return "SPHERE integration is disabled"
        state = "configured" if data.get("configured") else "not configured"
        return f"SPHERE enabled, {state} — project {data.get('default_project', '?')}"

    if name == "list_sphere_experiments" and isinstance(data, list):
        return f"Found {len(data)} SPHERE experiments"

    if name == "create_sphere_experiment" and isinstance(data, dict):
        return f"Created SPHERE experiment '{data.get('name', '?')}'"

    if name == "push_sphere_model" and isinstance(data, dict):
        return f"Pushed model to '{data.get('experiment', '?')}' (tag {data.get('tag') or 'none'})"

    if name == "list_sphere_realizations" and isinstance(data, list):
        complete = sum(1 for r in data if r.get("state") == "complete")
        return f"Found {len(data)} SPHERE realizations ({complete} complete)"

    if name == "sphere_realize" and isinstance(data, dict):
        return "Realization requested — check list_sphere_realizations for state"

    if name == "sphere_materialize" and isinstance(data, dict):
        return "Materialization started — poll get_sphere_materialization"

    if name == "get_sphere_materialization" and isinstance(data, dict):
        highest = (data.get("taskSummary") or {}).get("HighestStatus", "?")
        return f"Materialization status: {highest}"

    if name in ("sphere_dematerialize", "sphere_relinquish"):
        return "Done"

    if name == "list_sphere_xdcs" and isinstance(data, list):
        return f"Found {len(data)} XDCs"

    if name == "attach_sphere_xdc" and isinstance(data, dict):
        return "XDC attached — nodes reachable via loomai sphere ssh"

    if name == "list_composite_slices" and isinstance(data, list):
        return f"Found {len(data)} federated slices"

    if name == "get_composite_slice" and isinstance(data, dict):
        name_val = data.get("name", "?")
        fab = len(data.get("fabric_slices", []))
        chi = len(data.get("chameleon_slices", []))
        return f"'{name_val}' — {fab} FABRIC + {chi} Chameleon members"

    if name == "create_composite_slice" and isinstance(data, dict):
        return f"Created federated slice '{data.get('name', '?')}'"

    if name == "search_examples" and isinstance(data, dict):
        results = data.get("results", [])
        return data.get("note", f"Found {len(results)} examples")

    # Default: truncate result
    if result:
        clean = result.strip()[:80]
        if len(result) > 80:
            clean += "..."
        return clean
    return "Done"


def _extract_requested_lease_hours(user_message: str) -> int | None:
    """Extract an explicit lease duration from the user's prompt."""
    text = (user_message or "").lower()
    if not text:
        return None
    lease_terms = r"(?:lease|expiration|expire|duration|renew|extend)"
    hour_unit = r"(?:hours?|hrs?|hr|h)"
    day_unit = r"(?:days?|d)"
    week_unit = r"(?:weeks?|w)"
    sep = r"[\s-]*"
    patterns = [
        rf"{lease_terms}[^.\n]{{0,80}}?(\d+){sep}{hour_unit}\b",
        rf"(\d+){sep}{hour_unit}\b[^.\n]{{0,80}}?{lease_terms}",
        r"--lease-hours(?:=|\s+)(\d+)",
        r"lease[_-]?hours?[=:\s]+(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                hours = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if hours > 0:
                return hours
    word_numbers = {
        "a": 1,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
    }
    for word, hours in word_numbers.items():
        word_patterns = [
            rf"{lease_terms}[^.\n]{{0,80}}?\b{word}{sep}{hour_unit}\b",
            rf"\b{word}{sep}{hour_unit}\b[^.\n]{{0,80}}?{lease_terms}",
        ]
        if any(re.search(pattern, text) for pattern in word_patterns):
            return hours
    for pattern, scale in (
        (rf"{lease_terms}[^.\n]{{0,80}}?(\d+){sep}{day_unit}\b", 24),
        (rf"(\d+){sep}{day_unit}\b[^.\n]{{0,80}}?{lease_terms}", 24),
        (rf"{lease_terms}[^.\n]{{0,80}}?(\d+){sep}{week_unit}\b", 24 * 7),
        (rf"(\d+){sep}{week_unit}\b[^.\n]{{0,80}}?{lease_terms}", 24 * 7),
    ):
        match = re.search(pattern, text)
        if match:
            try:
                count = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if count > 0:
                return count * scale
    return None


def _apply_prompt_lease_duration(tool_name: str, args: dict, user_message: str) -> dict:
    """Copy explicit prompt lease duration into lifecycle tool args."""
    if tool_name not in {"create_slice", "submit_slice", "renew_slice"}:
        return args
    lease_hours = _extract_requested_lease_hours(user_message)
    if not lease_hours:
        return args
    updated = dict(args or {})
    if tool_name == "renew_slice":
        updated["hours"] = lease_hours
        updated.pop("days", None)
        updated.pop("end_date", None)
        updated.pop("lease_end", None)
    else:
        updated["lease_hours"] = lease_hours
        updated.pop("end_date", None)
        updated.pop("lease_end", None)
    return updated


# Consent vocabulary and rules live in app.assistant_consent (word-boundary
# matching, latest-turn confirmation, per-conversation pending action). The
# names are kept here for the few call sites that reference them.
from app import assistant_consent as _consent

_PROVISIONING_VERBS = _consent.PROVISIONING_VERBS
_SLICE_BUILD_VERBS = _consent.SLICE_BUILD_VERBS
_OPERATIONAL_PROOF_TERMS = _consent.OPERATIONAL_PROOF_TERMS
_DELETE_TERMS = _consent.DELETE_TERMS
_CONFIRMATION_TERMS = _consent.CONFIRMATION_TERMS
_SLICE_OPERATOR_INTENT_TOOLS = {
    "create_slice",
    "submit_slice",
    "renew_slice",
    "configure_networking",
    "delete_slice",
}


def _message_content(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _conversation_user_texts(messages: list[dict]) -> list[str]:
    return [
        _message_content(message)
        for message in messages
        if isinstance(message, dict) and message.get("role") == "user"
    ]


def _last_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return _message_content(message)
    return ""


def _last_user_message(messages: list[dict]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return {
                "role": "user",
                "content": _message_content(message),
            }
    return None


def _merge_persisted_chat_messages(
    client_messages: list[dict],
    persisted_messages: list[dict],
) -> list[dict]:
    """Resume hidden tool context while appending only the newest client user turn."""
    if not persisted_messages or len(client_messages) <= 1:
        return client_messages
    latest_user = _last_user_message(client_messages)
    if not latest_user or not latest_user.get("content"):
        return persisted_messages
    persisted_latest = _last_user_message(persisted_messages)
    if (
        persisted_latest
        and _message_content(persisted_latest).strip() == latest_user["content"].strip()
    ):
        return persisted_messages
    return persisted_messages + [latest_user]


def _conversation_without_system(conversation: list[dict]) -> list[dict]:
    result: list[dict] = []
    for message in conversation:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "system":
            continue
        if message.get("type") == "message" and message.get("role") == "system":
            continue
        result.append(message)
    return result


def _is_slice_operator_intent(intent_tool: str, user_message: str) -> bool:
    """Return true for slice lifecycle requests that need the operator agent."""
    if intent_tool in _SLICE_OPERATOR_INTENT_TOOLS:
        return True
    lowered = (user_message or "").lower()
    if "configure_networking" in lowered:
        return True
    if "slice" in lowered and "network" in lowered and any(
        term in lowered for term in ("configure", "verify", "ping", "post-stableok", "stableok")
    ):
        return True
    return False


def _conversation_authorizes_provisioning(messages: list[dict]) -> bool:
    """Return true when any user turn grants provisioning/submission consent."""
    return _consent.conversation_authorizes_provisioning(_conversation_user_texts(messages))


_SESSION_STATE_MARKER_PREFIX = "[SESSION-STATE] created-slices:"
_SESSION_STATE_MARKER_RE = re.compile(
    r"^\s*\[SESSION-STATE\]\s+created-slices:\s*(?P<names>[^\n]+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SLICE_NAME_STRIP_CHARS = "'\"`.,:;()[]{}"


def _normalize_created_slice_name(value: Any) -> str:
    name = str(value or "").strip().strip(_SLICE_NAME_STRIP_CHARS).strip()
    return name.lower() if name else ""


def _slice_state_marker_names(text: str) -> set[str]:
    """Return slice names encoded in durable assistant state markers."""
    names: set[str] = set()
    if not text:
        return names
    for match in _SESSION_STATE_MARKER_RE.finditer(text):
        raw_names = match.group("names") or ""
        for part in raw_names.split(","):
            name = _normalize_created_slice_name(part)
            if name:
                names.add(name)
    return names


def _build_session_state_marker(names: set[str] | list[str] | tuple[str, ...]) -> str:
    clean_names = sorted({
        _normalize_created_slice_name(name)
        for name in names
        if _normalize_created_slice_name(name)
    })
    if not clean_names:
        return ""
    return f"{_SESSION_STATE_MARKER_PREFIX} {', '.join(clean_names)}"


def _append_session_state_marker(text: str, names: set[str]) -> tuple[str, bool]:
    """Append a compact visible marker once so stateless clients can recover state."""
    if not names:
        return text or "", False
    base = text or ""
    if _slice_state_marker_names(base):
        return base, False
    marker = _build_session_state_marker(names)
    if not marker:
        return base, False
    separator = "\n\n" if base.strip() else ""
    return f"{base}{separator}{marker}", True


def _extract_conversation_created_slices(messages: list[dict]) -> set[str]:
    """Find slice names that appear to have been created during this chat."""
    names: set[str] = set()
    patterns = (
        r"\bcreated\s+draft\s+['\"`]?([A-Za-z0-9_.:-]+)['\"`]?",
        r"\bcreated\s+(?:a\s+)?(?:new\s+)?slice\s+['\"`]?([A-Za-z0-9_.:-]+)['\"`]?",
        r"\bcreate\s+(?:a\s+)?(?:new\s+)?slice\s+(?:called\s+|named\s+)?['\"`]?([A-Za-z0-9_.:-]+)['\"`]?",
        r"\bslice\s+(?:called\s+|named\s+)['\"`]?([A-Za-z0-9_.:-]+)['\"`]?",
    )
    for message in messages:
        text = _message_content(message)
        if not text:
            continue
        names.update(_slice_state_marker_names(text))
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                name = _normalize_created_slice_name(match.group(1))
                if name:
                    names.add(name)
        data = _safe_json_loads(text)
        if isinstance(data, dict):
            status = str(data.get("status") or "").lower()
            name = data.get("name") or data.get("slice_name")
            if status in {"created", "draft_created"} and name:
                normalized = _normalize_created_slice_name(name)
                if normalized:
                    names.add(normalized)
    return names


def _weak_model_context_management_applies(
    model_key: str,
    profile: dict[str, Any],
    capability_profile: dict[str, Any] | None,
) -> bool:
    """Return true when the current model profile is opted into weak-state help."""
    if bool(profile.get("weak_model_context_management")):
        return True
    if capability_profile and bool(capability_profile.get("weak_model_context_management")):
        return True
    model_lower = str(model_key or profile.get("model") or "").lower()
    # Compatibility fallback for stale external profile files that predate the
    # explicit field but still describe the known failing FC14 model.
    return "qwen3-coder-30b" in model_lower


def _prefetched_slice_name_lookup(tool_outputs: list[tuple[str, str]]) -> dict[str, str]:
    """Map lower-case slice names to display names from prefetched list_slices."""
    lookup: dict[str, str] = {}
    for tool_name, raw in tool_outputs:
        if tool_name != "list_slices":
            continue
        data = _safe_json_loads(raw)
        if not isinstance(data, list):
            continue
        for row in data:
            if isinstance(row, dict) and row.get("name"):
                name = str(row["name"])
                lookup.setdefault(name.lower(), name)
    return lookup


def _compact_session_slice_line(slice_data: dict[str, Any]) -> str:
    name = str(slice_data.get("name") or "").strip() or "unknown-slice"
    state = str(slice_data.get("state") or "unknown").strip() or "unknown"
    nodes = [n for n in (slice_data.get("nodes") or []) if isinstance(n, dict)]
    node_names = [str(n.get("name") or "").strip() for n in nodes if n.get("name")]
    sites = sorted({
        str(n.get("site") or "").strip()
        for n in nodes
        if str(n.get("site") or "").strip()
    })
    networks = [n for n in (slice_data.get("networks") or []) if isinstance(n, dict)]
    network_names = [
        str(n.get("name") or "").strip()
        for n in networks
        if n.get("name")
    ]
    parts = [f"{name}: {state}"]
    if node_names:
        parts.append(f"nodes {', '.join(node_names[:6])}")
    elif slice_data.get("node_count") is not None:
        parts.append(f"{slice_data.get('node_count')} nodes")
    if sites:
        parts.append(f"sites {', '.join(sites[:4])}")
    if network_names:
        parts.append(f"networks {', '.join(network_names[:5])}")
    lease_end = slice_data.get("lease_end")
    if lease_end:
        parts.append(f"lease_end {lease_end}")
    errors = slice_data.get("error_messages") or []
    if errors:
        parts.append(f"errors {json.dumps(errors[:2], default=str)[:160]}")
    return " - " + "; ".join(parts)


async def _build_current_session_state_block(
    created_slices: set[str],
    tool_outputs: list[tuple[str, str]],
    user_message: str,
    request: Request | None,
    state_cache: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Build a compact live-state block for weak models."""
    if not created_slices:
        return ""
    display_names = _prefetched_slice_name_lookup(tool_outputs)
    lines: list[str] = []
    for raw_name in sorted(created_slices)[:5]:
        display_name = display_names.get(raw_name.lower(), raw_name)
        slice_data: dict[str, Any] = {"name": display_name, "state": "unknown"}
        try:
            raw = await execute_tool("get_slice", {"slice_name": display_name}, request=request)
            data = _safe_json_loads(raw)
            if isinstance(data, dict):
                slice_data = data
        except Exception as exc:
            logger.debug("Current session state get_slice failed for %s: %s", display_name, exc)
            for tool_name, raw in tool_outputs:
                if tool_name != "list_slices":
                    continue
                rows = _safe_json_loads(raw)
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if (
                        isinstance(row, dict)
                        and str(row.get("name") or "").lower() == raw_name.lower()
                    ):
                        slice_data = dict(row)
                        break
        if state_cache is not None:
            cache_name = _normalize_created_slice_name(
                slice_data.get("name") or display_name or raw_name
            )
            if cache_name:
                state_cache[cache_name] = dict(slice_data)
        lines.append(_compact_session_slice_line(slice_data))

    if not lines:
        return ""
    remaining = (
        "Continue the user's workflow from the existing slice state. If the "
        "slice is StableOK and verification evidence is still missing, configure "
        "the requested private networking and collect real command output. If it "
        "is not StableOK, poll or fix that slice instead of creating another one."
    )
    if "ping" in (user_message or "").lower():
        remaining = (
            "Continue from the existing slice: configure requested private "
            "networking if needed, then demonstrate vm-to-vm ping with real output."
        )
    return (
        "## CURRENT SESSION STATE\n"
        "Slices you already created this conversation:\n"
        + "\n".join(lines)
        + "\nDo NOT create a new slice. Continue the workflow from the current state.\n"
        f"Remaining for this goal: {remaining}"
    )


def _extract_conversation_submitted_slices(messages: list[dict]) -> set[str]:
    """Find slice names that appear to have been submitted during this chat."""
    names: set[str] = set()
    patterns = (
        r"\bsubmitted\s+(?!slice\b)['\"`]?([A-Za-z0-9_.:-]+)['\"`]?",
        r"\bsubmitted\s+(?:slice\s+)?['\"`]?([A-Za-z0-9_.:-]+)['\"`]?",
        r"\bprovision(?:ed|ing)?\s+(?:slice\s+)?['\"`]?([A-Za-z0-9_.:-]+)['\"`]?",
    )
    for message in messages:
        text = _message_content(message)
        if not text:
            continue
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                name = _normalize_created_slice_name(match.group(1))
                if name:
                    names.add(name)
        data = _safe_json_loads(text)
        if isinstance(data, dict):
            status = str(data.get("status") or "").lower()
            name = data.get("name") or data.get("slice_name")
            if status in {"queued", "running", "submitted", "provisioning", "stableok"} and name:
                normalized = _normalize_created_slice_name(name)
                if normalized:
                    names.add(normalized)
    return names


def _extract_assistant_created_slice_names(messages: list[dict]) -> dict[str, str]:
    """Find draft names the assistant/tool history says were actually created."""
    names: dict[str, str] = {}
    patterns = (
        r"\bcreated\s+draft\s+['\"`]?([A-Za-z0-9_.:-]+)['\"`]?",
        r"\bcreated\s+(?:a\s+)?(?:new\s+)?slice\s+['\"`]?([A-Za-z0-9_.:-]+)['\"`]?",
    )
    for message in messages:
        if not isinstance(message, dict) or message.get("role") == "user":
            continue
        text = _message_content(message)
        if not text:
            continue
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                original = str(match.group(1) or "").strip(_SLICE_NAME_STRIP_CHARS)
                if original:
                    names[original.lower()] = original
        data = _safe_json_loads(text)
        if isinstance(data, dict):
            status = str(data.get("status") or "").lower()
            name = data.get("name") or data.get("slice_name")
            if status in {"created", "draft_created"} and name:
                original = str(name).strip(_SLICE_NAME_STRIP_CHARS)
                if original:
                    names[original.lower()] = original
    return names


def _record_created_slice_from_tool(
    tool_name: str,
    args: dict[str, Any],
    result: str,
    created_slices: set[str],
) -> None:
    if tool_name != "create_slice":
        return
    for value in (args or {}).get("name"), (args or {}).get("slice_name"):
        if value:
            name = _normalize_created_slice_name(value)
            if name:
                created_slices.add(name)
    data = _safe_json_loads(result)
    if isinstance(data, dict):
        for value in data.get("name"), data.get("slice_name"):
            if value:
                name = _normalize_created_slice_name(value)
                if name:
                    created_slices.add(name)


def _slice_state_needs_diagnosis(state: Any) -> bool:
    state_lower = str(state or "").strip().lower()
    return state_lower == "dead" or "error" in state_lower


def _duplicate_slice_guard_result(
    args: dict[str, Any],
    tracked_slices: set[str],
    state_cache: dict[str, dict[str, Any]],
) -> str | None:
    requested_display = str((args or {}).get("name") or (args or {}).get("slice_name") or "").strip()
    requested = _normalize_created_slice_name(requested_display)
    if not requested or requested in tracked_slices:
        return None
    if bool((args or {}).get("confirm_new_slice")):
        return None

    display_by_name: dict[str, str] = {}
    for tracked in tracked_slices:
        state = state_cache.get(tracked) or {}
        display = str(state.get("name") or tracked).strip() or tracked
        display_by_name[tracked] = display
    tracked_order = sorted(tracked_slices)
    primary_key = tracked_order[0]
    primary_display = display_by_name.get(primary_key, primary_key)
    primary_state = state_cache.get(primary_key) or {}
    primary_state_name = str(primary_state.get("state") or "").strip()
    if _slice_state_needs_diagnosis(primary_state_name):
        action = (
            f"this session already created slice '{primary_display}', which is "
            f"currently {primary_state_name}. Diagnose or repair THAT slice "
            "(get_slice/refresh_slice/delete_slice if explicitly authorized) "
            "instead of creating a fresh slice."
        )
    else:
        action = (
            f"this session already created slice '{primary_display}'. Continue "
            "with THAT slice using get_slice, add/modify tools, submit_slice, "
            "or verification tools instead of creating a fresh slice."
        )

    return json.dumps({
        "error": "DUPLICATE_SLICE_GUARD",
        "tool": "create_slice",
        "message": (
            "duplicate-slice-guard: "
            f"{action} Repeat create_slice with confirm_new_slice=true only "
            "if the user explicitly asked for an additional slice."
        ),
        "tracked_slices": [display_by_name.get(name, name) for name in tracked_order],
        "requested_slice": requested_display,
        "confirm_new_slice_required": True,
    }, default=str)


def _tool_output_slice_names(
    tool_outputs: list[tuple[str, str]],
    tool_name: str,
    statuses: set[str],
) -> dict[str, str]:
    """Return lower-case to original-case slice names from matching tool outputs."""
    names: dict[str, str] = {}
    for output_name, result in tool_outputs:
        if output_name != tool_name:
            continue
        data = _safe_json_loads(result)
        if not isinstance(data, dict):
            continue
        status = str(data.get("status") or data.get("state") or "").lower()
        if statuses and status not in statuses:
            continue
        for key in ("name", "slice_name", "id"):
            value = data.get(key)
            if value:
                original = str(value).strip(_SLICE_NAME_STRIP_CHARS)
                if original:
                    names[original.lower()] = original
                    break
    return names


def _pending_background_submit_jobs(tool_outputs: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Return background submit jobs that have not reached a terminal status."""
    pending: dict[str, dict[str, str]] = {}
    done: set[str] = set()
    for output_name, result in tool_outputs:
        data = _safe_json_loads(result)
        if not isinstance(data, dict):
            continue
        job_id = str(data.get("job_id") or "").strip()
        if not job_id:
            continue
        if output_name == "submit_slice" and data.get("background"):
            pending[job_id] = {
                "job_id": job_id,
                "slice_name": str(data.get("slice_name") or data.get("name") or ""),
            }
        if output_name == "get_job_status":
            status = str(data.get("status") or "").lower()
            if data.get("done") or data.get("ready") or status in {"ready", "failed", "not_found"}:
                done.add(job_id)
    return [
        payload
        for job_id, payload in pending.items()
        if job_id not in done
    ]


def _build_background_job_poll_prompt(pending_jobs: list[dict[str, str]]) -> str:
    jobs = ", ".join(
        f"`{job.get('job_id')}`"
        + (f" for slice `{job.get('slice_name')}`" if job.get("slice_name") else "")
        for job in pending_jobs
    )
    return (
        "A background submit job is still pending, so do not give a final "
        "success answer yet. Call `get_job_status(job_id, wait_seconds=30)` "
        f"for: {jobs}. If a job is ready, use its result before continuing. "
        "If it is still running after the status check, either poll again or "
        "report the exact job_id/status without claiming provisioning success."
    )


def _job_ready_sse_payload(tool_name: str, result: str) -> dict[str, Any] | None:
    if tool_name != "get_job_status":
        return None
    data = _safe_json_loads(result)
    if not isinstance(data, dict) or not data.get("ready"):
        return None
    return {
        "job_id": data.get("job_id"),
        "kind": data.get("kind"),
        "slice_name": data.get("slice_name") or data.get("name"),
        "status": data.get("status"),
        "slice_state": data.get("slice_state"),
    }


def _draft_submission_retry_candidates(
    messages: list[dict],
    tool_outputs: list[tuple[str, str]],
) -> list[str]:
    """Return draft slice names that still need submit for an authorized goal."""
    candidates = _extract_assistant_created_slice_names(messages)
    candidates.update(
        _tool_output_slice_names(tool_outputs, "create_slice", {"created", "draft", "draft_created"})
    )
    submitted = _extract_conversation_submitted_slices(messages)
    submitted.update(
        _tool_output_slice_names(
            tool_outputs,
            "submit_slice",
            {"queued", "running", "submitted", "provisioning", "configuring", "stableok", "stable", "ok"},
        )
    )
    return [
        original
        for lower_name, original in candidates.items()
        if lower_name not in submitted
    ]


def _build_draft_submission_retry_prompt(
    slice_names: list[str],
    user_message: str,
) -> str:
    """Prompt the model to submit an authorized draft before final answer."""
    names = ", ".join(f"`{name}`" for name in slice_names)
    lease_hours = _extract_requested_lease_hours(user_message)
    lease_text = (
        f" Include `lease_hours={lease_hours}` on submit_slice."
        if lease_hours else ""
    )
    return (
        "The user authorized provisioning by asking LoomAI to create a working "
        "or verified slice, but the conversation has only created a draft and "
        f"has not submitted it yet. Do not give a final success answer yet. "
        "Call `submit_slice` for these draft slice names with "
        f"`wait_for_stableok=true` and `background=true`: "
        f"{names}.{lease_text} Then poll `get_job_status(job_id, "
        "wait_seconds=30)` until the job is ready. After submit reaches "
        "StableOK, if the task uses a private L2 or FABNet network, call "
        "`configure_networking(slice_name, verify=true)` before the final "
        "answer. If submit fails or is blocked, summarize the exact tool "
        "result instead of claiming success."
    )


def _build_create_slice_guidance(
    args: dict[str, Any],
    user_message: str,
    messages: list[dict],
) -> str:
    """Return model-only guidance after create_slice creates a draft."""
    slice_name = str(
        (args or {}).get("name")
        or (args or {}).get("slice_name")
        or "this slice"
    )
    lease_hours = (
        (args or {}).get("lease_hours")
        or _extract_requested_lease_hours(user_message)
    )
    lease_text = (
        f" Include `lease_hours={lease_hours}` on submit_slice."
        if lease_hours else ""
    )
    if _conversation_authorizes_provisioning(messages):
        return (
            "LoomAI guidance: `create_slice` creates a DRAFT ONLY; it has not "
            "provisioned VMs or submitted anything to FABRIC. The user has "
            "authorized provisioning in this conversation, so after adding the "
            "requested nodes, components, and networks, call "
            f"`submit_slice(slice_name=\"{slice_name}\", wait_for_stableok=true, "
            "background=true)`, then poll `get_job_status(job_id, "
            "wait_seconds=30)` until ready before any final success answer."
            f"{lease_text} If the submitted topology uses private L2 or FABNet connectivity, call "
            "`configure_networking(slice_name, verify=true)` after StableOK "
            "and cite its ping evidence."
        )
    return (
        "LoomAI guidance: `create_slice` creates a DRAFT ONLY; it has not "
        "provisioned VMs or submitted anything to FABRIC. Do not call "
        "`submit_slice` until the user gives submit/deploy/provision "
        "authorization. In the final answer, describe the draft and ask for "
        "one scoped confirmation to submit it."
    )


def _conversation_confirms_delete(messages: list[dict], slice_name: str) -> bool:
    """The latest user turn confirms deleting *slice_name* by name."""
    return _consent.text_confirms_destruction(_last_user_text(messages), [slice_name or ""])


def _is_destructive_tool_authorized(
    tool_name: str,
    args: dict[str, Any],
    messages: list[dict],
    created_slices: set[str],
    conversation_id: str = "",
) -> bool:
    """Apply conversation-scoped authorization for destructive tools.

    See app.assistant_consent for the rules. *conversation_id* lets a bare
    "yes" confirm the action that was blocked on the previous turn.
    """
    return _consent.is_destructive_tool_authorized(
        tool_name,
        args or {},
        user_texts=_conversation_user_texts(messages),
        latest_user_text=_last_user_text(messages),
        created_slices=created_slices,
        conversation_id=conversation_id,
    )


# ---------------------------------------------------------------------------
# FABRIC infrastructure metrics — proxy to the fabric-metrics MCP server
# ---------------------------------------------------------------------------

_METRICS_RESULT_MAX = 6000


def _metrics_topic_tool(topic: str) -> str:
    """Normalize a topic name to the server's tool name.

    Accepts either the bare topic ('cpu') or the fully qualified tool name
    ('fabric_metrics_cpu') — models are inconsistent about which form they
    echo back from list_metric_topics.
    """
    from app.mcp_registry import METRICS_TOOL_PREFIX

    name = (topic or "").strip()
    if not name:
        return ""
    if name.startswith(METRICS_TOOL_PREFIX):
        return name
    return f"{METRICS_TOOL_PREFIX}{name.lstrip('_')}"


def _compact_metrics_topics(text: str) -> str:
    """Shrink the topic catalogue to what routing actually needs.

    fabric_metrics_list_topics returns every topic with full variant prose,
    params and dashboard names — ~13k chars, twice _METRICS_RESULT_MAX. Blind
    truncation cut the JSON mid-structure and appended "narrow the query",
    advice that means nothing for a listing call, so the model re-issued the
    identical call until the repeated-tool guard stopped the turn.

    Keep topic -> short description + variant NAMES + param names. That is
    enough to pick a (topic, variant) pair; list_metric_param_options still
    serves the detail for the one topic the model settles on.
    """
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return text
    if not isinstance(data, dict):
        return text

    compact: dict[str, Any] = {}
    for tool_name, info in data.items():
        if not isinstance(info, dict):
            continue
        topic = info.get("topic") or tool_name
        entry: dict[str, Any] = {}
        desc = info.get("description")
        if isinstance(desc, str) and desc:
            entry["description"] = desc
        variants = info.get("variants")
        if isinstance(variants, dict):
            entry["variants"] = sorted(variants)
        elif isinstance(variants, list):
            entry["variants"] = [v for v in variants if isinstance(v, str)]
        params = info.get("params")
        if isinstance(params, list) and params:
            entry["params"] = [pm for pm in params if isinstance(pm, str)]
        compact[topic] = entry

    if not compact:
        return text
    return json.dumps(compact)


async def _call_metrics_mcp(
    topic: str,
    arguments: dict,
    compact: Callable[[str], str] | None = None,
) -> str:
    """Call one tool on the fabric-metrics MCP server and return JSON text."""
    from app import mcp_client
    from app.mcp_registry import metrics_server

    server = metrics_server()
    if server is None:
        return json.dumps({
            "error": "The FABRIC infrastructure-metrics MCP server is not enabled.",
        })

    tool = _metrics_topic_tool(topic)
    if not tool:
        return json.dumps({
            "error": "No topic given. Call list_metric_topics first to pick one.",
        })

    # Drop null/empty optionals — the server rejects unexpected nulls on some
    # topics and the models like to send them.
    clean = {k: v for k, v in (arguments or {}).items() if v not in (None, "")}

    try:
        result = await mcp_client.call_tool(server, tool, clean)
    except mcp_client.MCPError as e:
        return json.dumps({"error": str(e), "tool": tool})

    text = mcp_client.result_to_text(result)
    # Compact BEFORE the cap. Truncating first would cut the JSON mid-structure
    # and leave the compactor nothing parseable to work with — the model would
    # get the same unusable fragment it used to.
    if compact is not None:
        text = compact(text)
    if len(text) > _METRICS_RESULT_MAX:
        text = text[:_METRICS_RESULT_MAX] + "\n...[truncated — narrow the query]"
    return text


async def execute_tool(name: str, arguments: dict, request: Request | None = None) -> str:
    """Execute a tool and return the result as a JSON string.

    Runs as an agent action, so the agent lease cap applies to any slice
    submit, renew or weave run the tool performs (see ``app.request_actor``).
    """
    from app.request_actor import agent_actor
    with agent_actor():
        return await _execute_tool(name, arguments, request)


async def _execute_tool(name: str, arguments: dict, request: Request | None = None) -> str:
    try:
        if name == "list_slices":
            from app.routes.slices import list_slices
            result = await list_slices(max_age=0)
            # Trim to essential fields
            return json.dumps([{
                "name": s.get("name"), "state": s.get("state"),
                "nodes": len(s.get("nodes", [])),
                "lease_end": s.get("lease_end"),
            } for s in result], default=str)

        elif name == "get_slice":
            from app.routes.slices import get_slice
            result = await get_slice(arguments["slice_name"], max_age=0)
            # Return a COMPACT summary so the result fits in standard tier's
            # tool_result_max (2000 chars). Full topology JSON for a 3-node
            # multi-network slice is 3-6KB and gets truncated mid-node, which
            # caused the LLM to miss later nodes and forget them in multi-node
            # workflows. If the caller needs low-level interface details
            # (MACs, VLAN IDs), they can query specific nodes via ssh_execute.
            nodes_summary = []
            for n in result.get("nodes", []) or []:
                if not isinstance(n, dict):
                    continue
                # Keep only fields a workflow would need: identity, placement,
                # image, IPs, and the network names it's attached to.
                # Include compact interfaces so the model can read
                # dataplane IPs (FABnet, L2) without running ip addr show.
                iface_summary = []
                net_names = []
                for iface in (n.get("interfaces") or []):
                    if isinstance(iface, dict):
                        nn = iface.get("network_name")
                        if nn and nn not in net_names:
                            net_names.append(nn)
                        ip = iface.get("ip_addr")
                        if nn or ip:
                            iface_summary.append({
                                "network_name": nn,
                                "ip_addr": ip,
                            })
                comp_models = []
                for c in (n.get("components") or []):
                    if isinstance(c, dict):
                        m = c.get("model")
                        if m:
                            comp_models.append(m)
                nodes_summary.append({
                    "name": n.get("name"),
                    "site": n.get("site"),
                    "host": n.get("host"),
                    "cores": n.get("cores"),
                    "ram": n.get("ram"),
                    "disk": n.get("disk"),
                    "image": n.get("image"),
                    "management_ip": n.get("management_ip"),
                    "username": n.get("username", "ubuntu"),
                    "reservation_state": n.get("reservation_state"),
                    "error_message": n.get("error_message") or "",
                    "components": comp_models,
                    "interfaces": iface_summary,
                    "networks": net_names,
                })
            networks_summary = []
            for net in result.get("networks", []) or []:
                if not isinstance(net, dict):
                    continue
                networks_summary.append({
                    "name": net.get("name"),
                    "type": net.get("type"),
                    "site": net.get("site"),
                })
            compact = {
                "name": result.get("name"),
                "id": result.get("id"),
                "state": result.get("state"),
                "lease_end": result.get("lease_end"),
                "error_messages": result.get("error_messages") or [],
                "node_count": len(nodes_summary),
                "nodes": nodes_summary,
                "network_count": len(networks_summary),
                "networks": networks_summary,
            }
            return json.dumps(compact, default=str)

        elif name == "query_sites":
            from app.routes.resources import list_sites
            sites = await list_sites(max_age=0)
            from app.settings_manager import is_compact_fabric_resource_tools_enabled
            if is_compact_fabric_resource_tools_enabled():
                return json.dumps(_compact_site_inventory(sites), default=str)
            # Legacy compact list retained until the deployment flag is enabled.
            summary = []
            for s in sites:
                notable_components = _available_components(s)
                gpu_components = _filter_gpu_components(notable_components)
                summary.append({
                    "name": s.get("name"),
                    "cores_available": s.get("cores_available"),
                    "ram_available": s.get("ram_available"),
                    "disk_available": s.get("disk_available"),
                    "state": s.get("state"),
                    "gpus": sum(gpu_components.values()),
                    "gpu_components": gpu_components,
                    "notable_components": notable_components,
                })
            return json.dumps(summary, default=str)

        elif name == "get_site_hosts":
            from app.routes.resources import list_site_hosts
            hosts = await list_site_hosts(arguments["site_name"])
            from app.settings_manager import is_compact_fabric_resource_tools_enabled
            if is_compact_fabric_resource_tools_enabled():
                return json.dumps(
                    _compact_host_inventory(hosts, arguments["site_name"]),
                    default=str,
                )
            host_rows = hosts if isinstance(hosts, list) else []
            enriched_hosts = []
            for host in host_rows:
                if not isinstance(host, dict):
                    enriched_hosts.append(host)
                    continue
                row = dict(host)
                notable_components = _available_components(row)
                gpu_components = _filter_gpu_components(notable_components)
                row["gpus"] = sum(gpu_components.values())
                row["gpu_components"] = gpu_components
                row["notable_components"] = notable_components
                enriched_hosts.append(row)
            return json.dumps(enriched_hosts, default=str)

        elif name == "create_slice":
            from app.routes.slices import CreateSliceRequest, create_slice
            raw_lease_hours = arguments.get("lease_hours")
            lease_hours = None
            if raw_lease_hours is not None and not isinstance(raw_lease_hours, bool):
                try:
                    candidate_lease_hours = int(raw_lease_hours)
                except (TypeError, ValueError):
                    candidate_lease_hours = None
                if candidate_lease_hours and candidate_lease_hours > 0:
                    lease_hours = candidate_lease_hours
            result = await create_slice(CreateSliceRequest(
                name=arguments["name"],
                lease_hours=lease_hours,
            ))
            return json.dumps({
                "status": "created",
                "name": arguments["name"],
                "state": result.get("state", "Draft"),
                "lease_hours": lease_hours,
            }, default=str)

        elif name == "add_node":
            from app.routes.slices import add_node, CreateNodeRequest
            req = CreateNodeRequest(
                name=arguments["node_name"],
                site=arguments.get("site", ""),
                cores=arguments.get("cores", 2),
                ram=arguments.get("ram", 8),
                disk=arguments.get("disk", 10),
                image=arguments.get("image", "default_ubuntu_22"),
            )
            result = await asyncio.to_thread(_run_sync, add_node, arguments["slice_name"], req)
            return json.dumps({"status": "added", "node": arguments["node_name"]}, default=str)

        elif name == "add_component":
            from app.routes.slices import add_component, CreateComponentRequest
            req = CreateComponentRequest(
                name=arguments["component_name"],
                model=arguments["model"],
            )
            result = await asyncio.to_thread(_run_sync, add_component, arguments["slice_name"], arguments["node_name"], req)
            return json.dumps({"status": "added", "component": arguments["component_name"], "model": arguments["model"]}, default=str)

        elif name == "add_fabnet":
            from app.routes.slices import add_fabnet_to_node, AddFabnetRequest
            net_type = arguments.get("net_type", "IPv4")
            req = AddFabnetRequest(net_type=net_type)
            await asyncio.to_thread(
                _run_sync, add_fabnet_to_node,
                arguments["slice_name"], arguments["node_name"], req,
            )
            return json.dumps({
                "status": "attached",
                "node": arguments["node_name"],
                "net_type": net_type,
                "note": f"Per-site FABNet{net_type[-2:].lower()} created; FABRIC backbone routes between sites.",
            }, default=str)

        elif name == "add_network":
            from app.routes.slices import add_network as add_network_fn, CreateNetworkRequest
            req = CreateNetworkRequest(
                name=arguments["network_name"],
                type=arguments["type"],
                interfaces=arguments.get("interfaces", []),
            )
            result = await asyncio.to_thread(_run_sync, add_network_fn, arguments["slice_name"], req)
            return json.dumps({"status": "added", "network": arguments["network_name"], "type": arguments["type"]}, default=str)

        elif name == "submit_slice":
            from app.routes.slices import submit_slice, SubmitSliceRequest
            wait_for_stableok = bool(
                arguments.get("wait_for_stableok", False)
                or arguments.get("wait", False)
            )
            background = bool(arguments.get("background", False))
            req = SubmitSliceRequest(
                lease_hours=arguments.get("lease_hours"),
                end_date=arguments.get("end_date"),
                lease_end=arguments.get("lease_end"),
                wait=wait_for_stableok,
                wait_for_stableok=wait_for_stableok,
                background=background,
            )
            if background:
                from app.assistant_jobs import start_job

                slice_name = arguments["slice_name"]
                foreground_req = (
                    req.model_copy(update={"background": False})
                    if hasattr(req, "model_copy")
                    else req.copy(update={"background": False})
                )
                job_id = await start_job(
                    "submit_slice",
                    lambda: submit_slice(slice_name, foreground_req),
                    metadata={
                        "slice_name": slice_name,
                        "lease_hours": arguments.get("lease_hours"),
                        "wait_for_stableok": wait_for_stableok,
                    },
                )
                return json.dumps({
                    "status": "queued",
                    "state": "queued",
                    "name": slice_name,
                    "slice_name": slice_name,
                    "lease_hours": arguments.get("lease_hours"),
                    "wait": wait_for_stableok,
                    "wait_for_stableok": wait_for_stableok,
                    "background": True,
                    "job_id": job_id,
                    "ready": False,
                    "done": False,
                    "message": (
                        "Submit started in the background. Poll "
                        f"get_job_status(job_id=\"{job_id}\") until ready "
                        "before claiming the slice is provisioned."
                    ),
                }, default=str)
            result = await submit_slice(arguments["slice_name"], req)
            status = result.get("status") or ("queued" if result.get("job_id") else "submitted")
            return json.dumps({
                "status": status,
                "state": result.get("state", "unknown"),
                "name": arguments["slice_name"],
                "lease_hours": arguments.get("lease_hours"),
                "wait": wait_for_stableok,
                "wait_for_stableok": wait_for_stableok,
                "background": background,
                "job_id": result.get("job_id"),
                "ready": result.get("ready"),
                "done": result.get("done"),
                "message": result.get("message"),
            }, default=str)

        elif name == "get_job_status":
            from app.assistant_jobs import get_job_status
            result = await get_job_status(
                arguments["job_id"],
                wait_seconds=arguments.get("wait_seconds", 0),
                poll_interval=arguments.get("poll_interval", 2),
            )
            return json.dumps(result, default=str)

        elif name == "configure_networking":
            from app.routes.slices import configure_networking, ConfigureNetworkingRequest
            req = ConfigureNetworkingRequest(
                run_post_boot=arguments.get("run_post_boot", True),
                configure_l2=arguments.get("configure_l2", True),
                configure_fabnet=arguments.get("configure_fabnet", True),
                verify=arguments.get("verify", True),
                l2_subnet_base=arguments.get("l2_subnet_base", "192.168.100.0/24"),
                ping_count=arguments.get("ping_count", 3),
                timeout=arguments.get("timeout", 120),
            )
            result = await configure_networking(arguments["slice_name"], req)
            return json.dumps(result, default=str)

        elif name == "delete_slice":
            from app.routes.slices import delete_slice
            result = await delete_slice(arguments["slice_name"])
            return json.dumps(result, default=str)

        elif name == "renew_slice":
            from app.routes.slices import renew_slice, RenewRequest
            req = RenewRequest(
                end_date=arguments.get("end_date"),
                lease_end=arguments.get("lease_end"),
                hours=arguments.get("hours"),
                lease_hours=arguments.get("lease_hours"),
                days=arguments.get("days", 7)
                if not any(k in arguments for k in ("end_date", "lease_end", "hours", "lease_hours"))
                else arguments.get("days"),
            )
            result = await renew_slice(arguments["slice_name"], req)
            return json.dumps(result, default=str)

        elif name == "list_templates":
            from app.routes.templates import list_templates
            result = await asyncio.to_thread(_run_sync, list_templates)
            return json.dumps([{
                "name": t.get("name"), "dir_name": t.get("dir_name"),
                "description": t.get("description", ""),
            } for t in result], default=str)

        elif name == "load_template":
            from app.routes.templates import load_template, LoadTemplateRequest
            req = LoadTemplateRequest(slice_name=arguments["slice_name"])
            result = await asyncio.to_thread(_run_sync, load_template, arguments["template_name"], req)
            return json.dumps({"status": "loaded", "slice_name": arguments["slice_name"]}, default=str)

        elif name == "clone_slice":
            from app.routes.slices import clone_slice as clone_slice_fn
            new_name = arguments.get("new_name") or arguments.get("target_name") or arguments.get("name")
            if not new_name:
                return json.dumps({"error": "clone_slice requires new_name"})
            result = await clone_slice_fn(arguments["slice_name"], new_name)
            return json.dumps({
                "status": "cloned",
                "source_slice": arguments["slice_name"],
                "name": result.get("name", new_name) if isinstance(result, dict) else new_name,
                "state": result.get("state", "Draft") if isinstance(result, dict) else "Draft",
                "nodes": len(result.get("nodes", [])) if isinstance(result, dict) else None,
                "networks": len(result.get("networks", [])) if isinstance(result, dict) else None,
            }, default=str)

        elif name == "save_as_template":
            from app.routes.templates import save_template, SaveTemplateRequest
            req = SaveTemplateRequest(
                slice_name=arguments["slice_name"],
                template_name=arguments["template_name"],
                description=arguments.get("description", ""),
            )
            result = await asyncio.to_thread(_run_sync, save_template, req)
            return json.dumps({"status": "saved", "template_name": arguments["template_name"]}, default=str)

        elif name == "remove_node":
            from app.routes.slices import remove_node
            result = await asyncio.to_thread(_run_sync, remove_node, arguments["slice_name"], arguments["node_name"])
            return json.dumps({"status": "removed", "node": arguments["node_name"]}, default=str)

        elif name == "remove_network":
            from app.routes.slices import remove_network
            result = await asyncio.to_thread(_run_sync, remove_network, arguments["slice_name"], arguments["network_name"])
            return json.dumps({"status": "removed", "network": arguments["network_name"]}, default=str)

        # --- File Operations (container filesystem) ---
        elif name == "write_file":
            from app.user_context import get_user_storage
            base = get_user_storage()
            rel = arguments["path"].lstrip("/")
            full = os.path.realpath(os.path.join(base, rel))
            if not full.startswith(os.path.realpath(base) + os.sep):
                return json.dumps({"error": "Path outside user storage"})
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(arguments["content"])
            return json.dumps({"status": "written", "path": rel, "size": len(arguments["content"])})

        elif name == "read_file":
            from app.user_context import get_user_storage
            base = get_user_storage()
            rel = arguments["path"].lstrip("/")
            full = os.path.realpath(os.path.join(base, rel))
            if not full.startswith(os.path.realpath(base) + os.sep):
                return json.dumps({"error": "Path outside user storage"})
            if not os.path.isfile(full):
                return json.dumps({"error": f"File not found: {rel}"})
            with open(full, "r") as f:
                content = f.read(100_000)  # limit to 100KB
            return json.dumps({"path": rel, "content": content})

        elif name == "list_directory":
            from app.user_context import get_user_storage
            base = get_user_storage()
            rel = (arguments.get("path") or "").lstrip("/")
            full = os.path.realpath(os.path.join(base, rel)) if rel else os.path.realpath(base)
            if not (full.startswith(os.path.realpath(base) + os.sep) or full == os.path.realpath(base)):
                return json.dumps({"error": "Path outside user storage"})
            if not os.path.isdir(full):
                return json.dumps({"error": f"Directory not found: {rel}"})
            entries = []
            for item in sorted(os.listdir(full)):
                if item.startswith("."):
                    continue
                item_path = os.path.join(full, item)
                entries.append({
                    "name": item,
                    "type": "dir" if os.path.isdir(item_path) else "file",
                    "size": os.path.getsize(item_path) if os.path.isfile(item_path) else 0,
                })
            return json.dumps({"path": rel or "/", "entries": entries})

        elif name == "create_directory":
            from app.user_context import get_user_storage
            base = get_user_storage()
            rel = arguments["path"].lstrip("/")
            full = os.path.realpath(os.path.join(base, rel))
            if not full.startswith(os.path.realpath(base) + os.sep):
                return json.dumps({"error": "Path outside user storage"})
            os.makedirs(full, exist_ok=True)
            return json.dumps({"status": "created", "path": rel})

        elif name == "delete_path":
            import shutil
            from app.user_context import get_user_storage
            base = get_user_storage()
            rel = arguments["path"].lstrip("/")
            full = os.path.realpath(os.path.join(base, rel))
            if not full.startswith(os.path.realpath(base) + os.sep):
                return json.dumps({"error": "Path outside user storage"})
            if not os.path.exists(full):
                return json.dumps({"error": f"Not found: {rel}"})
            if os.path.isdir(full):
                shutil.rmtree(full)
            else:
                os.remove(full)
            return json.dumps({"status": "deleted", "path": rel})

        elif name == "run_python_script":
            from app.user_context import get_user_storage
            base = os.path.realpath(get_user_storage())

            rel = arguments["path"].lstrip("/")
            script_path = os.path.realpath(os.path.join(base, rel))
            if not script_path.startswith(base + os.sep):
                return json.dumps({"error": "Script path outside user storage"})
            if not os.path.isfile(script_path):
                return json.dumps({"error": f"Script not found: {rel}"})
            if not script_path.endswith(".py"):
                return json.dumps({"error": "run_python_script only executes .py files"})

            cwd_arg = (arguments.get("cwd") or "").lstrip("/")
            cwd = os.path.realpath(os.path.join(base, cwd_arg)) if cwd_arg else os.path.dirname(script_path)
            if not (cwd.startswith(base + os.sep) or cwd == base):
                return json.dumps({"error": "Working directory outside user storage"})
            if not os.path.isdir(cwd):
                return json.dumps({"error": f"Working directory not found: {cwd_arg}"})

            raw_args = arguments.get("args") or []
            if isinstance(raw_args, str):
                raw_args = [raw_args]
            script_args = [str(arg) for arg in raw_args][:20]
            try:
                timeout = int(arguments.get("timeout", 120) or 120)
            except (TypeError, ValueError):
                timeout = 120
            timeout = max(1, min(timeout, 1800))

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                script_path,
                *script_args,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            timed_out = False
            try:
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                timed_out = True
                proc.kill()
                stdout_b, stderr_b = await proc.communicate()

            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")
            stdout_truncated = len(stdout) > 32000
            stderr_truncated = len(stderr) > 8000
            result = {
                "status": "timeout" if timed_out else ("ok" if proc.returncode == 0 else "error"),
                "path": rel,
                "cwd": os.path.relpath(cwd, base),
                "args": script_args,
                "exit_code": proc.returncode,
                "timeout": timeout,
                "stdout": stdout[:32000],
                "stderr": stderr[:8000],
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
            }
            if timed_out:
                result["error"] = f"Python script timed out after {timeout}s"
            return json.dumps(result, default=str)

        elif name == "run_jupyter_notebook":
            from app.user_context import get_user_storage
            base = os.path.realpath(get_user_storage())

            rel = arguments["path"].lstrip("/")
            notebook_path = os.path.realpath(os.path.join(base, rel))
            if not notebook_path.startswith(base + os.sep):
                return json.dumps({"error": "Notebook path outside user storage"})
            if not os.path.isfile(notebook_path):
                return json.dumps({"error": f"Notebook not found: {rel}"})
            if not notebook_path.endswith(".ipynb"):
                return json.dumps({"error": "run_jupyter_notebook only executes .ipynb files"})

            output_rel = (arguments.get("output_path") or rel).lstrip("/")
            output_path = os.path.realpath(os.path.join(base, output_rel))
            if not output_path.startswith(base + os.sep):
                return json.dumps({"error": "Output path outside user storage"})
            if not output_path.endswith(".ipynb"):
                return json.dumps({"error": "output_path must end with .ipynb"})
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            cwd_arg = (arguments.get("cwd") or "").lstrip("/")
            cwd = os.path.realpath(os.path.join(base, cwd_arg)) if cwd_arg else os.path.dirname(notebook_path)
            if not (cwd.startswith(base + os.sep) or cwd == base):
                return json.dumps({"error": "Working directory outside user storage"})
            if not os.path.isdir(cwd):
                return json.dumps({"error": f"Working directory not found: {cwd_arg}"})

            try:
                timeout = int(arguments.get("timeout", 120) or 120)
            except (TypeError, ValueError):
                timeout = 120
            timeout = max(1, min(timeout, 1800))
            kernel_name = str(arguments.get("kernel_name") or "python3")

            def _execute_notebook() -> dict[str, Any]:
                try:
                    import nbformat
                    from nbclient import NotebookClient
                except Exception as exc:
                    return {
                        "error": "Notebook execution dependencies are not installed",
                        "detail": str(exc),
                    }

                with open(notebook_path) as f:
                    nb = nbformat.read(f, as_version=4)

                error = ""
                try:
                    client = NotebookClient(
                        nb,
                        timeout=timeout,
                        kernel_name=kernel_name,
                        resources={"metadata": {"path": cwd}},
                    )
                    client.execute()
                except Exception as exc:
                    error = str(exc)

                with open(output_path, "w") as f:
                    nbformat.write(nb, f)

                code_cells = 0
                output_count = 0
                error_count = 0
                previews: list[dict[str, Any]] = []
                for index, cell in enumerate(nb.get("cells", [])):
                    if cell.get("cell_type") != "code":
                        continue
                    code_cells += 1
                    cell_outputs = cell.get("outputs") or []
                    output_count += len(cell_outputs)
                    cell_preview: list[str] = []
                    for output in cell_outputs:
                        output_type = output.get("output_type", "")
                        if output_type == "error":
                            error_count += 1
                            cell_preview.append(
                                f"{output.get('ename', 'Error')}: {output.get('evalue', '')}"
                            )
                        elif output_type == "stream":
                            cell_preview.append(str(output.get("text", "")))
                        elif output_type in {"execute_result", "display_data"}:
                            data = output.get("data") or {}
                            cell_preview.append(str(data.get("text/plain", "")))
                    if cell_preview and len(previews) < 12:
                        text = "\n".join(part for part in cell_preview if part)
                        previews.append({
                            "cell_index": index,
                            "text": text[:2000],
                            "truncated": len(text) > 2000,
                        })

                return {
                    "status": "error" if error or error_count else "ok",
                    "path": rel,
                    "output_path": os.path.relpath(output_path, base),
                    "cwd": os.path.relpath(cwd, base),
                    "kernel_name": kernel_name,
                    "timeout": timeout,
                    "code_cells": code_cells,
                    "output_count": output_count,
                    "error_count": error_count,
                    "outputs": previews,
                    "error": error or None,
                }

            result = await asyncio.to_thread(_execute_notebook)
            return json.dumps(result, default=str)

        # --- Artifact Management ---
        elif name == "list_artifacts":
            from app.routes.artifacts import list_local_artifacts
            result = await asyncio.to_thread(_run_sync, list_local_artifacts)
            artifacts = result.get("artifacts", [])
            return json.dumps([{
                "name": a.get("name"), "category": a.get("category"),
                "description": a.get("description", ""),
                "published": a.get("published", False),
            } for a in artifacts], default=str)

        elif name == "validate_artifact":
            from app.routes.artifacts import validate_artifact as validate_artifact_fn, ValidateArtifactRequest
            req = ValidateArtifactRequest(
                dir_name=arguments.get("dir_name"),
                weave_json=arguments.get("weave_json"),
                vm_template_json=arguments.get("vm_template_json"),
                recipe_json=arguments.get("recipe_json"),
                scripts=arguments.get("scripts") or {},
                files=arguments.get("files") or {},
            )
            result = await asyncio.to_thread(_run_sync, validate_artifact_fn, req)
            return json.dumps(result, default=str)

        elif name == "publish_artifact":
            from app.routes.artifacts import publish_artifact as publish_fn, PublishRequest
            req = PublishRequest(
                dir_name=arguments["dir_name"],
                title=arguments["title"],
                category=arguments.get("category", ""),
                description=arguments.get("description", ""),
                tags=arguments.get("tags", []),
                visibility=arguments.get("visibility", "author"),
                project_uuid=arguments.get("project_uuid", ""),
            )
            result = await publish_fn(req)
            return json.dumps(result, default=str)

        # --- Slice Operations ---
        elif name == "refresh_slice":
            from app.routes.slices import refresh_slice as refresh_fn
            result = await refresh_fn(arguments["slice_name"])
            # Return summary instead of full slice data
            return json.dumps({
                "status": "refreshed", "name": result.get("name"),
                "state": result.get("state"),
                "nodes": len(result.get("nodes", [])),
            }, default=str)

        elif name == "validate_slice":
            from app.routes.slices import validate_slice as validate_fn
            result = await asyncio.to_thread(_run_sync, validate_fn, arguments["slice_name"])
            return json.dumps(result, default=str)

        elif name == "update_node":
            from app.routes.slices import update_node as update_node_fn, UpdateNodeRequest
            req = UpdateNodeRequest(
                site=arguments.get("site"),
                cores=arguments.get("cores"),
                ram=arguments.get("ram"),
                disk=arguments.get("disk"),
                image=arguments.get("image"),
            )
            result = await asyncio.to_thread(
                _run_sync, update_node_fn, arguments["slice_name"], arguments["node_name"], req
            )
            return json.dumps({"status": "updated", "node": arguments["node_name"]}, default=str)

        # --- VM Operations (SSH) ---
        elif name == "ssh_execute":
            from app.routes.files import execute_on_vm, VmExecBody
            body = VmExecBody(
                command=arguments["command"],
                timeout=arguments.get("timeout"),
            )
            result = await execute_on_vm(arguments["slice_name"], arguments["node_name"], body)
            raw_stdout = result.get("stdout", "") or ""
            raw_stderr = result.get("stderr", "") or ""
            stdout = raw_stdout[:32000]
            stderr = raw_stderr[:8000]
            return json.dumps({
                "slice_name": arguments["slice_name"],
                "node_name": arguments["node_name"],
                "command": arguments["command"],
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": len(raw_stdout) > len(stdout),
                "stderr_truncated": len(raw_stderr) > len(stderr),
            }, default=str)

        elif name == "reboot_and_wait":
            from app.routes.files import reboot_and_wait as reboot_fn, VmRebootBody
            body = VmRebootBody(timeout=int(arguments.get("timeout", 300) or 300))
            result = await reboot_fn(arguments["slice_name"], arguments["node_name"], body)
            return json.dumps(result, default=str)

        elif name == "write_vm_file":
            from app.routes.files import write_vm_file_content, VmWriteFileRequest
            body = VmWriteFileRequest(path=arguments["path"], content=arguments["content"])
            result = await write_vm_file_content(arguments["slice_name"], arguments["node_name"], body)
            return json.dumps({"status": "written", "path": arguments["path"]}, default=str)

        elif name == "read_vm_file":
            from app.routes.files import read_vm_file_content, VmReadFileRequest
            body = VmReadFileRequest(path=arguments["path"])
            result = await read_vm_file_content(arguments["slice_name"], arguments["node_name"], body)
            content = result.get("content", "")[:50000]
            return json.dumps({"path": arguments["path"], "content": content}, default=str)

        elif name == "download_file_bulk":
            from app.routes.files import _get_node
            from app.slice_registry import resolve_slice_name
            from app.user_context import get_user_storage

            slice_name = resolve_slice_name(arguments["slice_name"])
            remote_path = arguments["remote_path"]
            base = os.path.realpath(get_user_storage())
            dest_rel = (arguments.get("dest_dir") or "downloads").lstrip("/")
            dest_dir = os.path.realpath(os.path.join(base, dest_rel))
            if not (dest_dir.startswith(base + os.sep) or dest_dir == base):
                return json.dumps({"error": "Destination outside user storage"})
            os.makedirs(dest_dir, exist_ok=True)

            filename = arguments.get("filename") or os.path.basename(remote_path.rstrip("/"))
            filename = os.path.basename(str(filename))
            if not filename:
                return json.dumps({"error": "Could not determine local filename"})
            local_path = os.path.realpath(os.path.join(dest_dir, filename))
            if not local_path.startswith(dest_dir + os.sep):
                return json.dumps({"error": "Local filename outside destination"})

            def _download() -> dict[str, Any]:
                node_obj = _get_node(slice_name, arguments["node_name"])
                node_obj.download_file(local_path, remote_path)
                size = os.path.getsize(local_path)
                try:
                    preview_bytes = int(arguments.get("preview_bytes", 4096) or 4096)
                except (TypeError, ValueError):
                    preview_bytes = 4096
                preview_bytes = max(0, min(preview_bytes, 32000))
                preview = b""
                if preview_bytes:
                    with open(local_path, "rb") as f:
                        preview = f.read(preview_bytes)
                rel_path = os.path.relpath(local_path, base)
                return {
                    "status": "downloaded",
                    "slice_name": slice_name,
                    "node_name": arguments["node_name"],
                    "remote_path": remote_path,
                    "local_path": rel_path,
                    "size": size,
                    "preview": preview.decode("utf-8", errors="replace"),
                    "preview_bytes": len(preview),
                    "preview_truncated": size > len(preview),
                }

            result = await asyncio.to_thread(_download)
            return json.dumps(result, default=str)

        elif name == "create_tunnel":
            from app.routes.tunnels import create_tunnel as create_tunnel_fn, TunnelCreateRequest
            req = TunnelCreateRequest(
                slice_name=arguments["slice_name"],
                node_name=arguments["node_name"],
                port=int(arguments["port"]),
                protocol=arguments.get("protocol", "http"),
            )
            result = await asyncio.to_thread(_run_sync, create_tunnel_fn, req)
            return json.dumps(result, default=str)

        # --- Recipe Operations ---
        elif name == "list_recipes":
            from app.routes.recipes import list_recipes as list_recipes_fn
            result = await asyncio.to_thread(_run_sync, list_recipes_fn)
            return json.dumps([{
                "name": r.get("name"), "description": r.get("description", ""),
                "dir_name": r.get("dir_name"),
            } for r in result], default=str)

        elif name == "execute_recipe":
            from app.routes.recipes import execute_recipe as execute_recipe_fn
            response = await execute_recipe_fn(
                arguments["recipe_name"],
                arguments["slice_name"],
                arguments["node_name"],
            )
            if isinstance(response, StreamingResponse):
                result = await _collect_sse_json_events(response)
            else:
                result = response
            if isinstance(result, dict):
                result = {
                    "recipe_name": arguments["recipe_name"],
                    "slice_name": arguments["slice_name"],
                    "node_name": arguments["node_name"],
                    **result,
                }
            return json.dumps(result, default=str)

        # --- JupyterLab ---
        elif name == "manage_jupyter":
            action = arguments["action"]
            if action == "start":
                from app.routes.jupyter import start_jupyter
                result = await start_jupyter()
                return json.dumps(result, default=str)
            elif action == "stop":
                from app.routes.jupyter import stop_jupyter
                result = await stop_jupyter()
                return json.dumps(result, default=str)
            elif action == "status":
                from app.routes.jupyter import jupyter_status
                result = await jupyter_status()
                return json.dumps(result, default=str)
            else:
                return json.dumps({"error": f"Unknown jupyter action: {action}"})

        # --- Background Runs ---
        elif name == "start_background_run":
            from app.routes.templates import start_background_run, StartRunRequest, _sanitize_name, _templates_dir, _validate_path
            result = start_background_run(
                arguments["weave_dir_name"],
                arguments["script"],
                StartRunRequest(slice_name=arguments.get("slice_name", "")),
                request=request,
            )
            return json.dumps(result, default=str)

        elif name == "list_background_runs":
            from app.routes.templates import list_background_runs
            result = list_background_runs()
            return json.dumps(result, default=str)

        elif name == "get_background_run_output":
            from app.routes.templates import get_background_run_output
            result = get_background_run_output(
                arguments["run_id"],
                arguments.get("offset", 0),
            )
            if isinstance(result, dict):
                result = {"run_id": arguments["run_id"], **result}
                if result.get("status") == "running":
                    # A weave provisioning a slice is silent for minutes, so
                    # identical output is the CORRECT answer here, not a stall.
                    # Say so, and tell the model to report rather than re-poll —
                    # it has no way to wait, so polling again just burns the
                    # repeated-tool budget and ends the turn looking like failure.
                    result["hint"] = (
                        "Run is still in progress. Do not call this tool again in "
                        "this turn — summarize the output so far and tell the user "
                        "to check back in a few minutes."
                    )
            return json.dumps(result, default=str)

        elif name == "stop_background_run":
            from app.routes.templates import stop_background_run
            result = stop_background_run(arguments["run_id"])
            return json.dumps(result, default=str)

        elif name == "create_weave":
            return await _create_weave_tool(arguments)

        # --- Web Search & Fetch ---
        elif name == "web_search":
            result = await _execute_web_search(
                arguments["query"],
                arguments.get("max_results", 5),
            )
            return result

        elif name == "fetch_webpage":
            result = await _execute_fetch_webpage(
                arguments["url"],
                arguments.get("max_length", 4000),
            )
            return result

        # --- Chameleon Cloud tools ---

        elif name == "list_chameleon_leases":
            from app.routes.chameleon import list_leases
            site = arguments.get("site")
            result = await list_leases(site)
            return json.dumps([{
                "name": l.get("name"), "status": l.get("status"),
                "site": l.get("_site"), "id": l.get("id"),
                "start": l.get("start_date", "")[:16],
                "end": l.get("end_date", "")[:16],
            } for l in result], default=str)

        elif name == "list_chameleon_instances":
            from app.routes.chameleon import list_instances
            site = arguments.get("site")
            result = await list_instances(site)
            return json.dumps(result, default=str)

        elif name == "list_chameleon_sites":
            from app.routes.chameleon import list_chameleon_sites
            result = await list_chameleon_sites()
            return json.dumps(result, default=str)

        elif name == "chameleon_site_images":
            from app.routes.chameleon import site_images
            result = await site_images(arguments["site"])
            return json.dumps(result[:20], default=str)  # Limit to 20

        elif name == "create_chameleon_lease":
            from app.routes.chameleon import create_lease
            from starlette.requests import Request as _Req
            from starlette.datastructures import Headers
            # Build a mock request with the arguments as JSON body
            scope = {"type": "http", "method": "POST", "headers": []}
            mock_req = _Req(scope)
            mock_req._body = json.dumps(arguments).encode()
            result = await create_lease(mock_req)
            return json.dumps(result, default=str)

        elif name == "delete_chameleon_lease":
            from app.routes.chameleon import delete_lease
            result = await delete_lease(arguments["lease_id"], arguments.get("site", "CHI@TACC"))
            return json.dumps(result, default=str)

        elif name == "create_chameleon_instance":
            from app.routes.chameleon import create_instance
            from starlette.requests import Request as _Req
            scope = {"type": "http", "method": "POST", "headers": []}
            mock_req = _Req(scope)
            mock_req._body = json.dumps(arguments).encode()
            result = await create_instance(mock_req)
            return json.dumps(result, default=str)

        elif name == "delete_chameleon_instance":
            from app.routes.chameleon import delete_instance
            result = await delete_instance(arguments["instance_id"], arguments.get("site", "CHI@TACC"))
            return json.dumps(result, default=str)

        elif name == "list_chameleon_slices":
            from app.routes.chameleon import list_chameleon_slices
            result = await list_chameleon_slices()
            return json.dumps(result, default=str)

        elif name == "deploy_chameleon_slice":
            from app.routes.chameleon import deploy_draft
            body = {"duration_hours": arguments.get("hours", 4)}
            result = await deploy_draft(arguments["draft_id"], body)
            return json.dumps(result, default=str)

        # --- SPHERE / MergeTB tools ---
        # NOTE: the sphere route functions use Body()/Query() defaults, which are
        # FieldInfo sentinels when called directly — every parameter must be
        # passed explicitly.

        elif name == "sphere_status":
            from app.routes.sphere import sphere_status
            result = await sphere_status()
            return json.dumps(result, default=str)

        elif name == "list_sphere_experiments":
            from app.routes.sphere import sphere_list_experiments
            result = await sphere_list_experiments(project=arguments.get("project"))
            return json.dumps(result, default=str)

        elif name == "create_sphere_experiment":
            from app.routes.sphere import sphere_create_experiment
            result = await sphere_create_experiment(
                experiment=arguments["experiment"],
                description=arguments.get("description", ""),
                project=arguments.get("project"),
            )
            return json.dumps(result, default=str)

        elif name == "push_sphere_model":
            from app.routes.sphere import sphere_push_model
            result = await sphere_push_model(
                model=arguments["model"],
                experiment=arguments["experiment"],
                tag=arguments.get("tag"),
                branch=None,
                project=arguments.get("project"),
            )
            return json.dumps(result, default=str)

        elif name == "list_sphere_realizations":
            from app.routes.sphere import sphere_list_realizations
            result = await sphere_list_realizations(
                project=arguments.get("project"), all=False, summary=False, state=True,
            )
            # Full realizations are verbose (per-socket topology) — compact for chat.
            compact = [{
                "realization": r.get("id"), "experiment": r.get("eid"),
                "project": r.get("pid"), "state": r.get("state"),
                "error": r.get("error"), "expires": r.get("expires"),
                "nodes": len(r.get("nodes") or {}), "links": len(r.get("links") or {}),
            } for r in result] if isinstance(result, list) else result
            return json.dumps(compact, default=str)

        elif name == "sphere_realize":
            from app.routes.sphere import sphere_realize
            result = await sphere_realize(
                experiment=arguments["experiment"],
                realization=arguments["realization"],
                tag=arguments.get("tag"),
                branch=None,
                revision=None,
                duration=arguments.get("duration"),
                project=arguments.get("project"),
            )
            return json.dumps(result, default=str)

        elif name == "sphere_relinquish":
            from app.routes.sphere import sphere_relinquish
            result = await sphere_relinquish(
                experiment=arguments["experiment"],
                realization=arguments["realization"],
                project=arguments.get("project"),
            )
            return json.dumps(result, default=str)

        elif name == "sphere_materialize":
            from app.routes.sphere import sphere_materialize
            result = await sphere_materialize(
                experiment=arguments["experiment"],
                realization=arguments["realization"],
                project=arguments.get("project"),
            )
            return json.dumps(result, default=str)

        elif name == "get_sphere_materialization":
            from app.routes.sphere import sphere_get_materialization
            result = await sphere_get_materialization(
                experiment=arguments["experiment"],
                realization=arguments["realization"],
                project=arguments.get("project"),
                status=True,
            )
            # Drop the ~43-task status tree; taskSummary + summary carry the signal.
            if isinstance(result, dict):
                result = {k: v for k, v in result.items() if k != "taskStatus"}
            return json.dumps(result, default=str)

        elif name == "sphere_dematerialize":
            from app.routes.sphere import sphere_dematerialize
            result = await sphere_dematerialize(
                experiment=arguments["experiment"],
                realization=arguments["realization"],
                project=arguments.get("project"),
            )
            return json.dumps(result, default=str)

        elif name == "list_sphere_xdcs":
            from app.routes.sphere import sphere_list_xdcs
            result = await sphere_list_xdcs(project=arguments.get("project"), status=True)
            return json.dumps(result, default=str)

        elif name == "create_sphere_xdc":
            from app.routes.sphere import sphere_create_xdc
            # Pass every param explicitly — calling a FastAPI route fn directly does
            # not resolve Body(...) defaults, so unpassed args would leak FieldInfo.
            result = await sphere_create_xdc(
                xdc=arguments["xdc"],
                type=arguments.get("type", "shared"),
                project=arguments.get("project"),
            )
            return json.dumps(result, default=str)

        elif name == "attach_sphere_xdc":
            from app.routes.sphere import sphere_attach_xdc
            result = await sphere_attach_xdc(
                arguments["xdc"],
                experiment=arguments["experiment"],
                realization=arguments["realization"],
                project=arguments.get("project"),
            )
            return json.dumps(result, default=str)

        elif name == "detach_sphere_xdc":
            from app.routes.sphere import sphere_detach_xdc
            result = await sphere_detach_xdc(
                arguments["xdc"],
                experiment=arguments["experiment"],
                realization=arguments["realization"],
                project=arguments.get("project"),
            )
            return json.dumps(result, default=str)

        elif name == "delete_sphere_xdc":
            from app.routes.sphere import sphere_delete_xdc
            result = await sphere_delete_xdc(
                arguments["xdc"],
                project=arguments.get("project"),
            )
            return json.dumps(result, default=str)

        elif name == "package_sphere_experiment":
            from app.routes.sphere import sphere_package_experiment
            # Pass every param explicitly — calling a FastAPI route fn directly does
            # not resolve Body(...) defaults, so unpassed args would leak FieldInfo.
            result = await sphere_package_experiment(
                experiment=arguments["experiment"],
                name=arguments["name"],
                description=arguments.get("description", ""),
                description_short="",
                description_long="",
                dir_name=arguments.get("dir_name"),
                realization=arguments.get("realization", "r0"),
                scripts=arguments.get("scripts") or [],
                include_notebook=arguments.get("include_notebook", True),
                notebook=arguments.get("notebook"),
                tags=arguments.get("tags"),
                project=arguments.get("project"),
            )
            return json.dumps(result, default=str)

        elif name == "list_composite_slices":
            from app.routes.composite import list_composite_slices
            result = await list_composite_slices()
            return json.dumps(result, default=str)

        elif name == "get_composite_slice":
            from app.routes.composite import get_composite_slice
            result = await get_composite_slice(arguments["slice_id"])
            return json.dumps(result, default=str)

        elif name == "create_composite_slice":
            from app.routes.composite import create_composite_slice
            body = {"name": arguments["name"]}
            result = await create_composite_slice(body)
            return json.dumps(result, default=str)

        elif name == "search_examples":
            # LLMs sometimes send "name" instead of "query"
            q = arguments.get("query") or arguments.get("name") or arguments.get("search") or ""
            return await _search_examples(q)

        elif name == "list_metric_topics":
            return await _call_metrics_mcp(
                "list_topics", {}, compact=_compact_metrics_topics)

        elif name == "list_metric_param_options":
            return await _call_metrics_mcp(
                "list_param_options",
                {
                    "topic": _metrics_topic_tool(arguments.get("topic") or ""),
                    "param": arguments.get("param") or "",
                },
            )

        elif name == "query_infrastructure_metrics":
            topic = arguments.get("topic") or ""
            call_args: dict[str, Any] = {}
            extra = arguments.get("args")
            if isinstance(extra, dict):
                call_args.update(extra)
            # Models occasionally hoist the topic params to the top level.
            for key in ("node", "src_rack", "dst_rack", "device", "interface",
                        "start", "end", "step", "mode", "params"):
                if key in arguments and key not in call_args:
                    call_args[key] = arguments[key]
            variant = arguments.get("variant")
            if variant:
                call_args["variant"] = variant
            return await _call_metrics_mcp(topic, call_args)

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except HTTPException as e:
        detail = str(e.detail)
        payload: dict[str, Any] = {"error": detail, "status_code": e.status_code}
        if _is_token_expired_error(e.status_code, detail):
            payload["error_code"] = "TOKEN_EXPIRED"
        logger.warning("Tool %s failed: %s", name, detail)
        return json.dumps(payload)
    except Exception as e:
        logger.warning("Tool %s failed: %s", name, e)
        payload = {"error": str(e)}
        if _is_token_expired_error(None, str(e)):
            payload["error_code"] = "TOKEN_EXPIRED"
        return json.dumps(payload)


# ---------------------------------------------------------------------------
# Web search & fetch helpers
# ---------------------------------------------------------------------------

async def _execute_web_search(query: str, max_results: int = 5) -> str:
    """Search the web using DuckDuckGo and return results as JSON."""
    max_results = min(max(1, max_results), 10)
    try:
        from duckduckgo_search import DDGS

        def _search():
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
                for r in results
            ]

        results = await asyncio.to_thread(_search)
        return json.dumps({"query": query, "results": results}, default=str)
    except Exception as e:
        logger.warning("Web search failed: %s", e)
        return json.dumps({"error": f"Search failed: {e}"})


_FETCH_BLOCKED_HOSTS = {"localhost", "metadata", "metadata.google.internal"}
_FETCH_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".cluster.local")
_FETCH_MAX_REDIRECTS = 3


def _fetch_url_problem(url: str) -> str | None:
    """Return why *url* must not be fetched for the model, or None if it may.

    The URL comes from the model, which may be following injected text, so
    the fetch must not reach the local backend (auth is off on loopback in
    hosted mode and it serves ``fabric_config/id_token.json``), the hub,
    other pods, or cloud metadata. Only public http(s) hosts are allowed and
    every address the host resolves to is checked, not just the first.
    Known limit: a host that changes its answer between this check and the
    connect (DNS rebinding) is not caught.
    """
    import ipaddress
    import socket
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
    except ValueError:
        return "malformed URL"
    if parts.scheme not in ("http", "https"):
        return "only http(s) URLs can be fetched"
    if parts.username or parts.password:
        return "credentials in the URL are not allowed"
    host = (parts.hostname or "").strip(".").lower()
    if not host:
        return "URL has no host"
    if host in _FETCH_BLOCKED_HOSTS or host.endswith(_FETCH_BLOCKED_SUFFIXES):
        return f"host '{host}' is not public"
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return "invalid port"
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return f"could not resolve '{host}'"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return f"'{host}' resolved to an unparsable address"
        if not ip.is_global or ip.is_multicast:
            return f"'{host}' resolves to a non-public address"
    return None


async def _fetch_public_url(url: str) -> "httpx.Response":
    """GET *url* with the SSRF guard applied to it and to every redirect hop."""
    from app.http_pool import web_client

    current = url
    for _ in range(_FETCH_MAX_REDIRECTS + 1):
        problem = await asyncio.to_thread(_fetch_url_problem, current)
        if problem:
            raise ValueError(f"refusing to fetch {current}: {problem}")
        resp = await web_client.get(current)
        if resp.is_redirect and resp.headers.get("location"):
            current = str(resp.url.join(resp.headers["location"]))
            continue
        return resp
    raise ValueError(f"too many redirects fetching {url}")


async def _execute_fetch_webpage(url: str, max_length: int = 4000) -> str:
    """Fetch a webpage and return its text content (HTML stripped)."""
    max_length = min(max(500, max_length), 8000)
    try:
        resp = await _fetch_public_url(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            text = _extract_text_from_html(resp.text)
        else:
            text = resp.text
        if len(text) > max_length:
            text = text[:max_length] + "\n\n[... truncated]"
        return json.dumps({"url": url, "content": text}, default=str)
    except Exception as e:
        logger.warning("Fetch webpage failed: %s", e)
        return json.dumps({"error": f"Fetch failed: {e}"})


def _extract_text_from_html(html: str) -> str:
    """Extract readable text from HTML, stripping tags, scripts, and styles."""
    import re
    # Remove script and style blocks
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Decode common HTML entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Re-add paragraph breaks at likely boundaries
    text = re.sub(r' {2,}', '\n\n', text)
    return text


# ---------------------------------------------------------------------------
# Streaming agentic chat
# ---------------------------------------------------------------------------

# Track cancelled streaming requests
_cancelled_requests: set[str] = set()


@router.get("/api/ai/chat/agents")
async def list_agents_endpoint():
    agents = _load_agents()
    return [{"id": aid, "name": info["name"], "description": info["description"]} for aid, info in agents.items()]


@router.post("/api/ai/chat/stream")
async def chat_stream(request: Request):
    """Agentic streaming chat with tool calling.

    The LLM can call tools (query sites, create slices, etc). When it does,
    we execute the tools, send results back, and let the LLM continue.
    All streamed as SSE events to the frontend.
    """
    body = await request.json()
    raw_messages = body.get("messages")
    if not isinstance(raw_messages, list):
        raise HTTPException(
            status_code=422,
            detail="messages must be a list containing at least one non-empty user message",
        )
    has_user_message = any(
        isinstance(msg, dict)
        and msg.get("role") == "user"
        and bool(str(msg.get("content") or "").strip())
        for msg in raw_messages
    )
    if not has_user_message:
        raise HTTPException(
            status_code=422,
            detail="messages must contain at least one non-empty user message",
        )
    messages = raw_messages
    conversation_id = ""
    try:
        from app.chat_sessions import load_chat_session, normalize_session_id

        conversation_id = normalize_session_id(
            body.get("conversation_id") or body.get("session_id") or ""
        )
        if conversation_id:
            stored_session = load_chat_session(conversation_id)
            stored_messages = stored_session.get("messages", []) if stored_session else []
            if isinstance(stored_messages, list) and stored_messages:
                messages = _merge_persisted_chat_messages(messages, stored_messages)
                logger.info(
                    "Loaded chat session %s with %d persisted messages; request has %d visible messages",
                    conversation_id,
                    len(stored_messages),
                    len(raw_messages),
                )
    except Exception as exc:
        logger.debug("Chat session load skipped: %s", exc)

    model = body.get("model") or ""
    if not model:
        from app.settings_manager import get_default_model
        model = get_default_model() or "qwen3-coder-30b"
    raw_agent_id = body.get("agent")
    agent_id = str(raw_agent_id).strip() if raw_agent_id else ""
    explicit_agent_id = agent_id or None
    explicit_agent_info: dict[str, Any] | None = None
    if explicit_agent_id:
        agents = _load_agents()
        explicit_agent_info = agents.get(explicit_agent_id)
        if explicit_agent_info is None:
            payload = json.dumps({"error": f'Agent "{explicit_agent_id}" not found'})
            return StreamingResponse(
                iter([f"data: {payload}\n\n".encode()]),
                media_type="text/event-stream",
            )
    explicit_agent_controls_context = bool(
        explicit_agent_id and explicit_agent_id != "fabric-query-reporter"
    )
    allow_automatic_context = not explicit_agent_controls_context
    slice_context = body.get("slice_context")
    request_id = body.get("request_id", "")
    requested_temperature = _optional_float(body, "temperature", minimum=0.0, maximum=2.0)
    requested_top_p = _optional_float(body, "top_p", minimum=0.0, maximum=1.0)
    requested_max_output = _optional_int(
        body,
        "max_output_tokens",
        minimum=1,
        maximum=32768,
    )
    requested_reasoning_effort = _normalize_reasoning_effort(body.get("reasoning_effort"))

    # Route to the correct provider based on model prefix
    # Formats: "nrp:model", "ProviderName:model", or bare "model" (FABRIC default)
    original_model_key = model  # preserve for model_type lookup
    use_nrp = False
    use_custom_provider = False
    custom_provider_name = ""
    if model.startswith("nrp:"):
        model = model[4:]  # strip prefix
        server_url = _nrp_server_url()
        api_key = _get_nrp_api_key()
        use_nrp = True
        if not api_key:
            raise _chat_config_exception(
                "NRP_API_KEY_NOT_CONFIGURED",
                "NRP API key not configured",
                provider="nrp",
            )
    elif ":" in model:
        # Custom provider — look up base_url and api_key from settings
        provider_name, _, model = model.partition(":")
        use_custom_provider = True
        custom_provider_name = provider_name
        from app.settings_manager import load_settings as _load_settings_route
        _cp_list = _load_settings_route().get("ai", {}).get("custom_providers", [])
        _cp_match = next((cp for cp in _cp_list if cp.get("name") == provider_name), None)
        if not _cp_match or not _cp_match.get("base_url"):
            raise _chat_config_exception(
                "CUSTOM_PROVIDER_NOT_CONFIGURED",
                f'Custom provider "{provider_name}" not configured',
                provider=f"custom:{provider_name}",
            )
        server_url = _cp_match["base_url"].rstrip("/")
        api_key = _cp_match.get("api_key", "")
        if not api_key:
            raise _chat_config_exception(
                "CUSTOM_PROVIDER_API_KEY_NOT_CONFIGURED",
                f'Custom provider "{provider_name}" API key not configured',
                provider=f"custom:{provider_name}",
            )
    else:
        server_url = _ai_server_url()
        api_key = _get_ai_api_key()
        if not api_key:
            raise _chat_config_exception(
                "AI_API_KEY_NOT_CONFIGURED",
                "AI API key not configured",
                provider="fabric",
            )

    # Determine whether this model uses the Responses API or Chat Completions.
    # Capability profiles can override this below when the P6 flag is enabled.
    model_api_type = _get_model_type(original_model_key)

    # Build system prompt with model-aware context management
    from app.chat_context import (
        get_model_profile, get_system_prompt, trim_conversation,
        filter_tool_schemas, estimate_tokens, estimate_conversation_tokens,
        estimate_tool_schema_tokens, system_prompt_budget, fit_system_parts,
    )
    from app.chat_intent import detect_intent, detect_multi_step, is_destructive, record_intent_result
    from app.chat_prompt import LOOMAI_MODE_PROMPT, LOOMAI_MODE_EXTENDED

    # Look up actual context_length from discovered models
    from app.settings_manager import load_settings
    _ctx_length = None
    _ctx_source = "default"
    try:
        _discovered = load_settings().get("ai", {}).get("discovered_models", {})
        _model_bare = model.split(":")[-1] if ":" in model else model  # strip provider prefix
        for _provider_models in _discovered.values():
            if isinstance(_provider_models, list):
                for _m in _provider_models:
                    if isinstance(_m, dict) and _m.get("id") == _model_bare:
                        _ctx_length = _m.get("context_length")
                        if _ctx_length:
                            _ctx_source = "discovered"
                        break
            if _ctx_length:
                break
        if not _ctx_length and use_custom_provider:
            _custom_models = _discovered.get("custom", {})
            if isinstance(_custom_models, dict):
                for _m in _custom_models.get(custom_provider_name, []) or []:
                    if isinstance(_m, dict) and _m.get("id") == _model_bare:
                        _ctx_length = _m.get("context_length")
                        if _ctx_length:
                            _ctx_source = "discovered-custom"
                        break
    except Exception:
        pass

    # Fallback to hardcoded defaults if discovery hasn't persisted yet
    # (first-turn bootstrap before the startup task writes discovered_models)
    if not _ctx_length:
        from app.routes.ai_terminal import _FABRIC_CONTEXT_DEFAULTS, _NRP_CONTEXT_DEFAULTS
        _model_bare = model.split(":")[-1] if ":" in model else model
        _ctx_length = _FABRIC_CONTEXT_DEFAULTS.get(_model_bare) or _NRP_CONTEXT_DEFAULTS.get(_model_bare)
        if _ctx_length:
            _ctx_source = "hardcoded-default"

    from app.settings_manager import get_model_capability_profile
    capability_profile_applied = get_model_capability_profile(original_model_key)
    if capability_profile_applied:
        cap_context = capability_profile_applied.get("context_window_tokens")
        if cap_context:
            _ctx_length = cap_context
            _ctx_source = "capability-profile"
        cap_endpoint_style = capability_profile_applied.get("endpoint_style")
        if cap_endpoint_style in {"chat", "responses", "non-chat"}:
            model_api_type = cap_endpoint_style
    if model_api_type == "non-chat":
        payload = json.dumps({
            "error": f'Model "{original_model_key}" is listed by its provider but does not support chat.',
        })
        return StreamingResponse(
            iter([f"data: {payload}\n\n".encode()]),
            media_type="text/event-stream",
        )

    profile = get_model_profile(model, context_length=_ctx_length)
    if capability_profile_applied:
        if capability_profile_applied.get("max_output_tokens"):
            profile["max_output"] = capability_profile_applied["max_output_tokens"]
        if "temperature" in capability_profile_applied:
            profile["temperature"] = capability_profile_applied["temperature"]
        if "top_p" in capability_profile_applied:
            profile["top_p"] = capability_profile_applied["top_p"]
        if capability_profile_applied.get("reasoning_effort"):
            profile["reasoning_effort"] = capability_profile_applied["reasoning_effort"]
        if capability_profile_applied.get("strip_temperature"):
            profile["strip_temperature"] = True
        if "supports_tools" in capability_profile_applied:
            profile["supports_tools"] = bool(capability_profile_applied["supports_tools"])
        if capability_profile_applied.get("context_truncation_policy"):
            profile["context_truncation_policy"] = capability_profile_applied["context_truncation_policy"]
        if capability_profile_applied.get("orchestration_tier"):
            profile["orchestration_tier"] = capability_profile_applied["orchestration_tier"]
        for _context_key in (
            "weak_model_context_management",
            "context_compaction_enabled",
            "context_compaction_trigger_tokens",
            "context_compaction_trigger_messages",
            "context_compaction_preserve_last_tool_outputs",
            "context_compaction_keep_last_messages",
        ):
            if _context_key in capability_profile_applied:
                profile[_context_key] = capability_profile_applied[_context_key]
    if requested_temperature is not None:
        profile["temperature"] = requested_temperature
    if requested_top_p is not None:
        profile["top_p"] = requested_top_p
    if requested_max_output is not None:
        profile["max_output"] = requested_max_output
    if requested_reasoning_effort is not None:
        profile["reasoning_effort"] = requested_reasoning_effort
    generation_config_requested = {
        "temperature": requested_temperature,
        "top_p": requested_top_p,
        "max_output_tokens": requested_max_output,
        "reasoning_effort": requested_reasoning_effort,
    }
    generation_config_defaults_applied: dict[str, Any] = {}
    generation_config_adjustments: list[dict[str, Any]] = []
    logger.info(
        "Chat model=%s tier=%s context=%d (source=%s) api=%s capability_profile=%s",
        model,
        profile["tier"],
        profile["context_window"],
        _ctx_source,
        model_api_type,
        bool(capability_profile_applied),
    )

    from app.settings_manager import (
        get_assistant_tool_loop_settings,
        get_assistant_turn_budget,
        get_final_answer_retry_scope,
        get_resource_query_generation_defaults,
        is_final_answer_retry_enabled,
        is_compact_fabric_resource_tools_enabled,
        is_resource_query_generation_defaults_enabled,
        is_strict_fabric_query_contract_enabled,
        is_weak_model_context_management_enabled,
    )
    strict_fabric_query_contract_enabled = is_strict_fabric_query_contract_enabled()
    if explicit_agent_controls_context:
        strict_fabric_query_contract_enabled = False
    final_answer_retry_enabled = is_final_answer_retry_enabled()
    final_answer_retry_scope = get_final_answer_retry_scope()
    compact_resource_tools_enabled = is_compact_fabric_resource_tools_enabled()
    resource_query_generation_defaults_enabled = is_resource_query_generation_defaults_enabled()
    tool_loop_settings = get_assistant_tool_loop_settings()
    no_progress_limit = int(tool_loop_settings.get("no_progress_limit") or 3)
    turn_budget = get_assistant_turn_budget(original_model_key)
    weak_context_management_enabled = (
        is_weak_model_context_management_enabled()
        and _weak_model_context_management_applies(
            original_model_key,
            profile,
            capability_profile_applied,
        )
    )
    if weak_context_management_enabled:
        profile.setdefault("context_compaction_enabled", True)
        profile.setdefault("context_compaction_trigger_tokens", 16000)
        profile.setdefault("context_compaction_trigger_messages", 18)
        profile.setdefault("context_compaction_preserve_last_tool_outputs", 4)
        profile.setdefault("context_compaction_keep_last_messages", 12)
    else:
        profile["context_compaction_enabled"] = False

    # --- LoomAI-side intent detection (pre-processing) ---
    # Extract the user's last message for intent matching
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content") or ""
            break

    intent_tool, intent_args, intent_confidence = detect_intent(user_message)
    template = detect_multi_step(user_message)

    if (
        resource_query_generation_defaults_enabled
        and _is_fabric_resource_generation_query(user_message, intent_tool)
    ):
        configured_defaults = get_resource_query_generation_defaults(original_model_key)
        if requested_temperature is None and "temperature" in configured_defaults:
            value = _optional_float(
                {"temperature": configured_defaults["temperature"]},
                "temperature",
                minimum=0.0,
                maximum=2.0,
            )
            if value is not None:
                profile["temperature"] = value
                generation_config_defaults_applied["temperature"] = value
        if requested_top_p is None and "top_p" in configured_defaults:
            value = _optional_float(
                {"top_p": configured_defaults["top_p"]},
                "top_p",
                minimum=0.0,
                maximum=1.0,
            )
            if value is not None:
                profile["top_p"] = value
                generation_config_defaults_applied["top_p"] = value
        if requested_max_output is None and "max_output_tokens" in configured_defaults:
            value = _optional_int(
                {"max_output_tokens": configured_defaults["max_output_tokens"]},
                "max_output_tokens",
                minimum=1,
                maximum=32768,
            )
            if value is not None:
                profile["max_output"] = value
                generation_config_defaults_applied["max_output_tokens"] = value
        if requested_reasoning_effort is None and "reasoning_effort" in configured_defaults:
            value = _normalize_reasoning_effort(configured_defaults["reasoning_effort"])
            if value is not None:
                profile["reasoning_effort"] = value
                generation_config_defaults_applied["reasoning_effort"] = value

    _adjust_generation_budget(
        profile,
        capability_profile_applied,
        generation_config_adjustments,
        max_output_source=(
            "request"
            if requested_max_output is not None
            else "resource_query_generation_defaults"
            if "max_output_tokens" in generation_config_defaults_applied
            else "profile"
        ),
    )
    _apply_reasoning_effort_defaults(
        profile,
        capability_profile_applied,
        generation_config_adjustments,
    )

    # --- Conversation-scoped destructive-action authorization check ---
    # Submit/provision consent is durable across the conversation when the
    # user has asked LoomAI to create a working/proven slice. Delete still
    # needs an explicit scoped confirmation.
    prior_messages = list(messages)
    if prior_messages and prior_messages[-1].get("role") == "user":
        prior_messages = prior_messages[:-1]
    conversation_created_slices = _extract_conversation_created_slices(prior_messages)
    turn_start_created_slices = set(conversation_created_slices)
    if _conversation_authorizes_provisioning(messages):
        logger.info("Conversation authorizes slice provisioning actions")
    else:
        logger.debug("Conversation does NOT authorize slice provisioning actions")

    # Pre-fetch data for high-confidence intents
    prefetched_data = ""
    prefetched_tools: list[tuple[str, str]] = []  # (tool_name, result)
    prefetched_tool_outputs: list[tuple[str, str]] = []  # full results for validation

    confirm_needed = False  # C2: dry run for destructive ops

    if allow_automatic_context and intent_confidence in ("high", "medium") and intent_tool:
        intent_args = _apply_prompt_lease_duration(intent_tool, intent_args, user_message)
        if is_destructive(intent_tool):
            if not _is_destructive_tool_authorized(
                intent_tool,
                intent_args,
                messages,
                conversation_created_slices,
                conversation_id,
            ):
                confirm_needed = True
                # The user's next bare "yes" authorizes exactly this call.
                _consent.record_pending(conversation_id, intent_tool, intent_args)
                logger.info("Destructive intent %s — will ask for confirmation", intent_tool)
            else:
                try:
                    result = await execute_tool(intent_tool, intent_args, request=request)
                    if _tool_result_is_token_expired(result):
                        return _single_sse_response(_token_expired_event(intent_tool, result))
                    _record_created_slice_from_tool(
                        intent_tool,
                        intent_args,
                        result,
                        conversation_created_slices,
                    )
                    prefetched_data = result
                    prefetched_tool_outputs.append((intent_tool, result))
                    limit = _tool_context_limit(
                        intent_tool,
                        user_message,
                        profile,
                        compact_resource_tools_enabled=compact_resource_tools_enabled,
                    )
                    prefetched_tools.append((intent_tool, result[:limit]))
                    logger.info("Pre-fetched authorized destructive intent %s", intent_tool)
                    try:
                        record_intent_result(model, intent_tool, True)
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning("Pre-fetch failed for %s: %s", intent_tool, e)
                    try:
                        record_intent_result(model, intent_tool, False)
                    except Exception:
                        pass
        else:
            try:
                result = await execute_tool(intent_tool, intent_args, request=request)
                if _tool_result_is_token_expired(result):
                    return _single_sse_response(_token_expired_event(intent_tool, result))
                _record_created_slice_from_tool(
                    intent_tool,
                    intent_args,
                    result,
                    conversation_created_slices,
                )
                prefetched_data = result
                prefetched_tool_outputs.append((intent_tool, result))
                limit = _tool_context_limit(
                    intent_tool,
                    user_message,
                    profile,
                    compact_resource_tools_enabled=compact_resource_tools_enabled,
                )
                prefetched_tools.append((intent_tool, result[:limit]))
                logger.info("Pre-fetched %s (%s confidence)", intent_tool, intent_confidence)
                # Record intent success for learning (persists to disk)
                try:
                    record_intent_result(model, intent_tool, True)
                except Exception:
                    pass
            except Exception as e:
                logger.warning("Pre-fetch failed for %s: %s", intent_tool, e)
                try:
                    record_intent_result(model, intent_tool, False)
                except Exception:
                    pass

    elif allow_automatic_context and template and not template.get("confirm"):
        # Non-destructive template — execute first step
        if template["steps"]:
            step_tool, step_args = template["steps"][0]
            try:
                step_args = _apply_prompt_lease_duration(step_tool, step_args, user_message)
                result = await execute_tool(step_tool, step_args, request=request)
                if _tool_result_is_token_expired(result):
                    return _single_sse_response(_token_expired_event(step_tool, result))
                prefetched_data = result
                prefetched_tool_outputs.append((step_tool, result))
                limit = _tool_context_limit(
                    step_tool,
                    user_message,
                    profile,
                    compact_resource_tools_enabled=compact_resource_tools_enabled,
                )
                prefetched_tools.append((step_tool, result[:limit]))
            except Exception:
                pass

    if (
        allow_automatic_context
        and strict_fabric_query_contract_enabled
        and _is_host_threshold_query(user_message)
        and not any(t == "get_site_hosts" for t, _ in prefetched_tools)
    ):
        try:
            result = await _collect_host_threshold_inventory(user_message)
            prefetched_tool_outputs.append(("get_site_hosts", result))
            limit = _tool_context_limit(
                "get_site_hosts",
                user_message,
                profile,
                compact_resource_tools_enabled=compact_resource_tools_enabled,
            )
            prefetched_tools.append(("get_site_hosts", result[:limit]))
            logger.info("Pre-fetched cross-site host threshold inventory")
        except Exception as e:
            logger.warning("Host threshold pre-fetch failed: %s", e)

    # Always pre-fetch slice summary (lightweight, ~200 tokens)
    if allow_automatic_context and not any(t == "list_slices" for t, _ in prefetched_tools):
        try:
            slice_summary = await execute_tool("list_slices", {}, request=request)
            if _tool_result_is_token_expired(slice_summary):
                return _single_sse_response(_token_expired_event('list_slices', slice_summary))
            prefetched_tool_outputs.append(("list_slices", slice_summary))
            limit = _tool_context_limit(
                "list_slices",
                user_message,
                profile,
                compact_resource_tools_enabled=compact_resource_tools_enabled,
                background="slice" not in (user_message or "").lower(),
            )
            prefetched_tools.append(("list_slices", slice_summary[:limit]))
        except Exception:
            pass

    # Pre-fetch FABlib examples when weave/experiment creation detected
    _weave_keywords = ["weave", "experiment", "topology", "deploy"]
    _benchmark_keywords = [
        "iperf", "benchmark", "bandwidth test", "throughput test",
        "latency test", "fio", "stress-ng", "stress test",
    ]
    _slice_mutation_keywords = [
        "add node", "add a node", "attach", "add component",
        "add network", "change image", "update node", "remove node",
        "remove network", "modify slice", "add gpu", "add nic",
        "add smartnic", "add fpga", "add nvme",
    ]
    # Any FABRIC/FABlib code-generation context should inject the ground truth.
    # This catches non-slice requests like "write Python for FABRIC that lists
    # GPU sites" plus slice/network requests that otherwise slip past the
    # weave/mutation keyword filters.
    _fablib_code_keywords = [
        "fablib", "fabric_lib", "fabrictestbed",
        "l2bridge", "l2sts", "l2ptp", "fabnetv4", "fabnetv6", "fabnet",
        "new_slice", "add_node", "add_l2network", "add_l3network",
        "slice.submit", "slice.add",
    ]
    _msg_lower = user_message.lower()
    _is_weave_request = any(kw in _msg_lower for kw in _weave_keywords)
    _is_benchmark_request = any(kw in _msg_lower for kw in _benchmark_keywords)
    _is_slice_mutation = any(kw in _msg_lower for kw in _slice_mutation_keywords)
    _is_fablib_code = any(kw in _msg_lower for kw in _fablib_code_keywords)
    _code_gen_verbs = ("write", "create", "code", "function", "python", "script", "generate")
    _fabric_code_terms = ("fabric", "fablib", "fabrictestbed", "fablibmanager")
    _is_fabric_code = (
        any(v in _msg_lower for v in _code_gen_verbs)
        and any(term in _msg_lower for term in _fabric_code_terms)
    )
    # Also treat "slice" + any code-generation verb as a FABlib code request.
    _has_slice_word = "slice" in _msg_lower
    _is_slice_code = _has_slice_word and any(v in _msg_lower for v in _code_gen_verbs)
    _needs_fablib_ref = (
        _is_weave_request
        or _is_slice_mutation
        or _is_fablib_code
        or _is_fabric_code
        or _is_slice_code
    )
    if (
        allow_automatic_context
        and _is_weave_request
        and not any(t == "search_examples" for t, _ in prefetched_tools)
    ):
        try:
            examples = await execute_tool("search_examples", {"query": user_message[:100]}, request=request)
            prefetched_tool_outputs.append(("search_examples", examples))
            limit = _tool_context_limit(
                "search_examples",
                user_message,
                profile,
                compact_resource_tools_enabled=compact_resource_tools_enabled,
            )
            prefetched_tools.append(("search_examples", examples[:limit]))
        except Exception:
            pass

    # --- RAG retrieval: hybrid semantic+BM25 search over the knowledge corpus ---
    # Runs for every non-trivial chat turn. Retrieved chunks are injected as
    # a "Retrieved Context" block in the system prompt.
    rag_context_block = ""
    if allow_automatic_context:
        try:
            from app.rag import refresh_index_if_stale, retrieve_for_chat, format_hits_as_context
            # Cheap incremental refresh (rescans corpus, re-embeds changed files only)
            await refresh_index_if_stale(max_age=30.0)
            # Don't waste retrieval on trivial greetings
            if len(user_message) >= 8:
                # Weave-biased retrieval when the user is clearly talking about weaves
                hits = retrieve_for_chat(
                    user_message,
                    k=5,
                    min_score=0.30,
                    weave_bias=_is_weave_request,
                )
                if hits:
                    # Size budget scales with tier: compact models get less, large models more
                    max_rag_chars = {
                        "compact": 1500,
                        "standard": 4000,
                        "large": 6000,
                    }.get(profile["tier"], 3000)
                    rag_context_block = format_hits_as_context(hits, max_chars=max_rag_chars)
                    logger.info(
                        "RAG: retrieved %d chunks for chat (top source=%s, top score=%.2f)",
                        len(hits), hits[0].chunk.source_type, hits[0].score,
                    )
        except Exception as e:
            logger.debug("RAG retrieval skipped: %s", e)

    # --- Build system prompt ---
    # For low-confidence / complex requests: use the full system prompt with tool-calling
    # so the LLM can call write_file, create_slice, etc. directly.
    # For high-confidence: use compact LoomAI-mode prompt (LoomAI already executed the tool).
    use_full_llm_mode = bool(explicit_agent_id) or (intent_confidence == "low")

    if explicit_agent_id and explicit_agent_info:
        system_parts = [
            _active_agent_system_block(
                explicit_agent_id,
                explicit_agent_info,
                explicit=True,
            )
        ]
        if explicit_agent_controls_context:
            system_parts.append(
                "\n\n## LoomAI Runtime\n"
                "You are running inside LoomAI and may use the available tools when "
                "the selected agent or user task requires them. Do not run automatic "
                "inventory, RAG, or query-reporter workflows unless the selected "
                "agent asks for them. If the selected agent requires a specific "
                "output shape, preserve that shape exactly."
            )
    elif use_full_llm_mode:
        # Full mode — LLM needs tool descriptions and the ability to call tools
        # But for compact models, use compact prompt even in full mode to avoid overflow
        if profile["tier"] == "compact":
            system_parts = [LOOMAI_MODE_PROMPT]
        else:
            system_parts = [get_system_prompt(profile["system_prompt"])]
        # Add tool-use instructions
        system_parts.append(
            "\n\n## Tool Use\n"
            "You have tools to: create/manage slices and nodes, write/read files, "
            "SSH to VMs, list sites/templates/artifacts, run weave scripts.\n"
            "Use tools proactively. Summarize after each tool call.\n\n"
            "**Creating weaves**: Use `create_weave` with ALL options in ONE call.\n"
            "**Writing FABlib code**: ALWAYS call `search_examples(query)` first to find\n"
            "proven code patterns, then `read_file` to load the example. Adapt it.\n"
            "Never write FABlib code from scratch — use the example library.\n"
            "When updating a weave, read `weave.md` first — it is the authoritative spec.\n"
            "**JSON output**: Never wrap JSON in markdown ```json``` code fences. "
            "Emit raw JSON only when the user asks for JSON.\n\n"
            "## Critical Rules — Read Carefully\n"
            "**Create slice ≠ submit slice.** When the user says 'create a slice', "
            "build a DRAFT topology only (`create_slice`, `add_node`, `add_fabnet`, "
            "`add_network`, `add_component`). Call `submit_slice` only when the "
            "conversation has authorized provisioning: explicit words like submit, "
            "deploy, or provision, or a create/build goal that also asks you to "
            "demonstrate working behavior such as ping, curl, SSH, iperf, or a "
            "service check. In authorized create-and-verify goals, call "
            "`submit_slice(wait_for_stableok=true)` before any final answer. Authorization "
            "is durable across the conversation for slices created in this chat; "
            "the user does not need to repeat magic "
            "words every turn. If there is no such authorization, describe the "
            "draft and ask for confirmation before submitting. If you receive "
            "DESTRUCTIVE_ACTION_BLOCKED, do not retry; summarize instead.\n\n"
            "**Long provisioning jobs.** For submit/wait provisioning, prefer "
            "`submit_slice(wait_for_stableok=true, background=true)` so the "
            "backend keeps working even if this chat stream is interrupted. "
            "Use the returned `job_id` with `get_job_status(job_id, "
            "wait_seconds=30)` until the job is ready before calling "
            "`configure_networking` or claiming the slice is provisioned.\n\n"
            "**Lease duration.** If the user specifies a lease duration, pass it "
            "explicitly: use `lease_hours` on `create_slice` and `submit_slice`, "
            "and `hours` on `renew_slice`. For benchmark or short-lived slices "
            "asking for a 6-hour lease, pass `lease_hours=6` all the way through "
            "creation and submission.\n\n"
            "**Create slice ≠ create weave.** A SLICE is a live FABRIC topology "
            "(nodes + networks, provisioned as VMs). A WEAVE is a project directory "
            "in `my_artifacts/` containing scripts, notebooks, and metadata. If the "
            "user asks for a slice, use `create_slice` only — do NOT also call "
            "`create_weave` unless they explicitly ask for one.\n\n"
            "**Multi-site FABNetv4/FABNetv6.** To connect N nodes at different sites "
            "over FABnet, call `add_fabnet(slice_name, node_name, net_type='IPv4')` "
            "ONCE PER NODE. FABRIC automatically creates a per-site FABnet network "
            "for each site and routes between them via its backbone. Do NOT use "
            "`add_network(type='FABNetv4', interfaces=[...])` for multi-site — a "
            "single FABNetv4 service cannot span more than one site and the FABRIC "
            "orchestrator will reject it with 'Service cannot span N sites. Limit: 1.'\n\n"
            "**Post-StableOK data-plane networking.** For any submitted multi-node "
            "slice with a private L2 network or FABNetv4/FABNetv6 connectivity, "
            "do not stop at StableOK. After the slice is StableOK, call "
            "`configure_networking(slice_name, verify=true)`. This assigns "
            "private L2 IPs when the draft did not specify them, runs FABNet "
            "post-boot setup, adds FABNetv4 aggregate routes, and returns ping "
            "evidence using target IP addresses. In your final answer, cite the "
            "source node, target IP, and ping result from `configure_networking`; "
            "do not use `ping vm2` or any other hostname-only ping as the proof.\n\n"
            "**Don't retry blocked actions.** If a tool returns "
            "`DESTRUCTIVE_ACTION_BLOCKED`, STOP. Summarize progress and ask the "
            "user for one scoped confirmation in plain text. Delete always needs "
            "confirmation for the named slice; submit/provision can be authorized "
            "by an earlier create-and-verify goal for a slice created in this "
            "chat. Retrying the same blocked tool without new confirmation will "
            "be blocked again.\n\n"
            "**Multi-node operations must touch EVERY node.** When the user says "
            "'all nodes', 'every node', 'the nodes', or any phrase implying all "
            "nodes in a slice, you MUST issue at least one `ssh_execute`, "
            "`write_vm_file`, `read_vm_file`, or `reboot_and_wait` call against "
            "every node returned by `get_slice`. Before emitting your final "
            "summary, verify you touched every node. Your summary MUST list each "
            "node by name with its per-node status (success/partial/skipped/error). "
            "Do NOT say 'both nodes' if there are three.\n\n"
            "**Container filesystem ≠ VM filesystem.** `write_file`, `read_file`, "
            "`list_directory`, `create_directory`, `delete_path` operate on the "
            "LoomAI container's user storage (rooted at `my_artifacts/`, "
            "`my_slices/`, `notebooks/`). Files written with these tools are NOT "
            "visible inside provisioned VMs. To put a file on a VM, use "
            "`write_vm_file(slice_name, node_name, path, content)`. To run a "
            "command on a VM, use `ssh_execute(...)`. Never `ssh_execute "
            "python3 /home/fabric/script.py` unless you first `write_vm_file` to "
            "that path on the VM.\n\n"
            "**Reboot handling.** To reboot a VM as part of a workflow, use "
            "`reboot_and_wait(slice_name, node_name)`. It reboots via SSH and "
            "polls until the VM is reachable again (default 5 min). For "
            "'reboot if needed' workflows, first check "
            "`test -f /var/run/reboot-required` with ssh_execute; if present, "
            "call reboot_and_wait, then continue with post-reboot steps.\n\n"
            "**Be honest in your summary.** Before writing your final summary, "
            "count the nodes and operations you actually performed. Mention any "
            "node that was skipped or any operation that returned an error or "
            "timed out. Do not claim success when a tool returned an error. "
            "Be specific: 'node1 fully configured; node2 apt lock — 5/10 "
            "packages installed; node3 not reached.'\n"
        )
        # Inject create-weave skill when the user is building weaves/experiments
        if _is_weave_request:
            _skill_path = os.path.join(_AI_TOOLS_DIR, "shared", "skills", "create-weave.md")
            try:
                with open(_skill_path) as _sf:
                    _skill = _sf.read()
                _skill = parse_markdown_asset(_skill).body.strip()
                system_parts.append(f"\n\n## Weave Creation Guide\n\n{_skill}\n")
            except Exception:
                pass
        # Inject benchmark skill when the user wants to run an ad-hoc test
        # on existing nodes. This must be in the system prompt (not just
        # RAG context) so the model reliably follows the IP-discovery and
        # anti-weave rules. Mirrors the create-weave injection above.
        if _is_benchmark_request and not _is_weave_request:
            _bench_path = os.path.join(_AI_TOOLS_DIR, "shared", "skills", "benchmark.md")
            try:
                with open(_bench_path) as _bf:
                    _bench = _bf.read()
                _bench = parse_markdown_asset(_bench).body.strip()
                system_parts.append(f"\n\n## Benchmark Guide\n\n{_bench}\n")
            except Exception:
                pass
        # Inject FABlib ground-truth method reference on FABRIC/FABlib code
        # generation requests. Prevents hallucinated method names like
        # fablib.get_fab(), node.write_file(), network.add_interface() —
        # all verified to occur in live probes at every temperature.
        if _needs_fablib_ref:
            _ref = _load_fablib_ref()
            if _ref:
                # Cap at 4500 chars (~1100 tokens) — fits the standard-tier
                # budget comfortably and covers the FablibManager/Slice/Node
                # method lists plus the "common hallucinations" preamble.
                _ref_snippet = _ref[:4500]
                system_parts.append(
                    "\n\n## FABlib Ground Truth — Real Method Names\n\n"
                    "The following is the authoritative list of real FABlib methods. "
                    "If a method is NOT in this reference, it does NOT exist — do not "
                    "invent method names. This file is extracted directly from the "
                    "installed fabrictestbed-extensions package.\n\n"
                    f"```python\n{_ref_snippet}\n```\n"
                )
    elif profile["tier"] == "compact":
        system_parts = [LOOMAI_MODE_PROMPT]
    else:
        system_parts = [LOOMAI_MODE_EXTENDED]

    # Inject pre-fetched data
    if prefetched_tools:
        data_section = "\n\n## Current Data\n\n"
        for tool_name, result in prefetched_tools:
            data_section += f"**{tool_name}**:\n```json\n{result}\n```\n\n"
        system_parts.append(data_section)

    # Inject retrieved RAG context (from semantic search over the corpus)
    if rag_context_block:
        system_parts.append("\n\n" + rag_context_block)

    # C2: If destructive action detected, tell LLM to confirm
    if confirm_needed:
        system_parts.append(
            f"\n\n## Action Requires Confirmation\n"
            f"The user wants to execute: **{intent_tool}**({json.dumps(intent_args)})\n"
            f"This is a destructive operation. Ask the user to confirm before proceeding.\n"
            f"{_consent.confirmation_instruction(intent_tool, intent_args)}\n"
            f"Once they have replied 'yes', call {intent_tool} with the same arguments."
        )

    # If template matched and needs confirmation, tell the LLM
    if template and template.get("confirm"):
        steps_desc = ", ".join(f"{s[0]}({s[1]})" for s in template["steps"][:5])
        system_parts.append(
            f"\n\n## Planned Action\n"
            f"The user wants to: {template['description']}\n"
            f"Steps: {steps_desc}\n"
            f"Ask the user to confirm before executing."
        )

    # Auto-activate agents based on intent when no agent is explicitly selected
    if not agent_id and _is_slice_operator_intent(intent_tool, user_message):
        agent_id = "fabric-slice-operator"
    if not agent_id and use_full_llm_mode:
        import re as _re
        msg_lower = user_message.lower()
        if (_re.search(r"write|create|update|modify|build|edit.*\.py|fablib|weave|script|code|slice.*node", msg_lower)
                and intent_tool in ("create_weave", "read_file", "")):
            agent_id = "fablib-coder"
    if (
        not agent_id
        and strict_fabric_query_contract_enabled
        and _is_fabric_information_query(user_message, intent_tool)
    ):
        agent_id = "fabric-query-reporter"

    if strict_fabric_query_contract_enabled and _is_host_threshold_query(user_message):
        limit = _requested_result_limit(user_message)
        system_parts.append(
            "\n\n## Host Threshold Query Rule\n"
            f"The user is asking for host-level threshold evidence. Before the FINAL ANSWER, "
            f"use host-level tool data (`get_site_hosts`) for relevant sites when it is not "
            f"already present in Current Data. The FINAL ANSWER must enumerate every returned "
            f"host that matches the requested threshold, up to {limit} hosts, with host name, "
            f"site, state, cores, RAM, and disk values. Do not answer with only site names."
        )

    if agent_id and not explicit_agent_id:
        agents = _load_agents()
        if agent_id in agents:
            system_parts.append(
                "\n\n"
                + _active_agent_system_block(agent_id, agents[agent_id], explicit=False)
            )

    if slice_context:
        # Truncate very large contexts
        ctx = slice_context[:8000] if len(slice_context) > 8000 else slice_context
        system_parts.append(
            "\n\n## Current Slice Context\n\n"
            "The user is viewing this slice topology:\n\n"
            f"```json\n{ctx}\n```"
        )

    current_session_state_block = ""
    current_session_slice_state: dict[str, dict[str, Any]] = {}
    if weak_context_management_enabled and conversation_created_slices:
        current_session_state_block = await _build_current_session_state_block(
            conversation_created_slices,
            prefetched_tool_outputs,
            user_message,
            request,
            state_cache=current_session_slice_state,
        )
        if current_session_state_block:
            system_parts.append("\n\n" + current_session_state_block)
    session_state_injected = bool(current_session_state_block)

    # Filter tools based on model capacity (full set for low-confidence/complex requests)
    max_tools = len(TOOL_SCHEMAS) if use_full_llm_mode else profile["max_tools"]
    tools_for_model = filter_tool_schemas(TOOL_SCHEMAS, max_tools)
    # Tool schemas ride along on every request; trim_conversation() charges
    # them to the conversation budget (they were not counted at all before).
    tool_token_estimate = (
        estimate_tool_schema_tokens(tools_for_model) if profile.get("supports_tools", True) else 0
    )
    # Fit the prompt text to its 30% share (the core prompt is the floor):
    # prefetched data, RAG context and skill files are trimmed first; the
    # core prompt and the session-state block only as a last resort.
    _protected_parts = {0}
    if session_state_injected and len(system_parts) > 1:
        _protected_parts.add(len(system_parts) - 1)
    system_parts, _truncated_parts = fit_system_parts(
        system_parts,
        system_prompt_budget(profile, core_tokens=estimate_tokens(system_parts[0]) if system_parts else 0),
        _protected_parts,
    )
    system_message = {"role": "system", "content": "\n".join(system_parts)}
    system_token_estimate = estimate_tokens(system_message["content"])
    if _truncated_parts:
        logger.info(
            "System prompt fitted for %s: %d prompt + %d tool tokens in a %s-token window (parts truncated: %s)",
            model, system_token_estimate, tool_token_estimate, profile.get("context_window"), _truncated_parts,
        )

    tools_disabled = False  # Set True if model can't do tool calling
    temperature_disabled = bool(profile.get("strip_temperature"))  # Set True if model rejects or should omit temperature
    if temperature_disabled:
        generation_config_adjustments.append({
            "field": "temperature",
            "source": "capability_profile",
            "profile_value": profile.get("temperature"),
            "applied_value": None,
            "reason": "model profile requires omitting temperature from provider requests",
        })
    reasoning_controls_disabled = False  # Set True if provider rejects reasoning controls
    context_compacted = False
    compacted_from_tokens = 0
    compacted_to_tokens = 0

    async def generate():
        nonlocal tools_disabled, temperature_disabled, reasoning_controls_disabled
        nonlocal model, model_api_type, server_url, api_key
        nonlocal context_compacted, compacted_from_tokens, compacted_to_tokens
        nonlocal profile, tools_for_model, tool_token_estimate, system_token_estimate
        import time as _time
        _start_time = _time.time()
        _tool_call_count = len(prefetched_tools)
        near_full_warned = False

        def _current_generation_config() -> dict[str, Any]:
            config = {
                "model": model,
                "endpoint_style": model_api_type,
                "context_window_tokens": profile.get("context_window"),
                "temperature": None if temperature_disabled else profile.get("temperature"),
                "top_p": profile.get("top_p"),
                "max_output_tokens": profile.get("max_output"),
            }
            if profile.get("reasoning_budget_mode"):
                config["reasoning_budget_mode"] = profile.get("reasoning_budget_mode")
            if profile.get("reasoning_effort"):
                config["reasoning_effort"] = profile.get("reasoning_effort")
            if profile.get("reasoning_effort_source"):
                config["reasoning_effort_source"] = profile.get("reasoning_effort_source")
            if profile.get("strip_temperature"):
                config["strip_temperature"] = True
            if reasoning_controls_disabled:
                config["reasoning_controls_disabled"] = True
            if generation_config_adjustments:
                config["adjustments"] = generation_config_adjustments
            if capability_profile_applied:
                config["capability_profile"] = capability_profile_applied
            if turn_budget:
                config["turn_budget"] = turn_budget
            return config

        def _current_fabric_query_validation_scope() -> bool:
            return (
                final_answer_retry_enabled
                and _model_in_final_answer_retry_scope(original_model_key, final_answer_retry_scope)
                and _fabric_query_validation_scope(
                    user_message,
                    agent_id,
                    executed_tool_names,
                    explicit_agent_controls_context=explicit_agent_controls_context,
                )
            )

        try:
            generation_config_event = {
                "generation_config": {
                    "requested": generation_config_requested,
                    "defaults_applied": generation_config_defaults_applied,
                    "adjustments": generation_config_adjustments,
                    "applied": _current_generation_config(),
                }
            }
            yield f"data: {json.dumps(generation_config_event)}\n\n"

            # Emit pre-fetched tool results to frontend
            for tool_name, result in prefetched_tools:
                if tool_name != "list_slices":  # Don't show background pre-fetch
                    yield f"data: {json.dumps({'tool_call': {'name': tool_name, 'arguments': intent_args}})}\n\n"
                    yield f"data: {json.dumps({'tool_result': {'name': tool_name, 'result': result[:2000]}})}\n\n"
                    yield f"data: {json.dumps({'execution_progress': f'Executed {tool_name}'})}\n\n"

            conversation = [system_message] + messages

            def _persist_conversation(final_text: str | None = None) -> None:
                if not conversation_id:
                    return
                try:
                    from app.chat_sessions import save_chat_session

                    session_messages = _conversation_without_system(conversation)
                    if final_text and final_text.strip():
                        session_messages = session_messages + [{
                            "role": "assistant",
                            "content": final_text.strip(),
                        }]
                    save_chat_session(
                        conversation_id,
                        session_messages,
                        metadata={
                            "model": original_model_key,
                            "agent": agent_id or explicit_agent_id or "",
                            "request_id": request_id,
                        },
                    )
                except Exception as exc:
                    logger.debug("Chat session persist skipped: %s", exc)

            _persist_conversation()
            tool_round = 0
            executed_tool_names = [tool_name for tool_name, _ in prefetched_tools]
            executed_tool_outputs = list(prefetched_tool_outputs)
            final_answer_retry_count = 0
            incomplete_response_after_retry = False
            final_answer_best_effort = False
            host_threshold_completion_applied = False
            zero_visible_output_retry_count = 0
            verification_evidence_guard_applied = False
            verification_evidence_appended = False
            empty_visible_final_retry_count = 0
            empty_visible_synthesized_answer = False
            empty_tool_call_placeholder_count = 0
            draft_submission_retry_count = 0
            background_job_poll_retry_count = 0
            provider_retry_count = 0
            session_state_marker_appended = False
            duplicate_slice_guard_triggered = 0
            tool_progress_tracker: dict[str, dict[str, Any]] = {}
            tool_loop_stop: dict[str, Any] | None = None
            turn_budget_token_limit = int(turn_budget.get("max_tokens") or 0)
            turn_budget_cost_limit = float(turn_budget.get("max_cost_usd") or 0)
            turn_budget_cost_rate = float(turn_budget.get("cost_per_1k_tokens_usd") or 0.0)
            turn_budget_tokens_estimate = 0
            turn_budget_cost_estimate = 0.0

            def _new_created_slice_names() -> set[str]:
                return conversation_created_slices - turn_start_created_slices

            def _finalize_visible_text(text: str | None) -> str:
                nonlocal session_state_marker_appended
                final_text = text or ""
                if not weak_context_management_enabled:
                    return final_text
                final_text, appended = _append_session_state_marker(
                    final_text,
                    _new_created_slice_names(),
                )
                if appended:
                    session_state_marker_appended = True
                return final_text

            def _context_usage_metadata() -> dict[str, Any]:
                return {
                    "session_state_injected": session_state_injected,
                    "session_state_marker_appended": session_state_marker_appended,
                    "created_slices_count": len(conversation_created_slices),
                    "duplicate_slice_guard_triggered": duplicate_slice_guard_triggered,
                    "context_compacted": context_compacted,
                    "compacted_from_tokens": compacted_from_tokens,
                    "compacted_to_tokens": compacted_to_tokens,
                }

            def _usage_payload() -> dict[str, Any]:
                elapsed_ms = int((_time.time() - _start_time) * 1000)
                return {
                    "tokens": estimate_conversation_tokens(conversation),
                    "tool_calls": _tool_call_count,
                    "duration_ms": elapsed_ms,
                    "generation_config_applied": _current_generation_config(),
                    "generation_config_defaults_applied": generation_config_defaults_applied,
                    "generation_config_adjustments": generation_config_adjustments,
                    "final_answer_retry_count": final_answer_retry_count,
                    "incomplete_response_after_retry": incomplete_response_after_retry,
                    "final_answer_best_effort": final_answer_best_effort,
                    "host_threshold_completion_applied": host_threshold_completion_applied,
                    "zero_visible_output_retry_count": zero_visible_output_retry_count,
                    "verification_evidence_guard_applied": verification_evidence_guard_applied,
                    "verification_evidence_appended": verification_evidence_appended,
                    "empty_visible_final_retry_count": empty_visible_final_retry_count,
                    "empty_visible_synthesized_answer": empty_visible_synthesized_answer,
                    "empty_tool_call_placeholder_count": empty_tool_call_placeholder_count,
                    "draft_submission_retry_count": draft_submission_retry_count,
                    "background_job_poll_retry_count": background_job_poll_retry_count,
                    "provider_retry_count": provider_retry_count,
                    "tool_loop_stop_reason": (tool_loop_stop or {}).get("reason"),
                    "turn_budget_tokens_estimate": turn_budget_tokens_estimate,
                    "turn_budget_cost_estimate_usd": round(turn_budget_cost_estimate, 8),
                    **_context_usage_metadata(),
                }

            # Tool-failure breakers are per turn: a model that makes one failing
            # call per round used to reset the counter every round and run all
            # 100 rounds (each up to the per-tool timeout).
            consecutive_errors = 0
            total_tool_errors = 0
            while tool_round < _MAX_TOOL_ROUNDS:
                if await request.is_disconnected():
                    break
                if request_id and request_id in _cancelled_requests:
                    break

                # Trim conversation to fit model's context window
                trim_result = trim_conversation(
                    conversation,
                    system_token_estimate,
                    profile,
                    tool_tokens=0 if tools_disabled else tool_token_estimate,
                )
                conversation = trim_result.messages
                if trim_result.was_compacted:
                    context_compacted = True
                    compacted_from_tokens = max(
                        compacted_from_tokens,
                        trim_result.compacted_from_tokens,
                    )
                    compacted_to_tokens = trim_result.compacted_to_tokens

                # Warn the user once per turn when the context is nearly full
                if trim_result.near_full and not near_full_warned:
                    near_full_warned = True
                    yield f"data: {json.dumps({'warning': 'Context window is nearly full. The conversation will be automatically compacted to continue.'})}\n\n"
                    # If context is full AND we've been trimming, stop tool calls
                    if trim_result.was_trimmed and tool_round >= 3:
                        ctx_full_msg = "\n\n[Context window full after repeated tool calls. Generating a summary.]\n"
                        yield f"data: {json.dumps({'content': ctx_full_msg})}\n\n"
                        break

                round_token_estimate = estimate_conversation_tokens(conversation) + int(
                    profile.get("max_output") or 0
                )
                projected_tokens = turn_budget_tokens_estimate + round_token_estimate
                projected_cost = _estimated_turn_cost(projected_tokens, turn_budget_cost_rate)
                budget_reason = ""
                if turn_budget_token_limit > 0 and projected_tokens > turn_budget_token_limit:
                    budget_reason = "turn_token_budget_exceeded"
                elif (
                    turn_budget_cost_limit > 0
                    and turn_budget_cost_rate > 0
                    and projected_cost > turn_budget_cost_limit
                ):
                    budget_reason = "turn_cost_budget_exceeded"
                if budget_reason:
                    turn_budget_tokens_estimate = projected_tokens
                    turn_budget_cost_estimate = projected_cost
                    tool_loop_stop = {
                        "reason": budget_reason,
                        "rounds_used": tool_round,
                        "projected_tokens": projected_tokens,
                        "max_tokens": turn_budget_token_limit,
                        "projected_cost_usd": round(projected_cost, 8),
                        "max_cost_usd": turn_budget_cost_limit,
                        "cost_per_1k_tokens_usd": turn_budget_cost_rate,
                        "message": (
                            "Stopped before another provider/tool round because "
                            "the configured per-turn budget would be exceeded."
                        ),
                    }
                    stop_msg = (
                        "\n\n[Stopped before another model/tool round because "
                        "the configured per-turn budget would be exceeded. "
                        "Use Continue or raise the assistant turn budget to proceed.]\n"
                    )
                    stop_msg = _finalize_visible_text(stop_msg)
                    yield f"data: {json.dumps({'content': stop_msg})}\n\n"
                    yield f"data: {json.dumps({'tool_loop_stopped': tool_loop_stop})}\n\n"
                    yield f"data: {json.dumps({'usage': _usage_payload()})}\n\n"
                    _persist_conversation(stop_msg)
                    yield "data: [DONE]\n\n"
                    return
                turn_budget_tokens_estimate = projected_tokens
                turn_budget_cost_estimate = projected_cost

                # Make LLM call (non-streaming for tool rounds, streaming for final)
                # Build request body based on API type
                if model_api_type == "responses":
                    llm_body = _build_responses_body(
                        model, conversation, profile, tools_for_model, tools_disabled,
                        temperature_disabled,
                        reasoning_controls_disabled,
                    )
                else:
                    llm_body: dict[str, Any] = {
                        "model": model,
                        "messages": conversation,
                        "max_tokens": profile["max_output"],
                    }
                    if not temperature_disabled:
                        llm_body["temperature"] = profile["temperature"]
                    if profile.get("top_p") is not None:
                        llm_body["top_p"] = profile["top_p"]
                    # Only include tools if model supports them and they haven't been disabled
                    if not tools_disabled and profile.get("supports_tools", True):
                        llm_body["tools"] = tools_for_model
                    _apply_reasoning_controls(
                        llm_body,
                        profile,
                        model_api_type,
                        disabled=reasoning_controls_disabled,
                    )

                # Determine endpoint
                _endpoint = (
                    f"{server_url}/v1/responses"
                    if model_api_type == "responses"
                    else f"{server_url}/v1/chat/completions"
                )

                # Try non-streaming first to detect tool calls
                _llm_headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                resp, _retries = await _post_llm_json_with_retries(
                    _endpoint,
                    _llm_headers,
                    {**llm_body, "stream": False},
                    timeout=300.0,
                )
                provider_retry_count += _retries

                # On server error or model-not-found, try fallbacks
                # Fallbacks always use chat/completions (confirmed chat-type models)
                if resp.status_code >= 400 and resp.status_code != 200:
                    # On 404 (model not found), retry with default model
                    if resp.status_code == 404 and not use_nrp and not use_custom_provider:
                        from app.settings_manager import get_default_model as _settings_default
                        fallback_model = _settings_default()
                        if fallback_model and fallback_model != model:
                            logger.info("Model %s returned 404, retrying with default %s", model, fallback_model)
                            yield f"data: {json.dumps({'content': f'[Model {model} unavailable, switching to {fallback_model}...] '})}\n\n"
                            model = fallback_model
                            # The profile (context window, max_output, tool
                            # budget, tool support) belongs to the model; a
                            # fallback must not inherit the original's.
                            profile, tools_for_model, tool_token_estimate = _reprofile_for_model(
                                profile, fallback_model, use_full_llm_mode,
                            )
                            # Re-detect API type for fallback model
                            model_api_type = _get_model_type(fallback_model)
                            if model_api_type == "responses":
                                llm_body = _build_responses_body(
                                    model, conversation, profile, tools_for_model, tools_disabled,
                                    temperature_disabled,
                                    reasoning_controls_disabled,
                                )
                                _endpoint = f"{server_url}/v1/responses"
                                resp, _retries = await _post_llm_json_with_retries(
                                    _endpoint,
                                    {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                                    {**llm_body, "stream": False},
                                    timeout=300.0,
                                )
                                provider_retry_count += _retries
                            else:
                                llm_body = {
                                    "model": model,
                                    "messages": conversation,
                                    "max_tokens": profile["max_output"],
                                }
                                if not temperature_disabled:
                                    llm_body["temperature"] = profile["temperature"]
                                if profile.get("top_p") is not None:
                                    llm_body["top_p"] = profile["top_p"]
                                if not tools_disabled and profile.get("supports_tools", True):
                                    llm_body["tools"] = tools_for_model
                                _apply_reasoning_controls(
                                    llm_body,
                                    profile,
                                    model_api_type,
                                    disabled=reasoning_controls_disabled,
                                )
                                _endpoint = f"{server_url}/v1/chat/completions"
                                resp, _retries = await _post_llm_json_with_retries(
                                    _endpoint,
                                    {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                                    {**llm_body, "stream": False},
                                    timeout=300.0,
                                )
                                provider_retry_count += _retries

                    # On 5xx, fallback to NRP (always chat/completions)
                    if resp.status_code >= 500 and not use_nrp:
                        nrp_key = _get_nrp_api_key()
                        if nrp_key:
                            logger.info("Primary AI server returned %s, falling back to NRP", resp.status_code)
                            yield f"data: {json.dumps({'content': '[Falling back to NRP server...] '})}\n\n"
                            # NRP fallback always uses chat/completions
                            # NRP models support temperature, so reset the flag
                            temperature_disabled = False
                            llm_body = {
                                "model": model,
                                "messages": conversation,
                                "temperature": profile["temperature"],
                                "max_tokens": profile["max_output"],
                            }
                            if profile.get("top_p") is not None:
                                llm_body["top_p"] = profile["top_p"]
                            if not tools_disabled and profile.get("supports_tools", True):
                                llm_body["tools"] = tools_for_model
                            _apply_reasoning_controls(
                                llm_body,
                                profile,
                                "chat",
                                disabled=reasoning_controls_disabled,
                            )
                            _endpoint = f"{_nrp_server_url()}/v1/chat/completions"
                            resp, _retries = await _post_llm_json_with_retries(
                                _endpoint,
                                {"Authorization": f"Bearer {nrp_key}", "Content-Type": "application/json"},
                                {**llm_body, "stream": False},
                                timeout=300.0,
                            )
                            provider_retry_count += _retries
                            # Switch to chat API type for NRP
                            model_api_type = "chat"
                            server_url = _nrp_server_url()
                            api_key = nrp_key

                if resp.status_code != 200:
                    error_text = resp.text[:300]
                    _err_lower = error_text.lower()
                    # Check if error indicates this model requires the Responses API
                    if model_api_type != "responses" and (
                        "responses api" in _err_lower
                        or "moved to 'input'" in _err_lower
                        or ("'input'" in _err_lower and "'messages'" in _err_lower)
                    ):
                        logger.info("Model %s requires Responses API, switching from chat completions", model)
                        model_api_type = "responses"
                        continue  # Retry with Responses API format
                    # Check if error is due to temperature not being supported
                    if not temperature_disabled and "temperature" in _err_lower and (
                        "not supported" in _err_lower or "unsupported" in _err_lower
                    ):
                        logger.info("Model %s does not support temperature, retrying without", model)
                        temperature_disabled = True
                        continue  # Retry without temperature
                    # Check if error is due to reasoning controls not being supported
                    if (
                        not reasoning_controls_disabled
                        and _request_has_reasoning_controls(llm_body)
                        and _is_reasoning_control_error(error_text)
                    ):
                        logger.info("Model %s does not support reasoning controls, retrying without", model)
                        reasoning_controls_disabled = True
                        continue  # Retry without reasoning controls
                    # Check if error is due to tools not being supported
                    if _error_says_tools_unsupported(error_text) and not tools_disabled and "tools" in llm_body:
                        logger.info("Model %s may not support tools, retrying without", model)
                        tools_disabled = True
                        no_tools_msg = '[This model does not support tool calling. I will suggest loomai CLI commands instead.]\n\n'
                        yield f"data: {json.dumps({'content': no_tools_msg})}\n\n"
                        continue  # Retry without tools
                    yield f"data: {json.dumps(_provider_error_payload(resp.status_code, error_text, provider_retry_count))}\n\n"
                    return

                # Parse response based on API type
                if model_api_type == "responses":
                    result = resp.json()
                    output_items = result.get("output", [])
                    resp_text, tool_calls = _parse_responses_output(output_items)
                    # Build a compatible msg dict for downstream code
                    msg = {"role": "assistant", "content": resp_text}
                    if tool_calls:
                        msg["tool_calls"] = tool_calls
                    finish = "tool_calls" if tool_calls else "stop"
                else:
                    result = resp.json()
                    choices = result.get("choices") or [{}]
                    if not choices:
                        choices = [{}]
                    choice = choices[0]
                    msg = choice.get("message", {})
                    finish = choice.get("finish_reason", "")

                # Check for tool calls (handle both finish_reason="tool_calls" and "length")
                tool_calls = msg.get("tool_calls")
                visible_text = str(msg.get("content") or "").strip()
                if tool_calls and not visible_text:
                    msg["content"] = _TOOL_CALL_PLACEHOLDER
                    empty_tool_call_placeholder_count += 1
                    visible_text = _TOOL_CALL_PLACEHOLDER
                if (
                    not tool_calls
                    and not visible_text
                    and zero_visible_output_retry_count < 1
                    and _is_reasoning_budget_model(profile, capability_profile_applied)
                ):
                    zero_visible_output_retry_count = 1
                    current_effort = _normalize_reasoning_effort(profile.get("reasoning_effort"))
                    if not reasoning_controls_disabled and current_effort not in {None, "minimal"}:
                        profile["reasoning_effort"] = "minimal"
                        profile["reasoning_effort_source"] = "zero_visible_output_retry"
                        generation_config_adjustments.append({
                            "field": "reasoning_effort",
                            "source": "zero_visible_output_retry",
                            "profile_value": current_effort,
                            "applied_value": "minimal",
                            "reason": (
                                "retry after zero visible output; reduce hidden "
                                "reasoning so the provider emits answer text"
                            ),
                        })
                        logger.info(
                            "Retrying zero-visible-output reasoning response with minimal reasoning effort"
                        )
                    else:
                        reasoning_controls_disabled = True
                        generation_config_adjustments.append({
                            "field": "reasoning_controls",
                            "source": "zero_visible_output_retry",
                            "profile_value": current_effort or "none",
                            "applied_value": "disabled",
                            "reason": (
                                "retry after zero visible output; suppress provider "
                                "reasoning controls to recover answer text"
                            ),
                        })
                        logger.info(
                            "Retrying zero-visible-output reasoning response without reasoning controls"
                        )
                    continue

                if (
                    not tool_calls
                    and not visible_text
                    and _tool_call_count > 0
                    and empty_visible_final_retry_count < 1
                    and not _current_fabric_query_validation_scope()
                ):
                    empty_visible_final_retry_count = 1
                    empty_retry_prompt = _build_empty_visible_final_retry_prompt(
                        executed_tool_outputs
                    )
                    if model_api_type == "responses":
                        conversation.append({
                            "type": "message",
                            "role": "user",
                            "content": empty_retry_prompt,
                        })
                    else:
                        conversation.append({"role": "user", "content": empty_retry_prompt})
                    tools_disabled = True
                    logger.info("Retrying empty visible final answer after tool execution")
                    continue

                if (
                    not tool_calls
                    and not visible_text
                    and _tool_call_count > 0
                    and empty_visible_final_retry_count >= 1
                ):
                    synthesized = _synthesize_empty_visible_answer(executed_tool_outputs)
                    if synthesized:
                        empty_visible_synthesized_answer = True
                        msg["content"] = synthesized
                        visible_text = synthesized

                if tool_calls and finish in ("tool_calls", "length", "stop"):
                    # Append assistant message with tool calls to conversation.
                    if model_api_type == "responses":
                        # For Responses API, append text + function_call items
                        if msg.get("content"):
                            conversation.append({
                                "type": "message",
                                "role": "assistant",
                                "content": msg["content"],
                            })
                        for tc in tool_calls:
                            fn = tc.get("function", {})
                            for prelude_item in tc.get("_responses_prelude_items") or []:
                                if isinstance(prelude_item, dict):
                                    conversation.append(_responses_reasoning_item(prelude_item))
                            responses_item = tc.get("_responses_item")
                            if isinstance(responses_item, dict):
                                conversation.append(_responses_function_call_item(responses_item))
                            else:
                                conversation.append({
                                    "type": "function_call",
                                    "call_id": tc.get("id", ""),
                                    "name": fn.get("name", ""),
                                    "arguments": fn.get("arguments", "{}"),
                                })
                    else:
                        # Strip reasoning_content / reasoning fields (NVIDIA Nemotron-style
                        # reasoning models return these as a separate channel — we never
                        # want them re-sent on subsequent turns because: (a) the server
                        # usually rejects unknown fields; (b) they inflate conversation
                        # tokens without contributing visible content; (c) the estimator
                        # wouldn't count them anyway, making budget math wrong.
                        clean_msg = {
                            k: v for k, v in msg.items()
                            if k in ("role", "content", "tool_calls", "tool_call_id", "name")
                        }
                        conversation.append(clean_msg)

                    executed_round_tool_calls = 0
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        tc_name = fn.get("name", "")
                        tc_id = tc.get("id", "")
                        try:
                            tc_args = json.loads(fn.get("arguments", "{}"))
                        except json.JSONDecodeError:
                            tc_args = {}
                        tc_args = _apply_prompt_lease_duration(tc_name, tc_args, user_message)

                        # Notify frontend about tool call
                        yield f"data: {json.dumps({'tool_call': {'name': tc_name, 'arguments': tc_args}})}\n\n"

                        # Destructive-action safety gate — the LLM can decide
                        # on its own to call submit_slice/delete_slice. Submit
                        # consent can be durable across this conversation for
                        # slices created here; delete needs scoped confirmation.
                        duplicate_guard_result = None
                        if (
                            weak_context_management_enabled
                            and tc_name == "create_slice"
                            and conversation_created_slices
                        ):
                            duplicate_guard_result = _duplicate_slice_guard_result(
                                tc_args,
                                conversation_created_slices,
                                current_session_slice_state,
                            )

                        if duplicate_guard_result is not None:
                            duplicate_slice_guard_triggered += 1
                            logger.info(
                                "Blocked duplicate create_slice tool call for weak model: tracked=%s args=%s",
                                sorted(conversation_created_slices),
                                tc_args,
                            )
                            tool_result = duplicate_guard_result
                        elif (
                            is_destructive(tc_name)
                            and not _is_destructive_tool_authorized(
                                tc_name,
                                tc_args,
                                messages,
                                conversation_created_slices,
                                conversation_id,
                            )
                        ):
                            logger.info(
                                "BLOCKED destructive LLM-initiated tool call: %s (not authorized for this conversation)",
                                tc_name,
                            )
                            # Remember exactly what was blocked so the user's
                            # next bare "yes" authorizes it and nothing else.
                            _consent.record_pending(conversation_id, tc_name, tc_args)
                            tool_result = json.dumps({
                                "error": "DESTRUCTIVE_ACTION_BLOCKED",
                                "tool": tc_name,
                                "message": (
                                    f"{tc_name} is a destructive action and "
                                    f"this conversation has not authorized it "
                                    f"for the requested resource. DO NOT RETRY "
                                    f"this tool now. Summarize progress, then: "
                                    + _consent.confirmation_instruction(tc_name, tc_args)
                                    + " Submit/provision consent may also come "
                                    f"from an earlier create-and-verify goal for "
                                    f"a slice created in this chat."
                                ),
                            })
                        else:
                            # Per-tool outer timeout. SSH operations on cold VMs
                            # can easily exceed the old 5-min default (apt install,
                            # docker pull, kernel upgrade). For ssh_execute / vm
                            # file ops we honor the caller-specified timeout + 60s
                            # grace to cover transport overhead; for everything
                            # else we keep a conservative 5-min default.
                            if tc_name in ("ssh_execute", "write_vm_file", "read_vm_file", "download_file_bulk", "reboot_and_wait", "configure_networking", "execute_recipe", "run_python_script", "run_jupyter_notebook"):
                                _requested = tc_args.get("timeout") if isinstance(tc_args, dict) else None
                                if isinstance(_requested, (int, float)) and _requested > 0:
                                    _outer_timeout = min(1860, int(_requested) + 60)
                                else:
                                    _outer_timeout = 660  # 600s default + 60s grace
                            elif tc_name == "submit_slice" and (
                                bool(tc_args.get("wait"))
                                or bool(tc_args.get("wait_for_stableok"))
                            ):
                                _outer_timeout = 1860
                            else:
                                _outer_timeout = 300
                            try:
                                tool_result = await asyncio.wait_for(
                                    execute_tool(tc_name, tc_args, request=request), timeout=_outer_timeout
                                )
                            except asyncio.TimeoutError:
                                tool_result = json.dumps({
                                    "error": f"Tool {tc_name} timed out after {_outer_timeout}s",
                                    "hint": (
                                        "For long-running VM operations, set a larger "
                                        "'timeout' argument (max 1800s). For apt "
                                        "operations, include DEBIAN_FRONTEND=noninteractive "
                                        "and use apt-get -y -qq to avoid interactive prompts."
                                    ) if tc_name in ("ssh_execute", "write_vm_file") else None,
                                })
                                logger.warning("Tool %s timed out after %ds", tc_name, _outer_timeout)
                            if _tool_result_is_token_expired(tool_result):
                                yield f"data: {json.dumps(_token_expired_event(tc_name, tool_result))}\n\n"
                                return
                            _record_created_slice_from_tool(
                                tc_name,
                                tc_args,
                                tool_result,
                                conversation_created_slices,
                            )

                        ready_payload = _job_ready_sse_payload(tc_name, tool_result)
                        summary = _tool_summary(tc_name, tc_args, tool_result)

                        # Track consecutive errors to break infinite retry loops
                        if tool_result and '"error"' in tool_result:
                            consecutive_errors += 1
                            total_tool_errors += 1
                        else:
                            consecutive_errors = 0

                        # Notify frontend about tool result with summary
                        yield f"data: {json.dumps({'tool_result': {'name': tc_name, 'result': tool_result[:2000], 'summary': summary}})}\n\n"
                        if ready_payload:
                            yield f"data: {json.dumps({'ready': ready_payload})}\n\n"

                        executed_tool_outputs.append((tc_name, tool_result))
                        progress_stop = _record_tool_progress(
                            tool_progress_tracker,
                            tc_name,
                            tc_args,
                            tool_result,
                            limit=no_progress_limit,
                        )

                        # Add tool result to conversation with per-tool context limits.
                        tool_max = _tool_context_limit(
                            tc_name,
                            user_message,
                            profile,
                            compact_resource_tools_enabled=compact_resource_tools_enabled,
                        )
                        tool_result = tool_result or ""
                        model_tool_result = tool_result
                        if tc_name == "create_slice":
                            model_tool_result = (
                                f"{tool_result}\n\n"
                                f"{_build_create_slice_guidance(tc_args, user_message, messages)}"
                            )
                        trimmed_result = (
                            model_tool_result[:tool_max]
                            if len(model_tool_result) > tool_max
                            else model_tool_result
                        )
                        if model_api_type == "responses":
                            conversation.append({
                                "type": "function_call_output",
                                "call_id": tc_id,
                                "output": trimmed_result,
                            })
                        else:
                            conversation.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": trimmed_result,
                            })
                        _persist_conversation()
                        executed_tool_names.append(tc_name)
                        executed_round_tool_calls += 1
                        if progress_stop:
                            tool_loop_stop = progress_stop
                            break

                    tool_round += 1
                    _tool_call_count += executed_round_tool_calls

                    if tool_loop_stop:
                        if tool_loop_stop.get("reason") == "still_running":
                            stop_msg = (
                                "\n\n[The run is still in progress — this is normal "
                                "for a long weave, and it is still going. Stopped "
                                "polling for now; ask again in a few minutes to see "
                                "new output.]\n"
                            )
                        else:
                            stop_msg = (
                                "\n\n[Stopped the tool loop because the model repeated "
                                f"`{tool_loop_stop.get('tool')}` with the same arguments "
                                f"{tool_loop_stop.get('repeat_count')} times and the tool "
                                "result did not change. Summarize the last result or "
                                "adjust the request before continuing.]\n"
                            )
                        stop_msg = _finalize_visible_text(stop_msg)
                        yield f"data: {json.dumps({'content': stop_msg})}\n\n"
                        yield f"data: {json.dumps({'tool_loop_stopped': tool_loop_stop})}\n\n"
                        yield f"data: {json.dumps({'usage': _usage_payload()})}\n\n"
                        _persist_conversation(stop_msg)
                        yield "data: [DONE]\n\n"
                        return

                    # Break out if too many errors: three in a row, or eight in
                    # the turn (a model alternating one failure per round).
                    if consecutive_errors >= 3 or total_tool_errors >= _MAX_TOOL_ERRORS_PER_TURN:
                        err_break_msg = "\n\n[Multiple tool calls failed. Please try a different approach.]\n"
                        yield f"data: {json.dumps({'content': err_break_msg})}\n\n"
                        break

                    continue

                # No tool calls — validate FABRIC query final answer before returning.
                final_text = (msg.get("content") or "").strip()
                pending_background_jobs = _pending_background_submit_jobs(executed_tool_outputs)
                if (
                    background_job_poll_retry_count < 3
                    and pending_background_jobs
                    and not explicit_agent_controls_context
                    and not tools_disabled
                    and profile.get("supports_tools", True)
                ):
                    background_job_poll_retry_count += 1
                    retry_prompt = _build_background_job_poll_prompt(pending_background_jobs)
                    if model_api_type == "responses":
                        if final_text:
                            conversation.append({
                                "type": "message",
                                "role": "assistant",
                                "content": final_text,
                            })
                        conversation.append({
                            "type": "message",
                            "role": "user",
                            "content": retry_prompt,
                        })
                    else:
                        if final_text:
                            conversation.append({"role": "assistant", "content": final_text})
                        conversation.append({"role": "user", "content": retry_prompt})
                    logger.info(
                        "Retrying final answer to poll pending background jobs: %s",
                        ", ".join(job["job_id"] for job in pending_background_jobs),
                    )
                    continue
                draft_submission_candidates = _draft_submission_retry_candidates(
                    messages,
                    executed_tool_outputs,
                )
                if (
                    draft_submission_retry_count < 1
                    and draft_submission_candidates
                    and "submit_slice" not in executed_tool_names
                    and _conversation_authorizes_provisioning(messages)
                    and not explicit_agent_controls_context
                    and not tools_disabled
                    and profile.get("supports_tools", True)
                ):
                    draft_submission_retry_count = 1
                    retry_prompt = _build_draft_submission_retry_prompt(
                        draft_submission_candidates,
                        user_message,
                    )
                    if model_api_type == "responses":
                        if final_text:
                            conversation.append({
                                "type": "message",
                                "role": "assistant",
                                "content": final_text,
                            })
                        conversation.append({
                            "type": "message",
                            "role": "user",
                            "content": retry_prompt,
                        })
                    else:
                        if final_text:
                            conversation.append({"role": "assistant", "content": final_text})
                        conversation.append({"role": "user", "content": retry_prompt})
                    logger.info(
                        "Retrying authorized draft-only answer to force submit/wait for %s",
                        ", ".join(draft_submission_candidates),
                    )
                    continue
                validation_scope = _current_fabric_query_validation_scope()
                validation_reasons = (
                    _validate_fabric_query_final_answer(
                        final_text,
                        user_message,
                        executed_tool_names,
                        executed_tool_outputs,
                    )
                    if validation_scope else []
                )
                if validation_reasons:
                    logger.info("Retrying incomplete FABRIC query answer: %s", "; ".join(validation_reasons))
                    final_answer_retry_count = 1
                    expected_terms = _retry_expected_terms(executed_tool_outputs, user_message)
                    final_answer_best_effort = bool(
                        strict_fabric_query_contract_enabled
                        and "empty final answer" in validation_reasons
                    )
                    retry_prompt = _build_fabric_query_retry_prompt(
                        validation_reasons,
                        expected_terms,
                        best_effort_without_contract=final_answer_best_effort,
                    )
                    retry_conversation = list(conversation)
                    if model_api_type == "responses":
                        if final_text:
                            retry_conversation.append({
                                "type": "message",
                                "role": "assistant",
                                "content": final_text,
                            })
                        retry_conversation.append({
                            "type": "message",
                            "role": "user",
                            "content": retry_prompt,
                        })
                        retry_body = _build_responses_body(
                            model,
                            retry_conversation,
                            profile,
                            tools_for_model,
                            tools_disabled=True,
                            temperature_disabled=temperature_disabled,
                            reasoning_controls_disabled=reasoning_controls_disabled,
                        )
                        retry_endpoint = f"{server_url}/v1/responses"
                    else:
                        if final_text:
                            retry_conversation.append({"role": "assistant", "content": final_text})
                        retry_conversation.append({"role": "user", "content": retry_prompt})
                        retry_body = {
                            "model": model,
                            "messages": retry_conversation,
                            "max_tokens": profile["max_output"],
                        }
                        if not temperature_disabled:
                            retry_body["temperature"] = profile["temperature"]
                        if profile.get("top_p") is not None:
                            retry_body["top_p"] = profile["top_p"]
                        _apply_reasoning_controls(
                            retry_body,
                            profile,
                            model_api_type,
                            disabled=reasoning_controls_disabled,
                        )
                        retry_endpoint = f"{server_url}/v1/chat/completions"

                    retry_resp, _retries = await _post_llm_json_with_retries(
                        retry_endpoint,
                        {
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        {**retry_body, "stream": False},
                        timeout=300.0,
                    )
                    provider_retry_count += _retries
                    if retry_resp.status_code == 200:
                        if model_api_type == "responses":
                            retry_result = retry_resp.json()
                            retry_text, _retry_tool_calls = _parse_responses_output(
                                retry_result.get("output", [])
                            )
                        else:
                            retry_result = retry_resp.json()
                            retry_choices = retry_result.get("choices") or [{}]
                            retry_msg = (retry_choices[0] if retry_choices else {}).get("message", {})
                            retry_text = retry_msg.get("content") or ""
                        retry_text = retry_text.strip()
                        retry_reasons = _validate_fabric_query_final_answer(
                            retry_text,
                            user_message,
                            executed_tool_names,
                            executed_tool_outputs,
                            require_final_answer_marker=not final_answer_best_effort,
                        )
                        if retry_text:
                            final_text = retry_text
                        if retry_reasons:
                            incomplete_response_after_retry = True
                            logger.info(
                                "FABRIC query answer still incomplete after retry: %s",
                                "; ".join(retry_reasons),
                            )
                    else:
                        incomplete_response_after_retry = True
                        logger.info(
                            "FABRIC query retry failed with status %s: %s",
                            retry_resp.status_code,
                            retry_resp.text[:200],
                        )

                    if final_text:
                        if incomplete_response_after_retry:
                            completion_block = _host_threshold_completion_block(
                                executed_tool_outputs,
                                user_message,
                            )
                            if completion_block and completion_block not in final_text:
                                final_text = final_text.rstrip() + "\n\n" + completion_block
                                host_threshold_completion_applied = True
                                post_completion_reasons = _validate_fabric_query_final_answer(
                                    final_text,
                                    user_message,
                                    executed_tool_names,
                                    executed_tool_outputs,
                                    require_final_answer_marker=not final_answer_best_effort,
                                )
                                if not post_completion_reasons:
                                    incomplete_response_after_retry = False
                        final_text, _guard_applied, _evidence_appended = _apply_verification_evidence_guard(
                            final_text,
                            executed_tool_outputs,
                        )
                        verification_evidence_guard_applied = (
                            verification_evidence_guard_applied or _guard_applied
                        )
                        verification_evidence_appended = (
                            verification_evidence_appended or _evidence_appended
                        )
                        final_text = _finalize_visible_text(final_text)
                        for start in range(0, len(final_text), 200):
                            yield f"data: {json.dumps({'content': final_text[start:start + 200]})}\n\n"
                        elapsed_ms = int((_time.time() - _start_time) * 1000)
                        conv_tokens = estimate_conversation_tokens(conversation)
                        usage_data = {
                            "tokens": conv_tokens,
                            "tool_calls": _tool_call_count,
                            "duration_ms": elapsed_ms,
                            "generation_config_applied": _current_generation_config(),
                            "generation_config_defaults_applied": generation_config_defaults_applied,
                            "generation_config_adjustments": generation_config_adjustments,
                            "final_answer_retry_count": final_answer_retry_count,
                            "incomplete_response_after_retry": incomplete_response_after_retry,
                            "final_answer_best_effort": final_answer_best_effort,
                            "host_threshold_completion_applied": host_threshold_completion_applied,
                            "zero_visible_output_retry_count": zero_visible_output_retry_count,
                            "verification_evidence_guard_applied": verification_evidence_guard_applied,
                            "verification_evidence_appended": verification_evidence_appended,
                            "empty_visible_final_retry_count": empty_visible_final_retry_count,
                            "empty_visible_synthesized_answer": empty_visible_synthesized_answer,
                            "empty_tool_call_placeholder_count": empty_tool_call_placeholder_count,
                            "draft_submission_retry_count": draft_submission_retry_count,
                            "provider_retry_count": provider_retry_count,
                            **_context_usage_metadata(),
                        }
                        yield f"data: {json.dumps({'usage': usage_data})}\n\n"
                        _persist_conversation(final_text)
                        yield "data: [DONE]\n\n"
                        return
                    if final_answer_retry_count:
                        incomplete_response_after_retry = True
                        final_text = _finalize_visible_text(final_text)
                        if final_text:
                            for start in range(0, len(final_text), 200):
                                yield f"data: {json.dumps({'content': final_text[start:start + 200]})}\n\n"
                        elapsed_ms = int((_time.time() - _start_time) * 1000)
                        conv_tokens = estimate_conversation_tokens(conversation)
                        usage_data = {
                            "tokens": conv_tokens,
                            "tool_calls": _tool_call_count,
                            "duration_ms": elapsed_ms,
                            "generation_config_applied": _current_generation_config(),
                            "generation_config_defaults_applied": generation_config_defaults_applied,
                            "generation_config_adjustments": generation_config_adjustments,
                            "final_answer_retry_count": final_answer_retry_count,
                            "incomplete_response_after_retry": incomplete_response_after_retry,
                            "final_answer_best_effort": final_answer_best_effort,
                            "host_threshold_completion_applied": host_threshold_completion_applied,
                            "zero_visible_output_retry_count": zero_visible_output_retry_count,
                            "verification_evidence_guard_applied": verification_evidence_guard_applied,
                            "verification_evidence_appended": verification_evidence_appended,
                            "empty_visible_final_retry_count": empty_visible_final_retry_count,
                            "empty_visible_synthesized_answer": empty_visible_synthesized_answer,
                            "empty_tool_call_placeholder_count": empty_tool_call_placeholder_count,
                            "draft_submission_retry_count": draft_submission_retry_count,
                            "provider_retry_count": provider_retry_count,
                            **_context_usage_metadata(),
                        }
                        yield f"data: {json.dumps({'usage': usage_data})}\n\n"
                        _persist_conversation(final_text)
                        yield "data: [DONE]\n\n"
                        return

                if validation_scope and final_text:
                    final_text, _guard_applied, _evidence_appended = _apply_verification_evidence_guard(
                        final_text,
                        executed_tool_outputs,
                    )
                    verification_evidence_guard_applied = (
                        verification_evidence_guard_applied or _guard_applied
                    )
                    verification_evidence_appended = (
                        verification_evidence_appended or _evidence_appended
                    )
                    final_text = _finalize_visible_text(final_text)
                    for start in range(0, len(final_text), 200):
                        yield f"data: {json.dumps({'content': final_text[start:start + 200]})}\n\n"
                    elapsed_ms = int((_time.time() - _start_time) * 1000)
                    conv_tokens = estimate_conversation_tokens(conversation)
                    usage_data = {
                        "tokens": conv_tokens,
                        "tool_calls": _tool_call_count,
                        "duration_ms": elapsed_ms,
                        "generation_config_applied": _current_generation_config(),
                        "generation_config_defaults_applied": generation_config_defaults_applied,
                        "generation_config_adjustments": generation_config_adjustments,
                        "final_answer_retry_count": final_answer_retry_count,
                        "incomplete_response_after_retry": incomplete_response_after_retry,
                        "final_answer_best_effort": final_answer_best_effort,
                        "host_threshold_completion_applied": host_threshold_completion_applied,
                        "zero_visible_output_retry_count": zero_visible_output_retry_count,
                        "verification_evidence_guard_applied": verification_evidence_guard_applied,
                        "verification_evidence_appended": verification_evidence_appended,
                        "empty_visible_final_retry_count": empty_visible_final_retry_count,
                        "empty_visible_synthesized_answer": empty_visible_synthesized_answer,
                        "empty_tool_call_placeholder_count": empty_tool_call_placeholder_count,
                        "draft_submission_retry_count": draft_submission_retry_count,
                        "provider_retry_count": provider_retry_count,
                        **_context_usage_metadata(),
                    }
                    yield f"data: {json.dumps({'usage': usage_data})}\n\n"
                    _persist_conversation(final_text)
                    yield "data: [DONE]\n\n"
                    return

                # No retry needed — stream the final text response
                guarded_final_text, _guard_applied, _evidence_appended = _apply_verification_evidence_guard(
                    final_text,
                    executed_tool_outputs,
                )
                if _guard_applied:
                    verification_evidence_guard_applied = True
                    verification_evidence_appended = (
                        verification_evidence_appended or _evidence_appended
                    )
                    guarded_final_text = _finalize_visible_text(guarded_final_text)
                    for start in range(0, len(guarded_final_text), 200):
                        yield f"data: {json.dumps({'content': guarded_final_text[start:start + 200]})}\n\n"
                    elapsed_ms = int((_time.time() - _start_time) * 1000)
                    conv_tokens = estimate_conversation_tokens(conversation)
                    usage_data = {
                        "tokens": conv_tokens,
                        "tool_calls": _tool_call_count,
                        "duration_ms": elapsed_ms,
                        "generation_config_applied": _current_generation_config(),
                        "generation_config_defaults_applied": generation_config_defaults_applied,
                        "generation_config_adjustments": generation_config_adjustments,
                        "final_answer_retry_count": final_answer_retry_count,
                        "incomplete_response_after_retry": incomplete_response_after_retry,
                        "final_answer_best_effort": final_answer_best_effort,
                        "host_threshold_completion_applied": host_threshold_completion_applied,
                        "zero_visible_output_retry_count": zero_visible_output_retry_count,
                        "verification_evidence_guard_applied": verification_evidence_guard_applied,
                        "verification_evidence_appended": verification_evidence_appended,
                        "empty_visible_final_retry_count": empty_visible_final_retry_count,
                        "empty_visible_synthesized_answer": empty_visible_synthesized_answer,
                        "empty_tool_call_placeholder_count": empty_tool_call_placeholder_count,
                        "draft_submission_retry_count": draft_submission_retry_count,
                        "provider_retry_count": provider_retry_count,
                        **_context_usage_metadata(),
                    }
                    yield f"data: {json.dumps({'usage': usage_data})}\n\n"
                    _persist_conversation(guarded_final_text)
                    yield "data: [DONE]\n\n"
                    return

                # Stream the validated final text in chunks. It used to re-run the
                # completion with stream=True "for smooth output": that doubled the
                # cost and latency of every final turn, the second answer could
                # differ from the one the guards had just checked, and it was
                # missing from the usage figures.
                streamed_final_text = final_text
                for start in range(0, len(final_text), 200):
                    if await request.is_disconnected():
                        break
                    if request_id and request_id in _cancelled_requests:
                        break
                    yield f"data: {json.dumps({'content': final_text[start:start + 200]})}\n\n"
                finalized_streamed_text = _finalize_visible_text(streamed_final_text)
                marker_suffix = finalized_streamed_text[len(streamed_final_text):]
                if marker_suffix:
                    for start in range(0, len(marker_suffix), 200):
                        yield f"data: {json.dumps({'content': marker_suffix[start:start + 200]})}\n\n"

                # C5: Emit usage stats
                elapsed_ms = int((_time.time() - _start_time) * 1000)
                conv_tokens = estimate_conversation_tokens(conversation)
                usage_data = {
                    "tokens": conv_tokens,
                    "tool_calls": _tool_call_count,
                    "duration_ms": elapsed_ms,
                    "generation_config_applied": _current_generation_config(),
                    "generation_config_defaults_applied": generation_config_defaults_applied,
                    "generation_config_adjustments": generation_config_adjustments,
                    "final_answer_retry_count": final_answer_retry_count,
                    "incomplete_response_after_retry": incomplete_response_after_retry,
                    "final_answer_best_effort": final_answer_best_effort,
                    "host_threshold_completion_applied": host_threshold_completion_applied,
                    "zero_visible_output_retry_count": zero_visible_output_retry_count,
                    "verification_evidence_guard_applied": verification_evidence_guard_applied,
                    "verification_evidence_appended": verification_evidence_appended,
                    "empty_visible_final_retry_count": empty_visible_final_retry_count,
                    "empty_visible_synthesized_answer": empty_visible_synthesized_answer,
                    "empty_tool_call_placeholder_count": empty_tool_call_placeholder_count,
                    "draft_submission_retry_count": draft_submission_retry_count,
                    "provider_retry_count": provider_retry_count,
                    **_context_usage_metadata(),
                }
                yield f"data: {json.dumps({'usage': usage_data})}\n\n"
                _persist_conversation(finalized_streamed_text)
                yield "data: [DONE]\n\n"
                return

            # Exhausted tool rounds — ask LLM to summarize progress for continuity
            # Append a system nudge so the LLM wraps up gracefully
            _nudge_msg = (
                "[System: Tool call limit reached. Please summarize what you've accomplished so far "
                "and what steps remain. The user can click 'Continue' to resume.]"
            )
            if model_api_type == "responses":
                conversation.append({"type": "message", "role": "user", "content": _nudge_msg})
            else:
                conversation.append({"role": "user", "content": _nudge_msg})
            # Make one final LLM call (without tools) to get a summary
            summary_parts: list[str] = []
            try:
                if model_api_type == "responses":
                    _sum_instructions, _sum_input = _build_responses_input(conversation)
                    summary_body = {
                        "model": model,
                        "input": _sum_input,
                        "max_output_tokens": min(profile["max_output"], 1024),
                        "stream": True,
                    }
                    if not temperature_disabled:
                        summary_body["temperature"] = profile["temperature"]
                    if profile.get("top_p") is not None:
                        summary_body["top_p"] = profile["top_p"]
                    if _sum_instructions:
                        summary_body["instructions"] = _sum_instructions
                    _apply_reasoning_controls(
                        summary_body,
                        profile,
                        model_api_type,
                        disabled=reasoning_controls_disabled,
                    )
                    _sum_endpoint = f"{server_url}/v1/responses"
                else:
                    summary_body = {
                        "model": model,
                        "messages": conversation,
                        "max_tokens": min(profile["max_output"], 1024),
                        "stream": True,
                    }
                    if not temperature_disabled:
                        summary_body["temperature"] = profile["temperature"]
                    if profile.get("top_p") is not None:
                        summary_body["top_p"] = profile["top_p"]
                    _apply_reasoning_controls(
                        summary_body,
                        profile,
                        model_api_type,
                        disabled=reasoning_controls_disabled,
                    )
                    _sum_endpoint = f"{server_url}/v1/chat/completions"
                async with ai_client.stream(
                    "POST",
                    _sum_endpoint,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=summary_body,
                ) as summary_resp:
                    if summary_resp.status_code == 200:
                        async for line in summary_resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                if model_api_type == "responses":
                                    if chunk.get("type") == "response.output_text.delta":
                                        content = chunk.get("delta", "")
                                        if content:
                                            summary_parts.append(content)
                                            yield f"data: {json.dumps({'content': content})}\n\n"
                                    elif chunk.get("type") in ("response.completed", "response.done"):
                                        break
                                else:
                                    delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                                    content = delta.get("content")
                                    if content:
                                        summary_parts.append(content)
                                        yield f"data: {json.dumps({'content': content})}\n\n"
                            except json.JSONDecodeError:
                                continue
            except Exception:
                pass

            summary_text = "".join(summary_parts)
            finalized_summary_text = _finalize_visible_text(summary_text)
            marker_suffix = finalized_summary_text[len(summary_text):]
            if marker_suffix:
                for start in range(0, len(marker_suffix), 200):
                    yield f"data: {json.dumps({'content': marker_suffix[start:start + 200]})}\n\n"

            # Emit tool_limit_reached so frontend can show Continue button
            yield f"data: {json.dumps({'tool_limit_reached': True, 'tool_rounds_used': tool_round})}\n\n"
            _persist_conversation(finalized_summary_text)
            yield "data: [DONE]\n\n"

        except httpx.ReadError as e:
            # The provider closed the connection mid-read. Ending silently
            # looked like an empty answer with nothing logged.
            logger.warning("Chat stream: provider connection dropped mid-read: %s", e)
            yield f"data: {json.dumps({'error': 'The model connection dropped before the answer finished. Please retry.', 'error_type': 'transient', 'retryable': True})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.exception("Chat stream error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            if request_id:
                _cancelled_requests.discard(request_id)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/api/ai/chat/stop")
async def chat_stop(request: Request):
    body = await request.json()
    request_id = body.get("request_id", "")
    if request_id:
        _cancelled_requests.add(request_id)
        return {"status": "stopped"}
    return {"status": "not_found"}
