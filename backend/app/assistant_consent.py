"""Consent rules for destructive assistant tools.

The LoomAI assistant may only submit, delete or otherwise destroy resources
when the user has clearly asked for it. Three rules, all applied to the
user's own words (never to model output or tool results):

1. Term matching is on word boundaries. The old substring checks let
   "testbed" count as "test" and "look" as "ok", so "create a slice on the
   FABRIC testbed" authorized provisioning and "look at foo and remove it"
   confirmed a delete.
2. A confirmation is read from the latest user turn only. Earlier turns can
   grant provisioning consent for a slice the user asked to build and prove
   (that goal is durable), but "yes" from three turns ago never confirms a
   delete now.
3. When a destructive call is blocked, the exact tool and arguments are
   recorded as the conversation's pending action. A bare "yes" (or "yes,
   delete_slice", "go ahead", ...) on the user's next turn authorizes that
   action and nothing else. The assistant is told to ask for exactly that.

The pending record lives in memory keyed by conversation id and expires
after ten minutes, which is plenty for a human to answer and short enough
that a stale "yes" cannot fire later.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable

PENDING_TTL_SECONDS = 600

PROVISIONING_VERBS = (
    "submit", "deploy", "provision", "launch the slice", "start the slice",
    "go live", "bring up", "stand up",
)
SLICE_BUILD_VERBS = ("create", "build", "make", "set up", "setup")
OPERATIONAL_PROOF_TERMS = (
    "demonstrate", "verify", "validate", "prove", "test", "ping", "curl",
    "iperf", "iperf3", "ssh", "reachable", "connectivity", "working",
    "web service", "http", "service", "stableok",
)
DELETE_TERMS = (
    "delete", "destroy", "tear down", "teardown", "release", "remove",
    "drop", "kill", "terminate", "recreate",
)
CONFIRMATION_TERMS = (
    "yes", "confirm", "confirmed", "approve", "approved", "go ahead",
    "do it", "proceed", "ok", "okay",
)
_NEGATION_TERMS = ("no", "not", "don't", "dont", "never", "cancel", "stop", "wait", "hold")


def _word_re(terms: Iterable[str]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<![\w-])(?:{alternatives})(?![\w-])", re.IGNORECASE)


_PROVISION_RE = _word_re(PROVISIONING_VERBS)
_BUILD_RE = _word_re(SLICE_BUILD_VERBS)
_PROOF_RE = _word_re(OPERATIONAL_PROOF_TERMS)
_DELETE_RE = _word_re(DELETE_TERMS)
_CONFIRM_RE = _word_re(CONFIRMATION_TERMS)
_NEGATION_RE = _word_re(_NEGATION_TERMS)
_SLICE_RE = _word_re(("slice", "slices"))
_CONFIRM_START_RE = re.compile(
    r"^\W*(?:yes|yep|yeah|sure|confirm(?:ed)?|approve[d]?|go ahead|do it|proceed|ok|okay)(?![\w-])",
    re.IGNORECASE,
)


def _mentions(text: str, target: str) -> bool:
    target = (target or "").strip()
    if not target:
        return False
    return re.search(rf"(?<![\w-]){re.escape(target)}(?![\w-])", text, re.IGNORECASE) is not None


def text_authorizes_provisioning(text: str) -> bool:
    """A single user turn that asks for provisioning, or to build a slice and
    prove it works (which implies submitting it)."""
    text = text or ""
    if _PROVISION_RE.search(text):
        return True
    return bool(_SLICE_RE.search(text) and _BUILD_RE.search(text) and _PROOF_RE.search(text))


def conversation_authorizes_provisioning(user_texts: Iterable[str]) -> bool:
    return any(text_authorizes_provisioning(t) for t in user_texts)


def text_confirms_destruction(text: str, targets: Iterable[str]) -> bool:
    """The latest user turn names every target and says both a delete term and
    a confirmation term, e.g. "yes, delete old-slice"."""
    text = text or ""
    targets = [t for t in targets if t]
    if not targets:
        return False
    if not (_DELETE_RE.search(text) and _CONFIRM_RE.search(text)):
        return False
    return all(_mentions(text, t) for t in targets)


def is_bare_confirmation(text: str) -> bool:
    """A short reply that starts with a confirmation and contains no negation:
    "yes", "ok go ahead", "yes, delete_slice", "confirm". Not "yes but not
    yet", not "no", not a new request that happens to start with "ok"."""
    text = (text or "").strip()
    if not text or len(text) > 80:
        return False
    if _NEGATION_RE.search(text):
        return False
    return _CONFIRM_START_RE.match(text) is not None


