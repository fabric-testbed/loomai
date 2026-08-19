"""Persistent LoomAI chat-session state."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from app.user_context import get_user_storage

_SESSION_SUBDIR = os.path.join(".loomai", "chat_sessions")
_MAX_SESSION_MESSAGES = 240


def _safe_session_id(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.:-]+", "-", session_id.strip())
    safe = safe.strip(".-")
    return safe[:120]


def _sessions_dir() -> str:
    path = os.path.join(get_user_storage(), _SESSION_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def _session_path(session_id: str) -> str:
    safe = _safe_session_id(session_id)
    if not safe:
        raise ValueError("empty chat session id")
    return os.path.join(_sessions_dir(), f"{safe}.json")


def normalize_session_id(session_id: Any) -> str:
    if not isinstance(session_id, str):
        return ""
    return _safe_session_id(session_id)


def load_chat_session(session_id: str) -> dict[str, Any] | None:
    safe = normalize_session_id(session_id)
    if not safe:
        return None
    path = _session_path(safe)
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    messages = data.get("messages")
    if not isinstance(messages, list):
        return None
    return data


def _strip_system_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stripped: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "system":
            continue
        if message.get("type") == "message" and message.get("role") == "system":
            continue
        stripped.append(message)
    return stripped[-_MAX_SESSION_MESSAGES:]


def save_chat_session(
    session_id: str,
    messages: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> None:
    safe = normalize_session_id(session_id)
    if not safe:
        return
    path = _session_path(safe)
    payload = {
        "session_id": safe,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "metadata": metadata or {},
        "messages": _strip_system_messages(messages),
    }
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(payload, f, default=str)
    os.replace(tmp_path, path)


def delete_chat_session(session_id: str) -> None:
    safe = normalize_session_id(session_id)
    if not safe:
        return
    try:
        os.remove(_session_path(safe))
    except FileNotFoundError:
        return
