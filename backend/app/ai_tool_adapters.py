"""Deterministic adapters from canonical LoomAI AI assets to tool files."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from typing import Iterable

from app.ai_assets import parse_markdown_asset, serialize_markdown_asset


_MANAGED_ASSET_MANIFEST = ".loomai-managed-assets.json"


@dataclass(frozen=True)
class ToolAsset:
    """Parsed AI asset ready for tool-specific rendering."""

    asset_id: str
    filename: str
    metadata: dict
    body: str
    source_path: str
    source: str


def _default_metadata(asset_id: str, metadata: dict, asset_type: str) -> dict:
    normalized = dict(metadata)
    normalized.setdefault("id", asset_id)
    normalized.setdefault("name", normalized.get("id", asset_id))
    normalized.setdefault("asset_type", asset_type)
    normalized.setdefault("audience", "end-user")
    normalized.setdefault("description", "")
    return normalized


def load_tool_assets(
    builtin_dir: str,
    *,
    custom_dir: str | None = None,
    asset_type: str,
    excluded_ids: Iterable[str] = (),
) -> list[ToolAsset]:
    """Load built-in assets and overlay user-custom assets by filename stem."""
    excluded = set(excluded_ids)
    by_id: dict[str, ToolAsset] = {}

    def _ingest(asset_dir: str, source: str) -> None:
        if not asset_dir or not os.path.isdir(asset_dir):
            return
        for fname in sorted(os.listdir(asset_dir)):
            if not fname.endswith(".md"):
                continue
            asset_id = fname[:-3]
            if asset_id in excluded:
                continue
            path = os.path.join(asset_dir, fname)
            try:
                with open(path) as f:
                    content = f.read()
            except OSError:
                continue
            parsed = parse_markdown_asset(content)
            metadata = _default_metadata(asset_id, parsed.metadata, asset_type)
            by_id[asset_id] = ToolAsset(
                asset_id=asset_id,
                filename=fname,
                metadata=metadata,
                body=parsed.body.strip(),
                source_path=path,
                source=source,
            )

    _ingest(builtin_dir, "built-in")
    if custom_dir:
        _ingest(custom_dir, "custom")
    return [by_id[asset_id] for asset_id in sorted(by_id)]


def render_canonical_markdown(asset: ToolAsset) -> str:
    """Render an asset with canonical frontmatter plus body."""
    return serialize_markdown_asset(asset.metadata, asset.body)


def render_body_only(asset: ToolAsset) -> str:
    """Render an asset body without frontmatter."""
    return asset.body.rstrip() + "\n"


def write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _read_managed_assets(dst_dir: str) -> set[str]:
    manifest_path = os.path.join(dst_dir, _MANAGED_ASSET_MANIFEST)
    try:
        with open(manifest_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, list):
        return set()
    return {item for item in data if isinstance(item, str)}


def _write_managed_assets(dst_dir: str, expected: set[str]) -> None:
    write_text(
        os.path.join(dst_dir, _MANAGED_ASSET_MANIFEST),
        json.dumps(sorted(expected), indent=2) + "\n",
    )


def sync_markdown_files(
    assets: Iterable[ToolAsset],
    dst_dir: str,
    *,
    renderer=render_canonical_markdown,
) -> int:
    """Write one markdown file per asset into dst_dir and prune managed stale files."""
    os.makedirs(dst_dir, exist_ok=True)
    previous = _read_managed_assets(dst_dir)
    expected = set()
    count = 0
    for asset in assets:
        fname = f"{asset.asset_id}.md"
        expected.add(fname)
        write_text(os.path.join(dst_dir, fname), renderer(asset))
        count += 1

    for fname in previous - expected:
        path = os.path.join(dst_dir, fname)
        if fname.endswith(".md") and os.path.isfile(path):
            os.remove(path)
    _write_managed_assets(dst_dir, expected)
    return count


def sync_skill_directories(
    assets: Iterable[ToolAsset],
    dst_dir: str,
    *,
    renderer=render_canonical_markdown,
) -> int:
    """Write tool skill directories shaped as <dst>/<id>/SKILL.md."""
    os.makedirs(dst_dir, exist_ok=True)
    previous = _read_managed_assets(dst_dir)
    expected = set()
    count = 0
    for asset in assets:
        expected.add(asset.asset_id)
        write_text(os.path.join(dst_dir, asset.asset_id, "SKILL.md"), renderer(asset))
        count += 1

    for name in previous - expected:
        path = os.path.join(dst_dir, name)
        if os.path.isdir(path) and name not in expected and os.path.isfile(os.path.join(path, "SKILL.md")):
            shutil.rmtree(path)
    _write_managed_assets(dst_dir, expected)
    return count


def render_asset_index(skills: Iterable[ToolAsset], agents: Iterable[ToolAsset]) -> str:
    """Render a compact read-only index for tools without native adapters."""
    lines = [
        "# LoomAI AI Asset Index",
        "",
        "This file is generated from `ai-tools/shared/` plus user-custom assets in Settings.",
        "Use `AGENTS.md` for execution guidance; use this file to discover available skills and agents.",
        "",
        "## Skills",
        "",
    ]
    for asset in skills:
        description = str(asset.metadata.get("description", "")).strip()
        domains = asset.metadata.get("domains") or []
        domain_text = f" Domains: {', '.join(domains)}." if isinstance(domains, list) and domains else ""
        lines.append(f"- `{asset.asset_id}` ({asset.source}): {description}.{domain_text}")

    lines.extend(["", "## Agents", ""])
    for asset in agents:
        description = str(asset.metadata.get("description", "")).strip()
        domains = asset.metadata.get("domains") or []
        domain_text = f" Domains: {', '.join(domains)}." if isinstance(domains, list) and domains else ""
        lines.append(f"- `{asset.asset_id}` ({asset.source}): {description}.{domain_text}")

    return "\n".join(lines).rstrip() + "\n"