# ---------------------------------------------------------------------------
# Pending destructive action, per conversation
# ---------------------------------------------------------------------------

@dataclass
class PendingAction:
    tool: str
    args: dict[str, Any]
    created_at: float


_pending: dict[str, PendingAction] = {}
_lock = threading.Lock()


def _normalized(args: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (args or {}).items():
        out[key] = value.strip().lower() if isinstance(value, str) else value
    return out


def _same_target(pending_args: dict[str, Any], args: dict[str, Any]) -> bool:
    a, b = _normalized(pending_args), _normalized(args)
    if a == b:
        return True
    # Lease hours, wait flags, etc. may differ between the blocked call and
    # the retry; the resource identity is what the user confirmed.
    for key in ("slice_name", "name", "path", "lease_id", "instance_id", "xdc", "node_name"):
        if key in a or key in b:
            return a.get(key) == b.get(key)
    return False


def record_pending(conversation_id: str, tool: str, args: dict[str, Any] | None) -> None:
    """Remember the destructive call that was just blocked so the user's next
    "yes" can authorize exactly it."""
    if not conversation_id or not tool:
        return
    with _lock:
        _pending[conversation_id] = PendingAction(tool, dict(args or {}), time.time())


def pending_for(conversation_id: str) -> PendingAction | None:
    if not conversation_id:
        return None
    with _lock:
        action = _pending.get(conversation_id)
        if action is None:
            return None
        if time.time() - action.created_at > PENDING_TTL_SECONDS:
            del _pending[conversation_id]
            return None
        return action


def clear_pending(conversation_id: str) -> None:
    if not conversation_id:
        return
    with _lock:
        _pending.pop(conversation_id, None)


def consume_if_confirmed(
    conversation_id: str,
    latest_user_text: str,
    tool: str,
    args: dict[str, Any] | None,
) -> bool:
    """True, and the pending record is cleared, when the latest user turn is a
    bare confirmation of the pending action and *tool*/*args* are that action."""
    action = pending_for(conversation_id)
    if action is None or action.tool != tool:
        return False
    if not _same_target(action.args, args or {}):
        return False
    if not is_bare_confirmation(latest_user_text):
        return False
    clear_pending(conversation_id)
    return True


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------

def is_destructive_tool_authorized(
    tool: str,
    args: dict[str, Any] | None,
    *,
    user_texts: list[str],
    latest_user_text: str,
    created_slices: set[str],
    conversation_id: str = "",
) -> bool:
    """Decide whether the conversation has authorized this destructive call."""
    args = args or {}
    if consume_if_confirmed(conversation_id, latest_user_text, tool, args):
        return True

    if tool == "submit_slice":
        slice_name = str(args.get("slice_name") or "").strip().lower()
        created_here = bool(slice_name and slice_name in created_slices)
        # A slice the user asked to build-and-prove in this chat may be
        # submitted on a later turn; a cold submit needs the latest turn to
        # ask for it. Either way some user turn must have asked.
        return (
            (created_here or text_authorizes_provisioning(latest_user_text))
            and conversation_authorizes_provisioning(user_texts)
        )

    if tool == "delete_slice":
        return text_confirms_destruction(latest_user_text, [str(args.get("slice_name") or "")])

    # Any other destructive tool: the latest turn must confirm it by name.
    targets = [str(v) for v in args.values() if isinstance(v, str) and v.strip()][:1]
    return text_confirms_destruction(latest_user_text, targets)


def confirmation_instruction(tool: str, args: dict[str, Any] | None) -> str:
    """What the assistant should tell the user when an action is blocked."""
    target = ""
    for value in (args or {}).values():
        if isinstance(value, str) and value.strip():
            target = value.strip()
            break
    what = f"{tool} on '{target}'" if target else tool
    return (
        f"{what} needs the user's confirmation. Ask them to reply 'yes' to "
        f"confirm; a plain 'yes' on their next message authorizes exactly this "
        f"action. Do not retry the tool before they answer."
    )
