"""Built-in model capability defaults for LoomAI assistant and harnesses.

These values are the source-controlled fallback for the benchmark-generated
``model_capabilities.json`` file. Runtime profile files may add more models,
but known ideal overrides in this module remain authoritative where the
benchmark notes identified a better container default.
"""

from __future__ import annotations

import copy
from typing import Any


CAPABILITY_DEFAULT_SOURCE = "builtin:loomai-model-capability-defaults"

_TRUNCATION_POLICY = (
    "preserve system/developer instructions, tool outputs, current task, and "
    "final-answer contract; summarize older evidence"
)

_WEAK_MODEL_CONTEXT_MANAGEMENT = {
    "weak_model_context_management": True,
    "context_compaction_enabled": True,
    "context_compaction_trigger_tokens": 16000,
    "context_compaction_trigger_messages": 18,
    "context_compaction_preserve_last_tool_outputs": 4,
    "context_compaction_keep_last_messages": 12,
}


DEFAULT_MODEL_CAPABILITY_PROFILES: dict[str, dict[str, Any]] = {
    "ai-renci:gpt-5.5": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "ai-renci:gpt-5.5",
        "provider": "ai-renci",
        "config_id": "gpt55-responses-reasoning-profile",
        "evaluation_confidence": "high",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "reasoning-large",
        "context_window_tokens": 131072,
        "max_input_tokens": 98304,
        "max_output_tokens": 32768,
        "endpoint_style": "responses",
        "reasoning_model": True,
        "reasoning_effort": "medium",
        "strip_temperature": True,
    },
    "ai-renci:Kimi-K2.6": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "ai-renci:Kimi-K2.6",
        "provider": "ai-renci",
        "config_id": "kimi-k26-safe-profile",
        "evaluation_confidence": "medium",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "standard",
        "context_window_tokens": 131072,
        "max_input_tokens": 122880,
        "max_output_tokens": 8192,
        "temperature": 0.1,
        "top_p": 0.9,
        "endpoint_style": "chat",
    },
    "fabric:qwen3-coder-30b": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "fabric:qwen3-coder-30b",
        "provider": "fabric",
        "config_id": "qwen3-coder-harness-temp-0.3-profile",
        "evaluation_confidence": "high",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "standard-code",
        "context_window_tokens": 262144,
        "max_input_tokens": 229376,
        "max_output_tokens": 32768,
        "temperature": 0.3,
        "top_p": 0.9,
        "endpoint_style": "chat",
        **_WEAK_MODEL_CONTEXT_MANAGEMENT,
    },
    "fabric:gpt-oss-20b": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "fabric:gpt-oss-20b",
        "provider": "fabric",
        "config_id": "gpt-oss-temp-0.0-profile",
        "evaluation_confidence": "high",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "standard",
        "context_window_tokens": 131072,
        "max_input_tokens": 98304,
        "max_output_tokens": 32768,
        "temperature": 0.0,
        "top_p": 0.9,
        "endpoint_style": "chat",
    },
    "fabric:gemma-4-27b": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "fabric:gemma-4-27b",
        "provider": "fabric",
        "config_id": "gemma-4-27b-262k-profile",
        "evaluation_confidence": "medium",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "standard",
        "context_window_tokens": 262144,
        "max_input_tokens": 258048,
        "max_output_tokens": 4096,
        "temperature": 0.1,
        "top_p": 0.95,
        "endpoint_style": "chat",
    },
    "fabric:nemotron-nano-30b": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "fabric:nemotron-nano-30b",
        "provider": "fabric",
        "config_id": "nemotron-reasoning-temp-0.3-profile",
        "evaluation_confidence": "medium",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "reasoning-standard",
        "context_window_tokens": 262144,
        "max_input_tokens": 258048,
        "max_output_tokens": 4096,
        "temperature": 0.3,
        "top_p": 0.9,
        "endpoint_style": "chat",
        "reasoning_model": True,
    },
    "nrp:minimax-m2": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "nrp:minimax-m2",
        "provider": "nrp",
        "config_id": "minimax-temp-0.0-profile",
        "evaluation_confidence": "high",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "standard",
        "context_window_tokens": 131072,
        "max_input_tokens": 98304,
        "max_output_tokens": 32768,
        "temperature": 0.0,
        "top_p": 0.9,
        "endpoint_style": "chat",
        **_WEAK_MODEL_CONTEXT_MANAGEMENT,
    },
    "nrp:qwen3": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "nrp:qwen3",
        "provider": "nrp",
        "config_id": "qwen3-temp-0.0-profile",
        "evaluation_confidence": "high",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "standard",
        "context_window_tokens": 32768,
        "max_input_tokens": 24576,
        "max_output_tokens": 8192,
        "temperature": 0.0,
        "top_p": 0.9,
        "endpoint_style": "chat",
        **_WEAK_MODEL_CONTEXT_MANAGEMENT,
        "context_compaction_trigger_tokens": 12000,
    },
    "nrp:qwen3-small": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "nrp:qwen3-small",
        "provider": "nrp",
        "config_id": "qwen3-small-temp-0.1-profile",
        "evaluation_confidence": "medium",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "compact",
        "context_window_tokens": 32768,
        "max_input_tokens": 24576,
        "max_output_tokens": 8192,
        "temperature": 0.1,
        "top_p": 0.9,
        "endpoint_style": "chat",
    },
    "nrp:qwen3-4bit": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "nrp:qwen3-4bit",
        "provider": "nrp",
        "config_id": "qwen3-4bit-temp-0.1-profile",
        "evaluation_confidence": "medium",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "standard",
        "context_window_tokens": 32768,
        "max_input_tokens": 24576,
        "max_output_tokens": 8192,
        "temperature": 0.1,
        "top_p": 0.9,
        "endpoint_style": "chat",
    },
    "nrp:glm-5": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "nrp:glm-5",
        "provider": "nrp",
        "config_id": "glm-reasoning-budget-profile",
        "evaluation_confidence": "high",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "reasoning-standard",
        "context_window_tokens": 32768,
        "max_input_tokens": 24576,
        "max_output_tokens": 8192,
        "temperature": 0.0,
        "top_p": 0.9,
        "endpoint_style": "chat",
        "reasoning_model": True,
    },
    "nrp:gpt-oss": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "nrp:gpt-oss",
        "provider": "nrp",
        "config_id": "gpt-oss-temp-0.0-profile",
        "evaluation_confidence": "medium",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "standard",
        "context_window_tokens": 131072,
        "max_input_tokens": 122880,
        "max_output_tokens": 8192,
        "temperature": 0.0,
        "top_p": 1.0,
        "endpoint_style": "chat",
    },
    "nrp:kimi": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "nrp:kimi",
        "provider": "nrp",
        "config_id": "kimi-temp-0.1-profile",
        "evaluation_confidence": "medium",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "standard",
        "context_window_tokens": 131072,
        "max_input_tokens": 122880,
        "max_output_tokens": 8192,
        "temperature": 0.1,
        "top_p": 0.9,
        "endpoint_style": "chat",
    },
    "nrp:gemma": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "nrp:gemma",
        "provider": "nrp",
        "config_id": "gemma-temp-0.1-profile",
        "evaluation_confidence": "medium",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "standard",
        "context_window_tokens": 32768,
        "max_input_tokens": 28672,
        "max_output_tokens": 4096,
        "temperature": 0.1,
        "top_p": 0.95,
        "endpoint_style": "chat",
        "omit_tool_choice": True,
    },
    "nrp:gemma-small": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "nrp:gemma-small",
        "provider": "nrp",
        "config_id": "gemma-small-temp-0.1-profile",
        "evaluation_confidence": "medium",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "standard",
        "context_window_tokens": 32768,
        "max_input_tokens": 28672,
        "max_output_tokens": 4096,
        "temperature": 0.1,
        "top_p": 0.95,
        "endpoint_style": "chat",
        "omit_tool_choice": True,
    },
    "nrp:gemma-small-e4b": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "nrp:gemma-small-e4b",
        "provider": "nrp",
        "config_id": "gemma-small-e4b-temp-0.1-profile",
        "evaluation_confidence": "medium",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "standard",
        "context_window_tokens": 32768,
        "max_input_tokens": 28672,
        "max_output_tokens": 4096,
        "temperature": 0.1,
        "top_p": 0.95,
        "endpoint_style": "chat",
        "omit_tool_choice": True,
    },
    "nrp:gh200-test": {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": "nrp:gh200-test",
        "provider": "nrp",
        "config_id": "gh200-safe-profile",
        "evaluation_confidence": "low",
        "evaluation_status": "profiled",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "standard",
        "context_window_tokens": 32768,
        "max_input_tokens": 28672,
        "max_output_tokens": 4096,
        "temperature": 0.0,
        "top_p": 1.0,
        "endpoint_style": "chat",
    },
}


