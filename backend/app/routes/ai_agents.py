"""CRUD API for AI agents and skills.

Built-in agents/skills live in ai-tools/shared/agents/ and ai-tools/shared/skills/.
User-custom overrides live in {STORAGE_DIR}/.loomai/agents/ and .loomai/skills/.
User-custom files override built-in files with the same id (filename stem).
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai-agents"])

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_BUILTIN_AGENTS_DIR = os.path.join(_APP_ROOT, "ai-tools", "shared", "agents")
_BUILTIN_SKILLS_DIR = os.path.join(_APP_ROOT, "ai-tools", "shared", "skills")

# Ids excluded from listing
_EXCLUDED_AGENT_IDS = frozenset({"ai-tools-evaluator"})
_EXCLUDED_SKILL_IDS = frozenset({"compact", "help"})

_ID_PATTERN = re.compile(r"^[a-z0-9-]+$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _storage_dir() -> str:
    from app.settings_manager import get_storage_dir
    return get_storage_dir()


def _custom_agents_dir() -> str:
    return os.path.join(_storage_dir(), ".loomai", "agents")


def _custom_skills_dir() -> str:
    return os.path.join(_storage_dir(), ".loomai", "skills")


def _validate_id(item_id: str) -> None:
    """Raise 400 if the id contains disallowed characters."""
    if not _ID_PATTERN.match(item_id):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid id '{item_id}': only lowercase letters, digits, and hyphens are allowed.",
        )


def _parse_md_file(fpath: str) -> dict[str, str]:
    """Parse a YAML-frontmatter .md file into name, description, and body."""
    with open(fpath, "r") as f:
        content = f.read()

    name = ""
    description = ""
    body = content

    if content.startswith("name:"):
        parts = content.split("---", 1)
        header = parts[0]
        body = parts[1].strip() if len(parts) > 1 else ""
        for line in header.strip().splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("description:"):
                description = line.split(":", 1)[1].strip()

    return {"name": name, "description": description, "body": body}


def _serialize_md(name: str, description: str, body: str) -> str:
    """Serialize back to the frontmatter .md format."""
    return f"name: {name}\ndescription: {description}\n---\n{body}\n"


def _load_all(
    builtin_dir: str,
    custom_dir: str,
    excluded_ids: frozenset[str],
) -> dict[str, dict[str, Any]]:
    """Load and merge built-in + user-custom items.

    Returns dict keyed by id with keys: name, description, source, body.
    """
    items: dict[str, dict[str, Any]] = {}

    # 1. Load built-in
    if os.path.isdir(builtin_dir):
        for fname in sorted(os.listdir(builtin_dir)):
            if not fname.endswith(".md"):
                continue
            item_id = fname[:-3]
            if item_id in excluded_ids:
                continue
            try:
                parsed = _parse_md_file(os.path.join(builtin_dir, fname))
                items[item_id] = {
                    "name": parsed["name"] or item_id,
                    "description": parsed["description"],
                    "source": "built-in",
                    "body": parsed["body"],
                }
            except Exception:
                logger.warning("Failed to load built-in %s/%s", builtin_dir, fname)

    # 2. Overlay user-custom
    if os.path.isdir(custom_dir):
        for fname in sorted(os.listdir(custom_dir)):
            if not fname.endswith(".md"):
                continue
            item_id = fname[:-3]
            if item_id in excluded_ids:
                continue
            try:
                parsed = _parse_md_file(os.path.join(custom_dir, fname))
                source: str = "customized" if item_id in items else "custom"
                items[item_id] = {
                    "name": parsed["name"] or item_id,
                    "description": parsed["description"],
                    "source": source,
                    "body": parsed["body"],
                }
            except Exception:
                logger.warning("Failed to load custom %s/%s", custom_dir, fname)

    return items


def _after_write() -> None:
    """Invalidate caches and propagate config changes after a write."""
    # Invalidate the agents cache used by the chat system
    from app.routes.ai_chat import invalidate_agents_cache
    invalidate_agents_cache()

    # Re-seed AI tool configs in a background thread so we don't block the response
    def _propagate():
        try:
            from app.routes.ai_terminal import propagate_ai_configs
            propagate_ai_configs()
        except Exception:
            logger.warning("propagate_ai_configs failed (non-fatal)", exc_info=True)

    threading.Thread(target=_propagate, daemon=True).start()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class AgentSkillBody(BaseModel):
    name: str
    description: str
    content: str  # The prompt body (markdown)


# ---------------------------------------------------------------------------
# Agent endpoints
# ---------------------------------------------------------------------------


@router.get("/agents")
async def list_agents():
    """List all agents (merged built-in + user custom)."""
    items = _load_all(_BUILTIN_AGENTS_DIR, _custom_agents_dir(), _EXCLUDED_AGENT_IDS)
    return [
        {"id": aid, "name": info["name"], "description": info["description"], "source": info["source"]}
        for aid, info in items.items()
    ]


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    """Get a single agent with full content."""
    _validate_id(agent_id)
    items = _load_all(_BUILTIN_AGENTS_DIR, _custom_agents_dir(), _EXCLUDED_AGENT_IDS)
    if agent_id not in items:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    info = items[agent_id]
    return {
        "id": agent_id,
        "name": info["name"],
        "description": info["description"],
        "source": info["source"],
        "content": info["body"],
    }


@router.put("/agents/{agent_id}")
async def put_agent(agent_id: str, body: AgentSkillBody):
    """Create or update a user-custom agent."""
    _validate_id(agent_id)
    if agent_id in _EXCLUDED_AGENT_IDS:
        raise HTTPException(status_code=400, detail=f"Agent id '{agent_id}' is reserved")

    custom_dir = _custom_agents_dir()
    os.makedirs(custom_dir, exist_ok=True)

    fpath = os.path.join(custom_dir, f"{agent_id}.md")
    md_content = _serialize_md(body.name, body.description, body.content)
    with open(fpath, "w") as f:
        f.write(md_content)

    # Determine source
    builtin_path = os.path.join(_BUILTIN_AGENTS_DIR, f"{agent_id}.md")
    source = "customized" if os.path.isfile(builtin_path) else "custom"

    _after_write()
    return {"id": agent_id, "name": body.name, "description": body.description, "source": source}


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Delete a user-custom agent. Cannot delete built-in agents."""
    _validate_id(agent_id)
    custom_path = os.path.join(_custom_agents_dir(), f"{agent_id}.md")

    if not os.path.isfile(custom_path):
        # Check if it's a built-in
        builtin_path = os.path.join(_BUILTIN_AGENTS_DIR, f"{agent_id}.md")
        if os.path.isfile(builtin_path):
            raise HTTPException(status_code=400, detail="Cannot delete a built-in agent. Use reset instead.")
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    os.remove(custom_path)
    _after_write()
    return {"deleted": agent_id}


