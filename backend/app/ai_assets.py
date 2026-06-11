"""Helpers for LoomAI AI asset Markdown metadata.

Canonical assets use standard Markdown/YAML frontmatter:

---
id: create-weave
name: Create Weave
description: Create a reusable LoomAI weave artifact
tools:
  - loomai
  - claude-code
---

The parser also accepts the legacy LoomAI format used by existing assets:

name: create-weave
description: Create a reusable LoomAI weave artifact
---

...
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re


VALID_ASSET_TYPES = frozenset({"prompt", "agent", "skill", "example", "runbook", "eval"})
VALID_AUDIENCES = frozenset({"developer", "end-user", "both"})
VALID_TOOLS = frozenset(
    {
        "loomai",
        "claude-code",
        "codex",
        "opencode",
        "aider",
        "crush",
        "deepagents",
        "antigravity",
        "jupyter-ai",
    }
)
_ASSET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass
class MarkdownAsset:
    """Parsed Markdown asset metadata plus body."""

    metadata: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    style: str = "plain"


def _clean_scalar(value: str) -> str:
    """Return a lightly unquoted YAML-ish scalar value."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_simple_frontmatter(header: str) -> dict[str, Any]:
    """Parse the subset of YAML frontmatter LoomAI assets need.

    This intentionally supports only simple scalar keys and top-level lists.
    It avoids adding PyYAML as a runtime dependency for prompt metadata.
    """
    metadata: dict[str, Any] = {}
    current_list_key: str | None = None

    for raw_line in header.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if current_list_key and stripped.startswith("- "):
            value = _clean_scalar(stripped[2:])
            existing = metadata.setdefault(current_list_key, [])
            if isinstance(existing, list):
                existing.append(value)
            continue

        current_list_key = None
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if not key:
            continue

        value = raw_value.strip()
        if value == "":
            metadata[key] = []
            current_list_key = key
        elif value.startswith("[") and value.endswith("]"):
            items = [
                _clean_scalar(item)
                for item in value[1:-1].split(",")
                if item.strip()
            ]
            metadata[key] = items
        else:
            metadata[key] = _clean_scalar(value)

    return metadata


def parse_markdown_asset(content: str) -> MarkdownAsset:
    """Parse canonical or legacy LoomAI AI asset Markdown."""
    lines = content.splitlines()

    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                header = "\n".join(lines[1:i])
                body = "\n".join(lines[i + 1 :]).lstrip()
                return MarkdownAsset(
                    metadata=_parse_simple_frontmatter(header),
                    body=body,
                    style="frontmatter",
                )
        return MarkdownAsset(metadata={}, body=content, style="plain")

    if lines and ":" in lines[0] and lines[0].split(":", 1)[0].strip():
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                header = "\n".join(lines[:i])
                body = "\n".join(lines[i + 1 :]).lstrip()
                return MarkdownAsset(
                    metadata=_parse_simple_frontmatter(header),
                    body=body,
                    style="legacy",
                )

    return MarkdownAsset(metadata={}, body=content, style="plain")


def serialize_markdown_asset(metadata: dict[str, Any], body: str) -> str:
    """Serialize a Markdown asset with canonical frontmatter."""
    lines = ["---"]
    for key, value in metadata.items():
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append(body.strip())
    return "\n".join(lines).rstrip() + "\n"


def validate_markdown_asset(
    content: str,
    *,
    filename_stem: str | None = None,
    require_canonical: bool = False,
) -> list[str]:
    """Return validation errors for a canonical AI asset Markdown file."""
    parsed = parse_markdown_asset(content)
    metadata = parsed.metadata
    errors: list[str] = []

    if require_canonical and parsed.style != "frontmatter":
        errors.append("asset must use canonical '---' Markdown frontmatter")

    for key in ("id", "name", "asset_type", "audience", "description"):
        value = metadata.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"missing required field: {key}")

    asset_id = metadata.get("id")
    if isinstance(asset_id, str) and asset_id:
        if not _ASSET_ID_RE.match(asset_id):
            errors.append("id must use lowercase letters, digits, and hyphens")
        if filename_stem and asset_id != filename_stem:
            errors.append(f"id must match filename stem '{filename_stem}'")

    asset_type = metadata.get("asset_type")
    if isinstance(asset_type, str) and asset_type and asset_type not in VALID_ASSET_TYPES:
        errors.append(f"invalid asset_type: {asset_type}")

    audience = metadata.get("audience")
    if isinstance(audience, str) and audience and audience not in VALID_AUDIENCES:
        errors.append(f"invalid audience: {audience}")

    for key in ("domains", "tools", "triggers", "source_paths", "generated_outputs", "eval_cases"):
        if key not in metadata:
            continue
        value = metadata[key]
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            errors.append(f"{key} must be a list of non-empty strings")

    tools = metadata.get("tools")
    if isinstance(tools, list):
        invalid_tools = sorted({tool for tool in tools if isinstance(tool, str) and tool not in VALID_TOOLS})
        if invalid_tools:
            errors.append(f"invalid tools: {', '.join(invalid_tools)}")

    if not parsed.body.strip():
        errors.append("asset body must not be empty")

    return errors