KNOWN_MODEL_IDEAL_OVERRIDES: dict[str, dict[str, Any]] = {
    "ai-renci:gpt-5.5": {
        "endpoint_style": "responses",
        "reasoning_model": True,
        "reasoning_effort": "medium",
        "strip_temperature": True,
    },
    "gpt-5.5": {
        "endpoint_style": "responses",
        "reasoning_model": True,
        "reasoning_effort": "medium",
        "strip_temperature": True,
    },
    "fabric:qwen3-coder-30b": {
        "context_window_tokens": 262144,
        "max_input_tokens": 229376,
        "max_output_tokens": 32768,
        "temperature": 0.3,
        "top_p": 0.9,
        **_WEAK_MODEL_CONTEXT_MANAGEMENT,
    },
    "qwen3-coder-30b": {
        "context_window_tokens": 262144,
        "max_input_tokens": 229376,
        "max_output_tokens": 32768,
        "temperature": 0.3,
        "top_p": 0.9,
        **_WEAK_MODEL_CONTEXT_MANAGEMENT,
    },
    "fabric:gemma-4-27b": {
        "context_window_tokens": 262144,
        "max_input_tokens": 258048,
    },
    "gemma-4-27b": {
        "context_window_tokens": 262144,
        "max_input_tokens": 258048,
    },
    "fabric:nemotron-nano-30b": {
        "context_window_tokens": 262144,
        "max_input_tokens": 258048,
        "temperature": 0.3,
        "reasoning_model": True,
    },
    "nemotron-nano-30b": {
        "context_window_tokens": 262144,
        "max_input_tokens": 258048,
        "temperature": 0.3,
        "reasoning_model": True,
    },
    "nrp:glm-5": {
        "reasoning_model": True,
        "context_window_tokens": 32768,
        "max_input_tokens": 24576,
        "max_output_tokens": 8192,
    },
    "glm-5": {
        "reasoning_model": True,
        "context_window_tokens": 32768,
        "max_input_tokens": 24576,
        "max_output_tokens": 8192,
    },
}


