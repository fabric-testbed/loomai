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

import json
import logging
import os
import re
import threading
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument extractor helpers
# ---------------------------------------------------------------------------


def _extract_duration_days(full_message: str, default: int = 7) -> int:
    """Parse '3 days', 'for 14 days', 'by two weeks' etc. out of a user message."""
    s = full_message.lower()
    # "for 3 days" / "by 3 days" / "3 days" / "3d"
    m = re.search(r"(\d+)\s*(?:days?|d)\b", s)
    if m:
        try:
            return max(1, min(180, int(m.group(1))))
        except ValueError:
            pass
    m = re.search(r"(\d+)\s*weeks?\b", s)
    if m:
        try:
            return max(1, min(180, int(m.group(1)) * 7))
        except ValueError:
            pass
    # "a week", "two weeks", "one month"
    _WORDS = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
    for word, n in _WORDS.items():
        if re.search(rf"\b{word}\s+weeks?\b", s):
            return min(180, n * 7)
        if re.search(rf"\b{word}\s+days?\b", s):
            return min(180, n)
    if re.search(r"\ba\s+month\b|\bone\s+month\b", s):
        return 30
    return default


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

    # --- Slice topology mutations (component/node/network) -----------------
    # These must be matched BEFORE the generic create/delete slice patterns so
    # that "add a GPU to node1" doesn't first match a less specific verb.
    # All MEDIUM confidence: non-destructive but they modify the draft topology.

    # Add a GPU/NIC/FPGA/NVME component — MEDIUM
    # "add a GPU_Tesla_T4 to node1 in slice foo"
    # "attach NIC_Basic to node2 on my-slice"
    (r"(?:add|attach)\s+(?:a\s+)?(GPU_[A-Za-z0-9_]+|NIC_[A-Za-z0-9_]+|FPGA_[A-Za-z0-9_]+|NVME_[A-Za-z0-9_]+)\s+to\s+(?:node\s+)?['\"]?(\w+)['\"]?\s+(?:in|on)\s+(?:slice\s+)?['\"]?(\S+)['\"]?",
     "add_component",
     lambda m: {
         "slice_name": m.group(3),
         "node_name": m.group(2),
         "component_name": f"{m.group(2)}-{m.group(1).lower()}",
         "model": m.group(1),
     },
     "medium"),

    # Add a node — MEDIUM
    # "add a node called worker1 at TACC to slice foo"
    (r"add\s+(?:a\s+)?node\s+(?:called\s+|named\s+)?['\"]?([a-zA-Z0-9_.\-]+)['\"]?\s+(?:at|on)\s+(\w+)\s+to\s+(?:slice\s+)?['\"]?(\S+)['\"]?",
     "add_node",
     lambda m: {
         "slice_name": m.group(3),
         "node_name": m.group(1),
         "site": m.group(2).upper(),
     },
     "medium"),

    # Change a node's image — MEDIUM
    # "change the image on node1 in slice foo to default_ubuntu_24"
    (r"(?:change|update|set)\s+(?:the\s+)?image\s+(?:on\s+|of\s+)?(?:node\s+)?['\"]?(\w+)['\"]?\s+(?:in\s+|of\s+)?(?:slice\s+)?['\"]?(\S+?)['\"]?\s+to\s+([a-zA-Z0-9_]+)",
     "update_node",
     lambda m: {
         "slice_name": m.group(2),
         "node_name": m.group(1),
         "image": m.group(3),
     },
     "medium"),

    # Add a network to a slice — MEDIUM
    # "add an L2Bridge network called data to slice foo"
    (r"add\s+(?:an?\s+)?(L2Bridge|L2STS|L2PTP|FABNetv4|FABNetv6)\s+network\s+(?:called\s+|named\s+)?['\"]?(\w+)['\"]?\s+to\s+(?:slice\s+)?['\"]?(\S+)['\"]?",
     "add_network",
     lambda m: {
         "slice_name": m.group(3),
         "network_name": m.group(2),
         "type": m.group(1),
         "interfaces": [],
     },
     "medium"),

    # Create slice — MEDIUM (may need clarification)
    (r"create\s+(?:a\s+)?(?:new\s+)?slice\s+(?:called\s+|named\s+)?['\"]?(\S+?)['\"]?$",
     "create_slice", lambda m: {"name": m.group(1)}, "medium"),

    # Delete slice — MEDIUM (needs confirmation)
    (r"delete\s+(?:slice\s+)?['\"]?(\S+?)['\"]?$",
     "delete_slice", lambda m: {"slice_name": m.group(1)}, "medium"),

    # Renew slice with explicit duration — HIGH
    # Matches: "renew my-slice for 14 days", "extend foo by 3 days", "renew bar 2 weeks"
    (r"(?:renew|extend)\s+(?:slice\s+|lease\s+(?:on|for)\s+)?['\"]?(\S+?)['\"]?\s+(?:by\s+|for\s+)?(\d+\s*(?:days?|d|weeks?)\b.*)",
     "renew_slice",
     lambda m: {"slice_name": m.group(1), "days": _extract_duration_days(m.group(0))},
     "high"),
    # Renew slice without duration — HIGH (defaults to 7 days)
    (r"(?:renew|extend)\s+(?:slice\s+|lease\s+(?:on|for)\s+)?['\"]?(\S+)['\"]?$",
     "renew_slice",
     lambda m: {"slice_name": m.group(1), "days": _extract_duration_days(m.string, default=7)},
     "high"),

    # Submit/deploy — MEDIUM
    (r"(?:submit|deploy|provision)\s+(?:slice\s+)?['\"]?(\S+?)['\"]?$",
     "submit_slice", lambda m: {"slice_name": m.group(1)}, "medium"),

    # Validate — HIGH
    (r"validate\s+(?:slice\s+)?['\"]?(\S+)['\"]?$",
     "validate_slice", lambda m: {"slice_name": m.group(1)}, "high"),

    # Refresh — HIGH
    (r"refresh\s+(?:slice\s+)?['\"]?(\S+)['\"]?$",
     "refresh_slice", lambda m: {"slice_name": m.group(1)}, "high"),

    # Templates/weaves listing — HIGH
    (r"(?:list|show)\s+(?:my\s+|all\s+)?(?:templates?|weaves?)", "list_templates", None, "high"),
    (r"what\s+(?:templates?|weaves?)\s+(?:do\s+)?(?:i\s+have|are\s+(?:there|available))",
     "list_templates", None, "high"),
    (r"^(?:my\s+)?(?:templates?|weaves?)\s*\??$", "list_templates", None, "high"),

    # --- Weave lifecycle: run / watch / stop -----------------------------
    # Run/execute a weave by explicit keyword — MEDIUM (mutation, non-destructive).
    # Requires "weave/template/experiment" keyword so we don't misfire on
    # "execute ls" or "run cat". Users who say "execute iperf3_Tuning" without
    # the keyword fall through to the LLM, which can call start_background_run
    # directly via tool schemas.
    (r"(?:run|execute|start|launch)\s+(?:the\s+|my\s+)?(?:weave|template|experiment)\s+['\"]?([a-zA-Z0-9_.\-]+)['\"]?",
     "start_background_run",
     lambda m: {"weave_dir_name": m.group(1), "script": "auto"},
     "medium"),

    # List background runs — HIGH (read-only)
    (r"(?:list|show|what)\s+(?:background\s+)?(?:runs?|weave\s+runs?|experiments\s+running)",
     "list_background_runs", None, "high"),
    (r"what'?s\s+running(?:\s+now)?$", "list_background_runs", None, "high"),
    (r"(?:any|are\s+there)\s+(?:background\s+)?runs?(?:\s+running)?", "list_background_runs", None, "high"),

    # Tail / watch / show run output — HIGH
    (r"(?:tail|watch|follow|show)\s+(?:the\s+)?(?:output|log|logs)\s+(?:of\s+|for\s+)?(?:run\s+)?['\"]?([a-zA-Z0-9_.\-]+)['\"]?",
     "get_background_run_output",
     lambda m: {"run_id": m.group(1), "offset": 0},
     "high"),
    (r"(?:show|get)\s+(?:me\s+)?(?:the\s+)?(?:output|log)\s+(?:of\s+|for\s+|from\s+)?(?:run\s+)?['\"]?([a-zA-Z0-9_.\-]+)['\"]?",
     "get_background_run_output",
     lambda m: {"run_id": m.group(1), "offset": 0},
     "high"),

    # Stop a background run — MEDIUM.
    # Requires an explicit "run" / "weave" / "experiment" keyword to avoid
    # misfiring on "stop my-slice" which doesn't map to a run at all.
    (r"(?:stop|kill|cancel|halt|abort)\s+(?:the\s+)?(?:run|weave|experiment)\s+['\"]?([a-zA-Z0-9_.\-]+)['\"]?",
     "stop_background_run",
     lambda m: {"run_id": m.group(1)},
     "medium"),

    # Load / clone a weave into a new draft slice — MEDIUM
    (r"(?:load|clone|use)\s+(?:the\s+|weave\s+|template\s+)?['\"]?([a-zA-Z0-9_.\-]+)['\"]?\s+(?:as\s+|into\s+)\s*['\"]?([a-zA-Z0-9_.\-]+)['\"]?",
     "load_template",
     lambda m: {"template_name": m.group(1), "slice_name": m.group(2)},
     "medium"),

    # Save current slice as a reusable template/weave — MEDIUM
    (r"save\s+(?:slice\s+)?['\"]?([a-zA-Z0-9_.\-]+)['\"]?\s+as\s+(?:a\s+)?(?:template|weave)\s+['\"]?([a-zA-Z0-9_.\-]+)['\"]?",
     "save_as_template",
     lambda m: {"slice_name": m.group(1), "template_name": m.group(2)},
     "medium"),

    # Show weave details (reads weave.md documentation) — HIGH
    (r"(?:show|describe|tell\s+me\s+about|explain)\s+(?:the\s+|weave\s+|template\s+)['\"]?([a-zA-Z0-9_.\-]+)['\"]?\s+(?:weave|template)",
     "read_file",
     lambda m: {"path": f"my_artifacts/{m.group(1)}/weave.md"},
     "low"),  # LOW because the LLM may want to run other tools after

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