@router.post("/agents/{agent_id}/reset")
async def reset_agent(agent_id: str):
    """Reset a customized built-in agent back to default.

    Removes the user-custom override so the built-in version is used again.
    """
    _validate_id(agent_id)
    builtin_path = os.path.join(_BUILTIN_AGENTS_DIR, f"{agent_id}.md")
    if not os.path.isfile(builtin_path):
        raise HTTPException(status_code=400, detail=f"Agent '{agent_id}' is not a built-in agent")

    custom_path = os.path.join(_custom_agents_dir(), f"{agent_id}.md")
    if os.path.isfile(custom_path):
        os.remove(custom_path)
        _after_write()

    # Return the built-in version
    parsed = _parse_md_file(builtin_path)
    return {
        "id": agent_id,
        "name": parsed["name"] or agent_id,
        "description": parsed["description"],
        "source": "built-in",
        "content": parsed["body"],
    }


# ---------------------------------------------------------------------------
# Skill endpoints
# ---------------------------------------------------------------------------


@router.get("/skills")
async def list_skills():
    """List all skills (merged built-in + user custom)."""
    items = _load_all(_BUILTIN_SKILLS_DIR, _custom_skills_dir(), _EXCLUDED_SKILL_IDS)
    return [
        {"id": sid, "name": info["name"], "description": info["description"], "source": info["source"]}
        for sid, info in items.items()
    ]


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str):
    """Get a single skill with full content."""
    _validate_id(skill_id)
    items = _load_all(_BUILTIN_SKILLS_DIR, _custom_skills_dir(), _EXCLUDED_SKILL_IDS)
    if skill_id not in items:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    info = items[skill_id]
    return {
        "id": skill_id,
        "name": info["name"],
        "description": info["description"],
        "source": info["source"],
        "content": info["body"],
    }


@router.put("/skills/{skill_id}")
async def put_skill(skill_id: str, body: AgentSkillBody):
    """Create or update a user-custom skill."""
    _validate_id(skill_id)
    if skill_id in _EXCLUDED_SKILL_IDS:
        raise HTTPException(status_code=400, detail=f"Skill id '{skill_id}' is reserved")

    custom_dir = _custom_skills_dir()
    os.makedirs(custom_dir, exist_ok=True)

    fpath = os.path.join(custom_dir, f"{skill_id}.md")
    md_content = _serialize_md(body.name, body.description, body.content)
    with open(fpath, "w") as f:
        f.write(md_content)

    builtin_path = os.path.join(_BUILTIN_SKILLS_DIR, f"{skill_id}.md")
    source = "customized" if os.path.isfile(builtin_path) else "custom"

    _after_write()
    return {"id": skill_id, "name": body.name, "description": body.description, "source": source}


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str):
    """Delete a user-custom skill. Cannot delete built-in skills."""
    _validate_id(skill_id)
    custom_path = os.path.join(_custom_skills_dir(), f"{skill_id}.md")

    if not os.path.isfile(custom_path):
        builtin_path = os.path.join(_BUILTIN_SKILLS_DIR, f"{skill_id}.md")
        if os.path.isfile(builtin_path):
            raise HTTPException(status_code=400, detail="Cannot delete a built-in skill. Use reset instead.")
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    os.remove(custom_path)
    _after_write()
    return {"deleted": skill_id}


@router.post("/skills/{skill_id}/reset")
async def reset_skill(skill_id: str):
    """Reset a customized built-in skill back to default.

    Removes the user-custom override so the built-in version is used again.
    """
    _validate_id(skill_id)
    builtin_path = os.path.join(_BUILTIN_SKILLS_DIR, f"{skill_id}.md")
    if not os.path.isfile(builtin_path):
        raise HTTPException(status_code=400, detail=f"Skill '{skill_id}' is not a built-in skill")

    custom_path = os.path.join(_custom_skills_dir(), f"{skill_id}.md")
    if os.path.isfile(custom_path):
        os.remove(custom_path)
        _after_write()

    parsed = _parse_md_file(builtin_path)
    return {
        "id": skill_id,
        "name": parsed["name"] or skill_id,
        "description": parsed["description"],
        "source": "built-in",
        "content": parsed["body"],
    }