SAFE_TIER_MODEL_DEFAULTS: dict[str, Any] = {
    "context_window_tokens": 32768,
    "max_input_tokens": 24576,
    "max_output_tokens": 6144,
    "temperature": 0.5,
    "top_p": 0.9,
    "endpoint_style": "chat",
}


def clone_builtin_capability_profiles() -> dict[str, dict[str, Any]]:
    """Return a deep copy of built-in profiles keyed by canonical model key."""
    return copy.deepcopy(DEFAULT_MODEL_CAPABILITY_PROFILES)


def apply_known_model_ideal_overrides(profile: dict[str, Any]) -> dict[str, Any]:
    """Apply source-controlled ideal overrides to a normalized profile copy."""
    updated = dict(profile)
    model_key = str(updated.get("model_key") or "").strip()
    bare = model_key.split(":", 1)[-1] if ":" in model_key else model_key
    for key in (model_key, model_key.lower(), bare, bare.lower()):
        override = KNOWN_MODEL_IDEAL_OVERRIDES.get(key)
        if override:
            updated.update(copy.deepcopy(override))
    return updated


def safe_harness_model_defaults(model_id: str, provider: str = "") -> dict[str, Any]:
    """Return provider-safe defaults for a model absent from known profiles."""
    model_id = str(model_id or "").strip()
    model_key = f"{provider}:{model_id}" if provider and ":" not in model_id else model_id
    defaults = {
        "source_path": CAPABILITY_DEFAULT_SOURCE,
        "model_key": model_key,
        "provider": provider or None,
        "config_id": "safe-tier-default-profile",
        "evaluation_confidence": "low",
        "evaluation_status": "safe-default",
        "context_truncation_policy": _TRUNCATION_POLICY,
        "orchestration_tier": "standard",
        **SAFE_TIER_MODEL_DEFAULTS,
    }
    return {k: v for k, v in defaults.items() if v is not None}


def get_capability_profile_for_model(model_id: str, provider: str = "") -> dict[str, Any]:
    """Return a built-in normalized profile for a provider/model, or safe defaults."""
    raw = str(model_id or "").strip()
    provider_key = str(provider or "").strip()
    lookup = raw if ":" in raw else f"{provider_key}:{raw}" if provider_key else raw
    profiles = clone_builtin_capability_profiles()
    profile = profiles.get(lookup) or profiles.get(lookup.lower())
    if not profile and ":" not in raw:
        profile = profiles.get(raw) or profiles.get(raw.lower())
    if not profile:
        profile = safe_harness_model_defaults(raw, provider_key)
    return apply_known_model_ideal_overrides(profile)


def harness_model_config(model_id: str, provider: str = "") -> dict[str, Any]:
    """Convert a normalized profile into a compact external-harness model entry."""
    profile = get_capability_profile_for_model(model_id, provider)
    bare = str(model_id or profile.get("model_key") or "").split(":", 1)[-1]
    config: dict[str, Any] = {"name": bare}
    field_map = {
        "context_window_tokens": "context_window",
        "max_input_tokens": "max_input_tokens",
        "max_output_tokens": "max_output_tokens",
        "temperature": "temperature",
        "top_p": "top_p",
        "endpoint_style": "endpoint_style",
        "reasoning_effort": "reasoning_effort",
        "reasoning_model": "reasoning_model",
        "strip_temperature": "strip_temperature",
        "omit_tool_choice": "omit_tool_choice",
        "orchestration_tier": "orchestration_tier",
    }
    for src, dest in field_map.items():
        if src in profile:
            config[dest] = profile[src]
    if bare.lower() in {"glm-5", "glm5"}:
        config.setdefault("reasoning_effort", "high")
        config["reasoning_budget_mode"] = "output_preferred"
    if str(provider or "").lower() == "nrp" and bare.lower().startswith("gemma"):
        config.setdefault("omit_tool_choice", True)
    return config


def harness_models_for_provider(provider: str, model_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Return harness model entries for *model_ids*, never omitting unknowns."""
    return {
        model_id: harness_model_config(model_id, provider)
        for model_id in model_ids
    }