_stats_lock = threading.Lock()
_stats_loaded = False
_stats_dirty = False


def _stats_path() -> str:
    """Return the on-disk path for intent stats (same .loomai dir as settings)."""
    try:
        from app.settings_manager import get_settings_dir
        return os.path.join(get_settings_dir(), "intent_stats.json")
    except Exception:
        storage = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
        return os.path.join(storage, ".loomai", "intent_stats.json")


def _load_stats() -> None:
    """Load persisted stats on first access (idempotent)."""
    global _intent_stats, _stats_loaded
    if _stats_loaded:
        return
    _stats_loaded = True
    path = _stats_path()
    if not os.path.isfile(path):
        return
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            _intent_stats = data
            logger.info("Loaded intent stats from %s (%d models)", path, len(data))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to load intent stats from %s: %s", path, e)


def _save_stats() -> None:
    """Persist stats to disk atomically. Only writes if dirty."""
    global _stats_dirty
    if not _stats_dirty:
        return
    path = _stats_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_intent_stats, f, indent=2)
        os.replace(tmp, path)
        _stats_dirty = False
    except OSError as e:
        logger.warning("Failed to save intent stats to %s: %s", path, e)


def record_intent_result(model: str, intent: str, success: bool) -> None:
    """Record whether an intent execution succeeded or failed for a model."""
    global _stats_dirty
    if not intent:
        return
    with _stats_lock:
        _load_stats()
        if model not in _intent_stats:
            _intent_stats[model] = {}
        if intent not in _intent_stats[model]:
            _intent_stats[model][intent] = {"success": 0, "fail": 0}
        key = "success" if success else "fail"
        _intent_stats[model][intent][key] += 1
        _stats_dirty = True
        # Persist immediately — the write is small and atomic; losing stats
        # on crash would defeat the point of learning.
        _save_stats()


def should_disable_tools(model: str) -> bool:
    """Check if a model has >50% tool-calling failure rate."""
    with _stats_lock:
        _load_stats()
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
    """Return a copy of the current intent statistics (for debugging)."""
    with _stats_lock:
        _load_stats()
        return {k: {ik: dict(iv) for ik, iv in v.items()} for k, v in _intent_stats.items()}
