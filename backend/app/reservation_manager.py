"""Future reservation management for scheduled slice submissions.

Stores reservations in a JSON file and provides a background checker
that auto-submits slices when their scheduled time arrives.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_RESERVATIONS_FILE: str | None = None


def _get_reservations_file() -> str:
    global _RESERVATIONS_FILE
    if _RESERVATIONS_FILE is None:
        from app import settings_manager
        root = settings_manager.get_root_storage_dir()
        _RESERVATIONS_FILE = os.path.join(root, ".loomai", "reservations.json")
    return _RESERVATIONS_FILE


def load_reservations() -> list[dict[str, Any]]:
    """Load all reservations from disk."""
    path = _get_reservations_file()
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load reservations: %s", e)
        return []


def save_reservations(reservations: list[dict[str, Any]]) -> None:
    """Persist reservations to disk."""
    path = _get_reservations_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(reservations, f, indent=2)


def add_reservation(data: dict[str, Any]) -> dict[str, Any]:
    """Create a new reservation and persist it."""
    reservations = load_reservations()
    reservation: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "slice_name": data["slice_name"],
        "scheduled_time": data["scheduled_time"],
        "duration_hours": data.get("duration_hours", 24),
        "auto_submit": data.get("auto_submit", True),
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }
    reservations.append(reservation)
    save_reservations(reservations)
    return reservation


def cancel_reservation(reservation_id: str) -> bool:
    """Cancel (remove) a reservation by ID. Returns True if found."""
    reservations = load_reservations()
    original_len = len(reservations)
    reservations = [r for r in reservations if r["id"] != reservation_id]
    if len(reservations) < original_len:
        save_reservations(reservations)
        return True
    return False


def check_and_execute_reservations() -> list[dict[str, Any]]:
    """Check for pending reservations that are due and execute them.

    Called periodically from the background task in main.py.
    Returns the list of reservations that were processed.
    """
    reservations = load_reservations()
    now = datetime.now(timezone.utc)
    executed: list[dict[str, Any]] = []

    for res in reservations:
        if res["status"] != "pending":
            continue
        try:
            scheduled = datetime.fromisoformat(
                res["scheduled_time"].replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            continue

        if scheduled > now:
            continue

        # Time has arrived
        try:
            if res["auto_submit"]:
                from app.fablib_manager import get_fablib, is_configured

                if is_configured():
                    fablib = get_fablib()
                    slice_obj = fablib.get_slice(name=res["slice_name"])
                    slice_obj.submit(wait=False)
                    res["status"] = "active"
                    logger.info(
                        "Auto-submitted slice %s for reservation %s",
                        res["slice_name"],
                        res["id"],
                    )
                else:
                    res["status"] = "failed"
                    res["error"] = "FABlib not configured"
            else:
                res["status"] = "active"

            executed.append(res)
        except Exception as e:
            res["status"] = "failed"
            res["error"] = str(e)
            logger.error(
                "Failed to auto-submit reservation %s: %s", res["id"], e
            )
            executed.append(res)

    if executed:
        save_reservations(reservations)
    return executed
