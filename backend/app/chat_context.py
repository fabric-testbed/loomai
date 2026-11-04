"""Per-model context window management for LoomAI assistant.

Provides model profiles, token estimation, conversation trimming,
system prompt variants, and tool schema filtering so the chat stays
within each model's context limits.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def estimate_tokens(text: str | None) -> int:
    """Rough token count (~4 chars per token for English/code)."""
    if not text:
        return 1
    return max(1, len(text) // 4)


def estimate_message_tokens(msg: dict) -> int:
    """Estimate tokens in a single chat message (content + role overhead)."""
    content = msg.get("content") or msg.get("output") or ""
    # Tool call messages have function arguments
    tool_calls = msg.get("tool_calls") or []
    extra = sum(
        len(tc.get("function", {}).get("arguments") or "")
        for tc in tool_calls
    )
    if msg.get("type") == "function_call":
        extra += len(msg.get("arguments") or "")
    return estimate_tokens(content) + estimate_tokens(str(extra)) + 4  # role overhead


def estimate_conversation_tokens(messages: list[dict]) -> int:
    """Estimate total tokens in a conversation."""
    return sum(estimate_message_tokens(m) for m in messages)


# ---------------------------------------------------------------------------
# Model profiles
# ---------------------------------------------------------------------------

# Profile tiers — keyed by size category.
#
# max_output is a RESERVATION of output-token headroom AND the API max_tokens
# cap. It must be big enough for the model to complete a realistic file write
# in a single tool call, and small enough to leave conversation budget on
# small-context models. Empirically validated against qwen3-coder-30b: a full
# 22KB Python script generates in ~4,440 completion tokens, ~113s wall-clock,
# with finish_reason=stop. Models can go bigger via max_output_override in
# MODEL_OVERRIDES for code-specialists with known-good long-output behavior.
#
# Budget math for standard tier on a 32K-context model (pessimistic case):
#   budget = 32768 * 0.70 - 8000 system - 6144 output = 8793 conversation tokens
# Still workable. For 256K-context models (typical qwen3-coder), budget is
# ~235K — headroom is irrelevant.
PROFILE_TIERS = {
    "compact": {
        "context_window": 8192,
        "max_output": 1024,
        "system_prompt": "compact",
        "tool_result_max": 200,
        "summarize_at": 0.40,
        "max_tools": 10,
        "temperature": 0.5,
        "supports_tools": True,
    },
    "standard": {
        "context_window": 32768,
        # Bumped 2048 → 6144: covers ~95% of realistic single-file writes
        # (full lifecycle scripts up to ~24KB). Above this, code-specialist
        # models should use a per-model max_output_override.
        "max_output": 6144,
        "system_prompt": "standard",
        # Standard-tier operational workflows need full slice/tool evidence
        # (interfaces, command output, weave logs). 2000 chars cut off worked
        # examples and multi-node topology details.
        "tool_result_max": 6000,
        "summarize_at": 0.70,
        # Keep the full CORE_TOOLS set available for standard-tier models.
        # The assistant quality evals cover this so roadmap-critical tools
        # (create_weave, search_examples, Chameleon, SPHERE, Federated) do not
        # silently fall out of the filtered schema as the tool list grows.
        # Keep this == len(CORE_TOOLS); bump both together when core tools grow.
        "max_tools": 61,
        "temperature": 0.5,
        "supports_tools": True,
    },
    "large": {
        "context_window": 131072,
        # Bumped 4096 → 12288: large-tier models have 131K+ context so the
        # reservation is immaterial (<10%). Handles full Jupyter notebooks
        # with analysis + plots in one write call.
        "max_output": 12288,
        "system_prompt": "full",
        "tool_result_max": 6000,
        "summarize_at": 0.85,
        # Also == len(CORE_TOOLS): large-tier models have the most headroom,
        # so they must never expose fewer core tools than standard.
        "max_tools": 61,
        "temperature": 0.5,
        "supports_tools": True,
    },
}

# Per-model overrides (model name substring → overrides)
# The "tier" controls CAPABILITY settings (prompt variant, max_tools, max_output).
# The discovered context_length controls CONTEXT BUDGET (context_window, summarize_at).
# These are separate concerns: a 30B model with 256K context still works best
# with a focused "standard" prompt and 25 tools, not the full 37-tool "large" prompt.
#
# Optional per-model keys:
#  - ``max_output_override``: absolute token cap that replaces the tier default
#    AFTER any reasoning scaling. Use for code-specialist models with large
#    context windows that need to write substantial files in a single tool call.
#    Empirically validated: qwen3-coder-30b at 12288 generates 22KB in ~113s.
#  - ``is_reasoning`` / ``max_output_scale``: for models with a separate
#    reasoning_content field (NVIDIA Nemotron-style). The completion budget
#    is multiplied by the scale to leave room for reasoning tokens. Typical
#    overhead: 2-3x. Override is applied AFTER scaling so override always wins.
MODEL_OVERRIDES: dict[str, dict] = {
    # Qwen3 Coder family — code specialists, validated for long output
    "qwen3-coder-30b": {
        "temperature": 0.3,
        "tier": "standard",
        "max_output_override": 12288,  # ~48KB per file write, ~113s wall-clock
    },
    "qwen3-coder-8b": {
        "temperature": 0.3,
        "tier": "compact",
        "max_output_override": 6144,   # 8K-context model; this eats most of it, use sparingly
    },
    "qwen3-coder": {
        "temperature": 0.3,
        "tier": "standard",
        "max_output_override": 12288,
    },
    # Qwen3 general family
    "qwen3-30b": {"tier": "standard"},
    "qwen3-8b": {"tier": "compact"},
    "qwen3-small": {"tier": "compact"},
    "qwen3": {"tier": "standard"},
    "qwen3-27b": {"tier": "standard"},
    # Other code specialists
    "deepseek-coder": {
        "temperature": 0.2,
        "tier": "standard",
        "max_output_override": 12288,
    },
    # Claude (closed-source, very good at long output)
    "claude-3-5-sonnet": {
        "tier": "large",
        "temperature": 0.5,
        "max_output_override": 16384,
    },
    "claude-haiku": {"tier": "standard", "temperature": 0.5},
    "gpt-4": {"tier": "large"},
    "gpt-3.5": {"tier": "standard"},
    # FABRIC AI floor models: keep capability tier standard even when the
    # advertised context window is 128K/262K. The context budget is handled
    # separately from this capability tier.
    "gpt-oss-20b": {"tier": "standard"},
    "gpt-oss": {"tier": "standard"},
    "gemma-4-27b": {"tier": "standard"},
    "mixtral": {"tier": "standard"},
    "llama": {"tier": "standard"},
    "gemma": {"tier": "compact"},
    "olmo": {"tier": "compact"},
    "kimi": {"tier": "standard"},
    "minimax": {"tier": "standard"},
    "glm-5": {
        "tier": "standard",
        "is_reasoning": True,
        "max_output_scale": 3.0,
    },
    "glm": {"tier": "standard"},
    # Reasoning model — separate reasoning_content field, ~2-3x completion
    # overhead, strong on multi-step design questions, noticeably slower than
    # qwen3-coder. Standard tier + focused prompt works better than "large"
    # because the model is trained to reason from concise context.
    "nemotron-nano-30b": {
        "tier": "standard",
        "temperature": 0.3,
        "is_reasoning": True,
        "max_output_scale": 2.5,
    },
    "nemotron": {
        "tier": "standard",
        "temperature": 0.3,
        "is_reasoning": True,
        "max_output_scale": 2.5,
    },
}


def _detect_tier(context_length: Optional[int]) -> str:
    """Detect capability tier from context window size (fallback only)."""
    if context_length is None:
        return "standard"  # safe default
    if context_length <= 12000:
        return "compact"
    if context_length <= 65000:
        return "standard"
    return "large"


def get_model_profile(model_name: str, context_length: Optional[int] = None) -> dict:
    """Get a complete profile for a model.

    Two-axis design:
    - CAPABILITY (tier): controls system_prompt variant, max_tools, max_output,
      tool_result_max. Comes from MODEL_OVERRIDES or _detect_tier() fallback.
    - CONTEXT BUDGET: controls context_window and summarize_at. Comes from
      discovered context_length when available, otherwise from tier defaults.

    A 30B model with 256K context gets standard-tier capabilities (focused prompt,
    25 tools, 4096 max_output) but a 256K context budget for conversation.
    """
    # Find tier + overrides from MODEL_OVERRIDES (substring match)
    tier = None
    overrides: dict = {}
    model_lower = model_name.lower()
    for pattern, ovr in MODEL_OVERRIDES.items():
        if pattern.lower() in model_lower:
            tier = ovr.get("tier")
            overrides = {k: v for k, v in ovr.items() if k != "tier"}
            break

    # If no tier from overrides, auto-detect from context_length
    if tier is None:
        tier = _detect_tier(context_length)

    # Start with capability settings from the tier
    profile = dict(PROFILE_TIERS[tier])
    profile["tier"] = tier

    # Override context_window with actual discovered context_length
    if context_length and context_length > 0:
        profile["context_window"] = context_length
        # Scale summarize_at based on actual context size (bigger context = trim later)
        if context_length > 200000:
            profile["summarize_at"] = 0.90
        elif context_length > 65000:
            profile["summarize_at"] = 0.85
        elif context_length > 32000:
            profile["summarize_at"] = 0.75

    # Apply per-model overrides (temperature, is_reasoning, max_output_override, etc.)
    profile.update(overrides)

    # Reasoning models burn completion tokens on internal thinking. Scale
    # max_output up so there's still room for a substantive visible reply
    # after reasoning overhead. Only applied when is_reasoning is set AND
    # max_output_scale wasn't itself overridden by the caller.
    if profile.get("is_reasoning"):
        scale = profile.get("max_output_scale", 2.5)
        try:
            profile["max_output"] = max(1024, int(profile["max_output"] * float(scale)))
        except (TypeError, ValueError):
            pass

    # max_output_override wins unconditionally — takes precedence over tier
    # defaults AND reasoning scaling. Used for code-specialist models that
    # need to write long files in a single tool call (e.g. qwen3-coder-30b
    # at 12288 tokens handles 48KB file writes in one shot).
    override = profile.get("max_output_override")
    if override is not None:
        try:
            override_val = int(override)
            if override_val > 0:
                profile["max_output"] = override_val
        except (TypeError, ValueError):
            pass

    profile["model"] = model_name
    return profile


# ---------------------------------------------------------------------------
# System prompt variants
# ---------------------------------------------------------------------------

_APP_ROOT = os.path.dirname(os.path.dirname(__file__))
_FABRIC_AI_PATH = os.path.join(_APP_ROOT, "ai-tools", "shared", "FABRIC_AI.md")

_prompt_cache: dict[str, str] = {}


def _load_full_prompt() -> str:
    """Load the full FABRIC_AI.md content."""
    if "full" not in _prompt_cache:
        try:
            with open(_FABRIC_AI_PATH) as f:
                _prompt_cache["full"] = f.read()
        except FileNotFoundError:
            _prompt_cache["full"] = "You are a helpful FABRIC testbed assistant."
    return _prompt_cache["full"]


def _build_compact_prompt() -> str:
    """Build a compact ~3K token prompt from full FABRIC_AI.md.

    Keeps: workflow, tool names, common request patterns, quick intent guide.
    Strips: full site list, Python examples, component details, verbose docs.
    """
    if "compact" in _prompt_cache:
        return _prompt_cache["compact"]

    full = _load_full_prompt()

    # Extract key sections by heading
    sections_to_keep = [
        "# FABRIC AI Coding Assistant",
        "## Workflow",
        "## Tools",
        "## Common Request Patterns",
        "## Slice Lifecycle",
    ]

    sections_to_strip = [
        "## Common FABlib Operations",
        "## FABRIC Sites Directory",
        "## VM Images",
        "## Component Models Reference",
        "## Network Types Deep Dive",
        "## Weave Lifecycle & Graceful Shutdown",
    ]

    lines = full.split("\n")
    result: list[str] = []
    include = True
    in_code_block = False
    code_block_lines = 0

    for line in lines:
        # Track code blocks — limit to 20 lines each in compact mode.
        # Standard/full prompts do not apply this cap.
        if line.strip().startswith("```"):
            if in_code_block:
                in_code_block = False
                if include:
                    result.append(line)
                continue
            else:
                in_code_block = True
                code_block_lines = 0
                if include:
                    result.append(line)
                continue

        if in_code_block:
            code_block_lines += 1
            if code_block_lines <= 20 and include:
                result.append(line)
            continue

        # Check section headers
        if line.startswith("#"):
            # Check if this is a section to strip
            stripped = False
            for strip_section in sections_to_strip:
                if line.strip().startswith(strip_section.lstrip("#").strip()):
                    include = False
                    stripped = True
                    break
            if not stripped:
                # Check if this starts a new section we should keep
                for keep_section in sections_to_keep:
                    if line.strip().startswith(keep_section.lstrip("#").strip()):
                        include = True
                        break
                # Any other ## section after the keep sections: include briefly
                if line.startswith("## ") and not any(
                    line.strip().startswith(s.lstrip("#").strip()) for s in sections_to_keep
                ):
                    include = True  # Include header, content will be brief

        if include:
            result.append(line)

    compact = "\n".join(result)
    # Final trim — if still too long, truncate
    max_chars = 12000  # ~3K tokens
    if len(compact) > max_chars:
        compact = compact[:max_chars] + "\n\n(System prompt truncated for context window.)"

    _prompt_cache["compact"] = compact
    return compact


def _build_standard_prompt() -> str:
    """Build a standard ~4K token prompt. Strips verbose sections carried by agents."""
    if "standard" in _prompt_cache:
        return _prompt_cache["standard"]

    full = _load_full_prompt()

    # Skip sections that are carried by on-demand agents instead.
    # These are expensive reference sections that are only needed situationally.
    _SKIP_SECTIONS = {
        "Backend REST API",
        "Persistent Sessions with tmux",
        "Web App Tunnels",
        "End-to-End Deployment Workflow",
        "Error Recovery",
        "FABlib Python API",
        "Working Environment",
        "LoomAI WebUI Features",
        "Artifact Terminology",
        "Artifact Tags & Descriptions",
        "FABRIC Authentication & Token",
        "LLM Providers",
        "What is FABRIC?",
        "FABRIC Sites",
        "Available VM Images",
        "Component Models",
        "Network Types",
        "Topology Definition",
        "tools/ Scripts (Per-VM Setup)",
        "vm-template.json",
        "recipe.json",
        "Basic Slice Creation",
        "Adding Components",
        "Sub-Interfaces",
        "Modifying a Running Slice",
        "Resource Availability Queries",
        "Facility Ports",
        "Port Mirroring",
        "Persistent Storage",
        "CPU Pinning and NUMA",
        "Batch Operations",
        "Slice Information",
        "FABRIC Portal",
        "FABRIC Artifact Manager",
        "FABRIC Reports API",
        "FABRIC User Information Service",
        "Template Design",
        "Script Writing",
        "Resource Guidelines",
        "Common Patterns",
    }

    lines = full.split("\n")
    result: list[str] = []
    skip = False
    for line in lines:
        if line.startswith("## "):
            heading = line[3:].strip()
            # Check if any skip section matches the start of this heading
            skip = any(heading.startswith(s) for s in _SKIP_SECTIONS)
        if not skip:
            result.append(line)

    trimmed = "\n".join(result)

    # Final safety — if still too long, hard-trim
    max_chars = 16000  # ~4K tokens target
    if len(trimmed) > max_chars:
        cut = trimmed.rfind("\n## ", 0, max_chars)
        if cut > max_chars * 0.7:
            trimmed = trimmed[:cut]
        else:
            trimmed = trimmed[:max_chars]
        trimmed += "\n\n(Activate an agent for detailed reference — e.g. fablib-coder, cli-helper, troubleshooter.)"

    _prompt_cache["standard"] = trimmed
    return trimmed


def get_system_prompt(variant: str) -> str:
    """Get the system prompt for a given variant (compact/standard/full)."""
    if variant == "compact":
        return _build_compact_prompt()
    elif variant == "standard":
        return _build_standard_prompt()
    else:
        return _load_full_prompt()


# ---------------------------------------------------------------------------
# Conversation trimming
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Budget: 30% system prompt (+ tool schemas), 50% conversation, 20% tool results
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_SHARE = 0.30


def estimate_tool_schema_tokens(schemas: list[dict] | None) -> int:
    """Tokens the tool definitions cost on every request.

    They are sent with each call, so trim_conversation() charges them to the
    conversation budget (the standard tier's 61 schemas are ~9K tokens; the
    old budget ignored them).
    """
    if not schemas:
        return 0
    try:
        return estimate_tokens(json.dumps(schemas, separators=(",", ":")))
    except (TypeError, ValueError):
        return sum(estimate_tokens(str(schema)) for schema in schemas)


def system_prompt_budget(profile: dict, core_tokens: int = 0) -> int:
    """Max tokens the system prompt text may use: 30% of the window.

    The core prompt is the floor: on a compact model the compact prompt alone
    is already ~3K tokens of an 8K window, so the share is applied to the
    optional blocks (prefetched data, RAG context, skills) rather than to the
    instructions the assistant cannot work without.
    """
    window = int(profile.get("context_window") or 0)
    # Headroom above the core prompt for the session-state block and the
    # truncation markers, so fitting never nibbles at the core itself.
    return max(int(window * SYSTEM_PROMPT_SHARE), int(core_tokens or 0) + 400)


_TRUNCATION_MARK = "\n\n[... trimmed to fit the model's context window]"


def fit_system_parts(
    parts: list[str],
    max_tokens: int,
    protected: set[int] | None = None,
) -> tuple[list[str], list[int]]:
    """Shrink the system prompt's parts until they fit *max_tokens*.

    The largest unprotected part is truncated first (prefetched data, RAG
    context and skill files are the usual culprits), and it keeps a marker so
    the model knows the block is incomplete. Protected parts (the core prompt,
    the session-state block) are only truncated when nothing else is left.
    Returns the fitted parts and the indices that were truncated.
    """
    protected = set(protected or ())
    parts = list(parts)
    truncated: list[int] = []
    if max_tokens <= 0:
        max_tokens = 1

    def total() -> int:
        return sum(estimate_tokens(p) for p in parts)

    def shrink_one(candidates: list[int]) -> bool:
        if not candidates:
            return False
        idx = max(candidates, key=lambda i: estimate_tokens(parts[i]))
        over_tokens = total() - max_tokens
        if over_tokens <= 0:
            return False
        current = parts[idx]
        # Drop at least the overage (~4 chars per token) plus room for the marker.
        keep_chars = max(0, len(current) - over_tokens * 4 - len(_TRUNCATION_MARK))
        if keep_chars < 200:
            parts[idx] = _TRUNCATION_MARK.strip()
        else:
            parts[idx] = current[:keep_chars].rstrip() + _TRUNCATION_MARK
        if idx not in truncated:
            truncated.append(idx)
        return True

    while total() > max_tokens:
        unprotected = [i for i in range(len(parts)) if i not in protected and estimate_tokens(parts[i]) > 60]
        if shrink_one(unprotected):
            continue
        guarded = [i for i in range(len(parts)) if i in protected and estimate_tokens(parts[i]) > 60]
        if not shrink_one(guarded):
            break
    if truncated:
        logger.warning(
            "System prompt over its %d-token share; truncated parts %s", max_tokens, truncated,
        )
    return parts, truncated


class TrimResult:
    """Result of conversation trimming with context status flags."""
    __slots__ = (
        "messages",
        "near_full",
        "was_trimmed",
        "was_compacted",
        "compacted_from_tokens",
        "compacted_to_tokens",
    )

    def __init__(
        self,
        messages: list[dict],
        near_full: bool = False,
        was_trimmed: bool = False,
        was_compacted: bool = False,
        compacted_from_tokens: int = 0,
        compacted_to_tokens: int = 0,
    ):
        self.messages = messages
        self.near_full = near_full
        self.was_trimmed = was_trimmed
        self.was_compacted = was_compacted
        self.compacted_from_tokens = compacted_from_tokens
        self.compacted_to_tokens = compacted_to_tokens


def _is_user_message(msg: dict) -> bool:
    return msg.get("role") == "user"


def _message_role(msg: dict) -> str:
    return str(msg.get("role") or "")


def _is_instruction_message(msg: dict) -> bool:
    role = _message_role(msg)
    if role in {"system", "developer"}:
        return True
    return msg.get("type") == "message" and role in {"system", "developer"}


def _message_text(msg: dict) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    output = msg.get("output")
    if isinstance(output, str):
        return output
    return ""


def _one_line(text: str, max_chars: int = 180) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _tool_call_names(msg: dict) -> list[str]:
    if msg.get("type") == "function_call":
        name = str(msg.get("name") or "").strip()
        return [name] if name else []
    names: list[str] = []
    for call in msg.get("tool_calls") or []:
        if isinstance(call, dict):
            name = str(call.get("function", {}).get("name") or "").strip()
            if name:
                names.append(name)
    return names


def _tool_output_call_id(msg: dict) -> str:
    if msg.get("role") == "tool":
        return str(msg.get("tool_call_id") or "")
    if msg.get("type") == "function_call_output":
        return str(msg.get("call_id") or "")
    return ""


def _tool_call_ids(msg: dict) -> set[str]:
    if msg.get("type") == "function_call":
        call_id = str(msg.get("call_id") or msg.get("id") or "")
        return {call_id} if call_id else set()
    ids: set[str] = set()
    for call in msg.get("tool_calls") or []:
        if isinstance(call, dict):
            call_id = str(call.get("id") or "")
            if call_id:
                ids.add(call_id)
    return ids


def _add_matching_tool_call_indices(messages: list[dict], keep_indices: set[int]) -> None:
    """Keep tool-call messages paired with any preserved tool outputs."""
    for index in list(keep_indices):
        if index < 0 or index >= len(messages):
            continue
        call_id = _tool_output_call_id(messages[index])
        if not call_id:
            continue
        for prior in range(index - 1, -1, -1):
            if call_id in _tool_call_ids(messages[prior]):
                keep_indices.add(prior)
                break


def _add_matching_tool_output_indices(messages: list[dict], keep_indices: set[int]) -> None:
    """Keep available tool outputs for any preserved tool-call message."""
    for index in list(keep_indices):
        if index < 0 or index >= len(messages):
            continue
        call_ids = _tool_call_ids(messages[index])
        if not call_ids:
            continue
        for later in range(index + 1, len(messages)):
            call_id = _tool_output_call_id(messages[later])
            if call_id in call_ids:
                keep_indices.add(later)
            elif call_id:
                continue
            elif _message_role(messages[later]) not in {"tool", ""}:
                break


def _latest_tool_output_indices(messages: list[dict], max_outputs: int) -> set[int]:
    if max_outputs <= 0:
        return set()
    indices: set[int] = set()
    found = 0
    for index in range(len(messages) - 1, -1, -1):
        if _tool_output_call_id(messages[index]):
            indices.add(index)
            found += 1
            if found >= max_outputs:
                break
    _add_matching_tool_call_indices(messages, indices)
    _add_matching_tool_output_indices(messages, indices)
    return indices


def _summarize_compacted_messages(messages: list[dict]) -> str:
    parts: list[str] = []
    for msg in messages:
        role = _message_role(msg)
        if msg.get("type") == "function_call":
            name = str(msg.get("name") or "tool")
            args = _one_line(str(msg.get("arguments") or ""), 160)
            parts.append(f"Tool requested: {name}({args})")
            continue
        if msg.get("type") == "function_call_output":
            output = _one_line(str(msg.get("output") or ""), 220)
            parts.append(f"Tool output: {output}")
            continue
        names = _tool_call_names(msg)
        if names:
            parts.append(f"Assistant requested tools: {', '.join(names)}")
            continue
        text = _one_line(_message_text(msg), 220)
        if not text:
            continue
        if role == "user":
            parts.append(f"User: {text}")
        elif role == "assistant":
            parts.append(f"Assistant: {text}")
        elif role == "tool":
            name = str(msg.get("name") or "tool")
            parts.append(f"Tool {name}: {text}")
        else:
            parts.append(text)
    if not parts:
        parts.append("Older turns were compacted; no user-visible facts were lost.")
    return "## Compacted prior progress\n" + "\n".join(f"- {part}" for part in parts[-24:])


def _state_preserving_compaction(
    messages: list[dict],
    system_tokens: int,
    profile: dict,
    conv_tokens: int,
) -> TrimResult | None:
    """Compact weak-model conversations while preserving current state and tools."""
    if not profile.get("context_compaction_enabled"):
        return None

    trigger_messages = int(profile.get("context_compaction_trigger_messages") or 0)
    trigger_tokens = int(profile.get("context_compaction_trigger_tokens") or 0)
    non_instruction_count = sum(1 for msg in messages if not _is_instruction_message(msg))
    should_compact = (
        bool(trigger_messages and non_instruction_count > trigger_messages)
        or bool(trigger_tokens and conv_tokens > trigger_tokens)
    )
    if not should_compact:
        return None

    keep_last = int(profile.get("context_compaction_keep_last_messages") or 10)
    keep_last = max(4, min(40, keep_last))
    keep_tool_outputs = int(profile.get("context_compaction_preserve_last_tool_outputs") or 3)
    keep_tool_outputs = max(0, min(10, keep_tool_outputs))

    keep_indices: set[int] = {
        index for index, msg in enumerate(messages) if _is_instruction_message(msg)
    }
    if keep_last:
        keep_indices.update(range(max(0, len(messages) - keep_last), len(messages)))

    latest_user = next(
        (index for index in range(len(messages) - 1, -1, -1) if _is_user_message(messages[index])),
        None,
    )
    if latest_user is not None:
        keep_indices.add(latest_user)

    keep_indices.update(_latest_tool_output_indices(messages, keep_tool_outputs))
    _add_matching_tool_call_indices(messages, keep_indices)
    _add_matching_tool_output_indices(messages, keep_indices)
    keep_indices = {idx for idx in keep_indices if 0 <= idx < len(messages)}

    old_messages = [
        msg for index, msg in enumerate(messages)
        if index not in keep_indices and not _is_instruction_message(msg)
    ]
    if not old_messages:
        return None

    from_tokens = estimate_conversation_tokens(messages)
    instruction_messages = [
        msg for index, msg in enumerate(messages)
        if index in keep_indices and _is_instruction_message(msg)
    ]
    preserved_messages = [
        msg for index, msg in enumerate(messages)
        if index in keep_indices and not _is_instruction_message(msg)
    ]
    summary_msg = {"role": "user", "content": _summarize_compacted_messages(old_messages)}
    compacted = instruction_messages + [summary_msg] + preserved_messages
    compacted = _truncate_tool_results(compacted, profile["tool_result_max"])
    to_tokens = estimate_conversation_tokens(compacted)
    near_full = system_tokens + to_tokens + int(profile.get("max_output") or 0) > (
        int(profile.get("context_window") or 0) * 0.90
    )
    logger.info(
        "State-preserving compaction: %d → %d messages, %d → %d tokens",
        len(messages),
        len(compacted),
        from_tokens,
        to_tokens,
    )
    return TrimResult(
        compacted,
        near_full=near_full,
        was_trimmed=True,
        was_compacted=True,
        compacted_from_tokens=from_tokens,
        compacted_to_tokens=to_tokens,
    )


def _recent_messages_preserving_latest_user(messages: list[dict], keep_last: int) -> list[dict]:
    """Return recent messages, always including the newest user turn."""
    if keep_last <= 0:
        recent: list[dict] = []
    else:
        recent = list(messages[-keep_last:])
    latest_user = next((msg for msg in reversed(messages) if _is_user_message(msg)), None)
    if latest_user is not None and all(msg is not latest_user for msg in recent):
        recent.append(latest_user)
        original_order = {id(msg): idx for idx, msg in enumerate(messages)}
        recent.sort(key=lambda msg: original_order.get(id(msg), 0))
    return recent


def _recent_paired_messages(messages: list[dict], keep_last: int) -> list[dict]:
    """The last *keep_last* non-system messages plus the latest user turn, with
    every kept tool output's tool_call message (and every kept tool_call's
    outputs) included, in original order."""
    keep: set[int] = set(range(max(1, len(messages) - keep_last), len(messages)))
    latest_user = next(
        (i for i in range(len(messages) - 1, 0, -1) if _is_user_message(messages[i])), None,
    )
    if latest_user is not None:
        keep.add(latest_user)
    _add_matching_tool_call_indices(messages, keep)
    _add_matching_tool_output_indices(messages, keep)
    return [messages[i] for i in sorted(keep) if i > 0]


def trim_conversation(
    messages: list[dict],
    system_tokens: int,
    profile: dict,
    tool_tokens: int = 0,
) -> TrimResult:
    """Trim conversation to fit within context budget.

    Returns a TrimResult with the trimmed messages and status flags:
    - near_full: True if context is >90% full even after trimming
    - was_trimmed: True if messages were summarized/removed

    Strategy:
    1. Calculate token budget (context_window * summarize_at - system_tokens
       - tool_tokens - max_output). *tool_tokens* is what the tool schemas
       cost per request; they used to be ignored, which let a compact model
       be sent more than its whole window.
    2. If conversation fits, return as-is
    3. Otherwise, keep system message + the latest user turn + recent messages
       (with their tool_call/tool pairs intact), summarize the rest
    """
    context_window = profile["context_window"]
    max_output = profile["max_output"]
    threshold = int(context_window * profile["summarize_at"])
    fixed_tokens = system_tokens + int(tool_tokens or 0)
    budget = threshold - fixed_tokens - max_output

    if budget <= 0:
        logger.warning("System prompt + tools (%d tokens) exceed budget for %d context",
                        fixed_tokens, context_window)
        if len(messages) > 2:
            trimmed = [messages[0]] + _recent_paired_messages(messages, 2)
        else:
            trimmed = messages
        return TrimResult(trimmed, near_full=True, was_trimmed=True)

    # Estimate current conversation tokens (excluding system)
    conv_tokens = sum(estimate_message_tokens(m) for m in messages[1:])

    compacted = _state_preserving_compaction(messages, system_tokens, profile, conv_tokens)
    if compacted is not None:
        return compacted

    if conv_tokens <= budget:
        # Check if we're getting close to full (>90% of total context used)
        total_used = fixed_tokens + conv_tokens + max_output
        near_full = total_used > context_window * 0.90
        return TrimResult(messages, near_full=near_full)

    # Need to trim — keep system + latest user turn + last 4 messages, plus
    # whatever tool_call/tool pairs those messages belong to: a `tool` message
    # whose `tool_calls` was summarized away is rejected by the provider
    # ("tool message must follow tool_calls"), which then looked like a model
    # without tool support.
    keep_last = 4
    if len(messages) <= keep_last + 1:
        truncated = _truncate_tool_results(messages, profile["tool_result_max"])
        return TrimResult(truncated, near_full=True, was_trimmed=True)

    system_msg = messages[0]
    recent_messages = _recent_paired_messages(messages, keep_last)
    recent_ids = {id(msg) for msg in recent_messages}
    old_messages = [msg for msg in messages[1:] if id(msg) not in recent_ids]

    summary_parts = []
    for msg in old_messages:
        role = msg.get("role", "")
        content = msg.get("content") or ""
        if role == "user" and content:
            summary_parts.append(f"User asked: {content[:100]}")
        elif role == "assistant" and content:
            summary_parts.append(f"Assistant: {content[:100]}")
        elif role == "tool":
            name = msg.get("name", "tool")
            summary_parts.append(f"Tool {name} was called")

    summary_text = "Previous conversation summary:\n" + "\n".join(summary_parts[-10:])
    summary_msg = {"role": "user", "content": summary_text}

    trimmed = [system_msg, summary_msg] + recent_messages

    # Check if still near full after trimming
    trimmed_tokens = sum(estimate_message_tokens(m) for m in trimmed[1:])
    total_used = fixed_tokens + trimmed_tokens + max_output
    near_full = total_used > context_window * 0.90

    logger.info("Trimmed conversation: %d → %d messages (summarized %d, near_full=%s)",
                len(messages), len(trimmed), len(old_messages), near_full)
    return TrimResult(trimmed, near_full=near_full, was_trimmed=True)


def _truncate_tool_results(messages: list[dict], max_chars: int) -> list[dict]:
    """Truncate tool result content in messages."""
    result = []
    for msg in messages:
        content = msg.get("content") or ""
        if msg.get("role") == "tool" and len(content) > max_chars:
            msg = {**msg, "content": content[:max_chars] + "..."}
        elif msg.get("type") == "function_call_output":
            output = msg.get("output") or ""
            if len(output) > max_chars:
                msg = {**msg, "output": output[:max_chars] + "..."}
        result.append(msg)
    return result


# ---------------------------------------------------------------------------
# Tool schema filtering
# ---------------------------------------------------------------------------

# Most commonly needed tools — prioritized when filtering for smaller models.
# Weave/slice lifecycle coverage: creation, mutation (add/remove/update),
# submission, background runs (start/stop/list/output), and the site tools
# needed for placement decisions. Chameleon core kept alongside FABRIC.
CORE_TOOLS = {
    # Slice lifecycle
    "list_slices", "get_slice", "create_slice", "clone_slice", "submit_slice",
    "get_job_status", "configure_networking", "delete_slice", "renew_slice",
    "validate_slice", "refresh_slice",
    # Slice mutation (topology editing)
    "add_node", "add_component", "add_network", "add_fabnet",
    "update_node", "remove_node", "remove_network",
    # Resource discovery for placement
    "query_sites", "get_site_hosts",
    # Weaves / templates
    "create_weave", "list_templates", "load_template", "save_as_template",
    "list_recipes", "execute_recipe",
    # Background run lifecycle
    "start_background_run", "stop_background_run",
    "list_background_runs", "get_background_run_output",
    # Files + VM ops
    "write_file", "read_file", "run_python_script", "run_jupyter_notebook",
    "ssh_execute", "write_vm_file", "read_vm_file", "download_file_bulk",
    "reboot_and_wait", "create_tunnel",
    # Examples / search
    "search_examples",
    # Chameleon core
    "list_chameleon_leases", "list_chameleon_sites", "create_chameleon_lease",
    "list_chameleon_slices", "deploy_chameleon_slice",
    # SPHERE core (experiment creation lifecycle)
    "list_sphere_realizations", "create_sphere_experiment", "push_sphere_model",
    "sphere_realize", "sphere_materialize", "get_sphere_materialization",
    "package_sphere_experiment",
    # SPHERE XDC lifecycle (reaching experiment nodes)
    "list_sphere_xdcs", "create_sphere_xdc", "attach_sphere_xdc",
    # Federated/composite core
    "list_composite_slices", "get_composite_slice",
    # FABRIC infrastructure metrics (fabric-metrics MCP proxy)
    "list_metric_topics", "list_metric_param_options",
    "query_infrastructure_metrics",
}


def filter_tool_schemas(schemas: list[dict], max_tools: int) -> list[dict]:
    """Return top N tools, prioritizing CORE_TOOLS."""
    if len(schemas) <= max_tools:
        return schemas

    # Split into core and non-core
    core = [s for s in schemas if s.get("function", {}).get("name") in CORE_TOOLS]
    non_core = [s for s in schemas if s.get("function", {}).get("name") not in CORE_TOOLS]

    # Fill up to max_tools
    remaining = max_tools - len(core)
    if remaining > 0:
        return core + non_core[:remaining]
    return core[:max_tools]
