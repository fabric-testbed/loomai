"""LoomAI-side intent detection — pattern-match user messages to tool calls.

Instead of relying on the LLM's function calling (which many models don't
support), LoomAI detects intent directly and executes tools before the LLM
call.  The LLM then receives the tool results as context and just needs to
format a natural-language response.

Confidence levels:
- HIGH: Exact intent match → execute immediately, give results to LLM
- MEDIUM: Partial match → execute likely tools, let LLM decide if more needed
- LOW: Ambiguous → pass to LLM with tool calling if supported
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intent patterns: (compiled_regex, tool_name, arg_extractor, confidence)
# ---------------------------------------------------------------------------

_RAW_PATTERNS: list[tuple[str, str, Optional[Callable], str]] = [
    # Slice listing — HIGH confidence
    (r"(?:list|show|get)\s+(?:my\s+|all\s+)?slices?$", "list_slices", None, "high"),
    (r"what\s+slices?\s+(?:do\s+)?i\s+have", "list_slices", None, "high"),
    (r"(?:tell|show)\s+me\s+about\s+(?:my\s+)?slices?", "list_slices", None, "high"),
    (r"slice\s+(?:list|status)", "list_slices", None, "high"),
    (r"^(?:my\s+)?slices?\s*\?*$", "list_slices", None, "high"),

    # Slice detail — HIGH
    (r"(?:show|get|describe)\s+(?:me\s+)?(?:slice\s+)?['\"]?(\S+?)['\"]?\s*(?:details?|info)?$",
     "get_slice", lambda m: {"slice_name": m.group(1)}, "high"),
    (r"what(?:'s|\s+is)\s+(?:the\s+)?(?:state|status)\s+of\s+['\"]?(\S+)['\"]?$",
     "get_slice", lambda m: {"slice_name": m.group(1)}, "high"),

    # Site queries — HIGH
    (r"(?:what|which)\s+sites?\s+(?:are\s+)?(?:available|active)", "query_sites", None, "high"),
    (r"(?:list|show)\s+(?:all\s+)?(?:fabric\s+)?sites?", "query_sites", None, "high"),
    (r"find\s+sites?\s+(?:with\s+)?(?:gpu|GPU)", "query_sites", None, "high"),
    (r"(?:show|get)\s+(?:me\s+)?(?:available\s+)?resources?", "query_sites", None, "high"),
    (r"(?:what|where)\s+(?:can\s+i|has)\s+(?:get\s+)?gpu", "query_sites", None, "high"),

    # Site hosts — HIGH
    (r"(?:show|get|list)\s+hosts?\s+(?:at|for|on)\s+(\w+)", "get_site_hosts",
     lambda m: {"site_name": m.group(1).upper()}, "high"),

    # Create slice — MEDIUM (may need clarification)
    (r"create\s+(?:a\s+)?(?:new\s+)?slice\s+(?:called\s+|named\s+)?['\"]?(\S+?)['\"]?$",
     "create_slice", lambda m: {"name": m.group(1)}, "medium"),

    # Delete slice — MEDIUM (needs confirmation)
    (r"delete\s+(?:slice\s+)?['\"]?(\S+?)['\"]?$",
     "delete_slice", lambda m: {"slice_name": m.group(1)}, "medium"),

    # Renew slice — HIGH
    (r"(?:renew|extend)\s+(?:slice\s+|lease\s+(?:on|for)\s+)?['\"]?(\S+)['\"]?$",
     "renew_slice", lambda m: {"slice_name": m.group(1), "days": 7}, "high"),

    # Submit/deploy — MEDIUM
    (r"(?:submit|deploy|provision)\s+(?:slice\s+)?['\"]?(\S+?)['\"]?$",
     "submit_slice", lambda m: {"slice_name": m.group(1)}, "medium"),

    # Validate — HIGH
    (r"validate\s+(?:slice\s+)?['\"]?(\S+)['\"]?$",
     "validate_slice", lambda m: {"slice_name": m.group(1)}, "high"),

    # Refresh — HIGH
    (r"refresh\s+(?:slice\s+)?['\"]?(\S+)['\"]?$",
     "refresh_slice", lambda m: {"slice_name": m.group(1)}, "high"),

    # Templates/weaves — HIGH
    (r"(?:list|show)\s+(?:my\s+|all\s+)?(?:templates?|weaves?)", "list_templates", None, "high"),

    # Artifacts — HIGH
    (r"(?:list|show|browse)\s+(?:my\s+|all\s+)?(?:artifacts?|marketplace)",
     "list_artifacts", None, "high"),

    # Recipes — HIGH
    (r"(?:list|show)\s+(?:available\s+)?recipes?", "list_recipes", None, "high"),

    # Images — HIGH
    (r"(?:list|show|what)\s+(?:available\s+)?(?:vm\s+)?images?", "_list_images", None, "high"),

    # Create weave — LOW (LLM needs full tool-calling to write complex scripts)
    (r"create\s+(?:a\s+)?(?:new\s+)?weave\s+(?:called\s+|named\s+)?['\"]?(\S+)['\"]?",
     "create_weave", lambda m: {
         "name": m.group(1),
         "include_data_folder": bool(re.search(r"data\s+(?:folder|dir)", m.string, re.IGNORECASE)),
         "include_node_tools": bool(re.search(r"node.?tools?|setup\s+script|install", m.string, re.IGNORECASE)),
         "include_notebooks": True,
     }, "low"),
    (r"create\s+(?:a\s+)?(?:new\s+)?weave",
     "create_weave", lambda m: {"include_notebooks": True}, "low"),
    (r"(?:build|make|design)\s+(?:a\s+|an\s+)?(?:experiment|weave|topology)",
     "create_weave", lambda m: {"include_notebooks": True}, "low"),

    # Update/customize existing weave — LOW (needs tool-calling for write_file)
    (r"(?:consider|update|customize|modify|change|edit)\s+(?:the\s+)?(?:new\s+)?weave\s+(?:called\s+|named\s+)['\"]?([a-zA-Z0-9_-]+)['\"]?",
     "read_file", lambda m: {"path": f"my_artifacts/{m.group(1)}/weave.md"}, "low"),

    # Complex file creation — LOW (need full tool calling for write_file)
    (r"(?:write|build|make)\s+(?:a\s+)?(?:script|file|template|artifact)", "", None, "low"),
    (r"(?:write|create)\s+.+\.(?:py|sh|json|md)", "", None, "low"),

    # --- Chameleon Cloud ---
    (r"(?:list|show|my)\s+chameleon\s+leases?", "list_chameleon_leases", None, "high"),
    (r"chameleon\s+leases?", "list_chameleon_leases", None, "high"),
    (r"(?:list|show|my)\s+chameleon\s+instances?", "list_chameleon_instances", None, "high"),
    (r"chameleon\s+instances?", "list_chameleon_instances", None, "high"),
    (r"chameleon\s+sites?", "list_chameleon_sites", None, "high"),
    (r"(?:reserve|create)\s+.+(?:on|at)\s+CHI@", "create_chameleon_lease", None, "medium"),
    (r"chameleon\s+images?\s+(?:on|at)\s+(\S+)", "chameleon_site_images", lambda m: {"site": m.group(1)}, "high"),

    # Help / greeting — LOW (let LLM handle)
    (r"^(?:hi|hello|hey|help)[\s!?.]*$", "", None, "low"),
]

# Compile patterns once
INTENT_PATTERNS: list[tuple[re.Pattern, str, Optional[Callable], str]] = [
    (re.compile(pattern, re.IGNORECASE), tool, extractor, confidence)
    for pattern, tool, extractor, confidence in _RAW_PATTERNS
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_intent(message: str) -> tuple[str, dict, str]:
    """Detect intent from a user message.

    Returns:
        (tool_name, arguments, confidence)
        - tool_name: name of the tool to execute, or "" if no match
        - arguments: dict of arguments for the tool
        - confidence: "high", "medium", or "low"
    """
    message = message.strip()
    if not message:
        return ("", {}, "low")

    for pattern, tool_name, extractor, confidence in INTENT_PATTERNS:
        match = pattern.search(message)
        if match:
            args = extractor(match) if extractor else {}
            logger.info("Intent detected: %s (confidence=%s) from '%s'",
                        tool_name or "(none)", confidence, message[:50])
            return (tool_name, args, confidence)

    return ("", {}, "low")


def detect_multi_step(message: str) -> Optional[dict]:
    """Detect multi-step operation templates.

    Returns template dict or None.
    """
    from app.chat_templates import match_template
    return match_template(message)


# Destructive operations that need user confirmation
DESTRUCTIVE_TOOLS = {"delete_slice", "submit_slice"}

def is_destructive(tool_name: str) -> bool:
    """Check if a tool is destructive and needs confirmation."""
    return tool_name in DESTRUCTIVE_TOOLS


# ---------------------------------------------------------------------------
# C6: Learning from failures — track per-model per-intent success rates
# ---------------------------------------------------------------------------

_intent_stats: dict[str, dict[str, dict[str, int]]] = {}
# model → intent → {"success": int, "fail": int}


def record_intent_result(model: str, intent: str, success: bool) -> None:
    """Record whether an intent execution succeeded or failed for a model."""
    if model not in _intent_stats:
        _intent_stats[model] = {}
    if intent not in _intent_stats[model]:
        _intent_stats[model][intent] = {"success": 0, "fail": 0}
    key = "success" if success else "fail"
    _intent_stats[model][intent][key] += 1


def should_disable_tools(model: str) -> bool:
    """Check if a model has >50% tool-calling failure rate."""
    stats = _intent_stats.get(model, {})
    if not stats:
        return False
    total_success = sum(s["success"] for s in stats.values())
    total_fail = sum(s["fail"] for s in stats.values())
    total = total_success + total_fail
    if total < 5:  # Need at least 5 attempts before deciding
        return False
    return total_fail > total_success


def get_intent_stats() -> dict:
    """Return the current intent statistics (for debugging)."""
    return dict(_intent_stats)
