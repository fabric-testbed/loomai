"""Generate default external-harness configs from LoomAI shared AI assets.

This module is intentionally dependency-light so it can run at image build and
again at backend startup. Existing config values win over generated defaults:
the generator fills missing providers, agents, commands, and permission blocks
without clobbering user-owned values.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from app.ai_assets import parse_markdown_asset
from app.model_capability_defaults import harness_model_config, harness_models_for_provider

if TYPE_CHECKING:
    from app.mcp_registry import MCPServer


APP_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SHARED_ROOT = APP_ROOT / "ai-tools" / "shared"
DEFAULT_WORKSPACE = Path(os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work"))
DEFAULT_HOME = Path(os.environ.get("HOME", "/home/fabric"))

MANAGED_TEXT_MARKER = "<!-- LoomAI-managed harness default; user files with no marker are preserved. -->"
MANAGED_TOML_MARKER = "# LoomAI-managed harness default; user files with no marker are preserved."
MANAGED_CODE_MARKER = "// LoomAI-managed harness default; user files with no marker are preserved."
MANAGED_SHELL_MARKER = "# LoomAI-managed harness default; user files with no marker are preserved."
PI_PACKAGE_VERSION = "0.80.3"
PI_MCP_ADAPTER_VERSION = "2.10.0"
PI_PERMISSION_SYSTEM_VERSION = "16.0.1"
PI_SUBAGENTS_VERSION = "0.33.1"
PI_WEB_ACCESS_VERSION = "0.10.7"
PI_LSP_VERSION = "0.0.3"
PI_PYRIGHT_VERSION = "1.1.411"
PI_EXTENSION_PACKAGES: tuple[tuple[str, str, str], ...] = (
    ("pi-mcp-adapter", PI_MCP_ADAPTER_VERSION, "index.ts"),
    ("@gotgenes/pi-permission-system", PI_PERMISSION_SYSTEM_VERSION, "src/index.ts"),
    ("pi-subagents", PI_SUBAGENTS_VERSION, "src/extension/index.ts"),
    ("pi-web-access", PI_WEB_ACCESS_VERSION, "index.ts"),
    ("@lebronj/pi-lsp", PI_LSP_VERSION, "dist/index.js"),
)
PUBLIC_MANAGED_HARNESSES: tuple[str, ...] = (
    "opencode",
    "goose",
    "pi",
    "aider",
    "crush",
    "codex",
    "claude",
)
ALL_MANAGED_HARNESSES: tuple[str, ...] = (*PUBLIC_MANAGED_HARNESSES, "antigravity")
HARNESS_ALIASES = {
    "claude-code": "claude",
    "claude_code": "claude",
    "claudecode": "claude",
    "open-code": "opencode",
    "pi.dev": "pi",
}
HARNESS_METADATA: dict[str, dict[str, str]] = {
    "opencode": {
        "label": "OpenCode",
        "description": "Terminal coding harness with provider, agent, skill, and MCP defaults.",
    },
    "goose": {
        "label": "Goose",
        "description": "Goose workspace profile with LoomAI providers and instructions.",
    },
    "pi": {
        "label": "Pi",
        "description": "Minimal Pi terminal harness with provider, MCP adapter, subagent, web, LSP, and permission defaults.",
    },
    "aider": {
        "label": "Aider",
        "description": "Aider pair-programming defaults and shared LoomAI conventions.",
    },
    "crush": {
        "label": "Crush",
        "description": "Crush TUI defaults with shared agents, skills, and provider settings.",
    },
    "codex": {
        "label": "Codex",
        "description": "Codex CLI defaults with LoomAI providers, agents, and skills.",
    },
    "claude": {
        "label": "Claude Code",
        "description": "Claude Code instructions, slash-command, and agent defaults.",
    },
    "antigravity": {
        "label": "Antigravity",
        "description": "Antigravity workspace instructions, agents, and skills.",
    },
}

_HARNESS_FILE_SPECS: dict[str, dict[str, list[str]]] = {
    "opencode": {
        "workspace_files": ["opencode.json", "opencode/AGENTS.md"],
        "workspace_globs": [
            ".opencode/mcp-scripts/*.sh",
            ".opencode/agent-prompts/*.md",
            ".opencode/skills/*/SKILL.md",
        ],
        "home_files": [],
        "home_globs": [],
    },
    "goose": {
        "workspace_files": ["goose/AGENTS.md", ".config/goose/config.yaml"],
        "workspace_globs": [".goose/agents/*.md", ".goose/skills/*/SKILL.md"],
        "home_files": [".config/goose/config.yaml"],
        "home_globs": [],
    },
    "pi": {
        "workspace_files": [".pi/extensions/pi-permission-system/config.json"],
        "workspace_globs": ["pi/**/*"],
        "home_files": [
            ".local/bin/pi-fabric",
            ".pi/agent/models.json",
            ".pi/agent/settings.json",
            ".pi/agent/mcp.json",
            ".pi/agent/lsp.json",
            ".pi/agent/web-search.json",
            ".pi/agent/extensions/loomai-surface-guard.ts",
            ".pi/agent/extensions/pi-permission-system/config.json",
        ],
        "home_globs": [".pi/agent/skills/*/SKILL.md"],
    },
    "aider": {
        "workspace_files": ["CONVENTIONS.md", ".aider.conf.yml", ".aiderignore"],
        "workspace_globs": [],
        "home_files": [".aider.conf.yml", ".aiderignore"],
        "home_globs": [],
    },
    "crush": {
        "workspace_files": ["CRUSH.md", ".crush.json"],
        "workspace_globs": [".crush/skills/*.md", ".crush/agents/*.md"],
        "home_files": [".config/crush/crush.json"],
        "home_globs": [],
    },
    "codex": {
        "workspace_files": ["codex/AGENTS.md"],
        "workspace_globs": [".codex/skills/*/SKILL.md", ".codex/agents/*.md"],
        "home_files": [".codex/config.toml"],
        "home_globs": [],
    },
    "claude": {
        "workspace_files": ["CLAUDE.md", ".mcp.json"],
        "workspace_globs": [".claude/commands/*.md", ".claude/agents/*.md"],
        "home_files": [".claude/CLAUDE.md"],
        "home_globs": [],
    },
    "antigravity": {
        "workspace_files": ["antigravity/AGENTS.md"],
        "workspace_globs": [".antigravity/skills/*.md", ".antigravity/agents/*.md"],
        "home_files": [],
        "home_globs": [],
    },
}

HARNESS_CONTRACT = """\
## LoomAI External Harness Operating Contract

Use this contract for Codex, OpenCode, Goose, Aider, Crush, Claude Code, and
other external harnesses launched from the LoomAI container.

- Prefer the `loomai` CLI and the LoomAI backend REST API at
  `http://localhost:8000`; do not bypass LoomAI with raw FABlib unless the user
  explicitly asks for lower-level debugging.
- For benchmark or automated validation work, create only resources whose
  names begin with `bench-`.
- Use 6-hour leases for every create, submit, renew, or weave-run workflow
  unless the user gives a different duration. The LoomAI backend caps
  agent-initiated leases at the user's Agent Lease Limit (default 6 hours);
  if a renew is refused for exceeding it, tell the user they can renew from
  the LoomAI UI or raise the limit in Configure.
- Never use FABRIC sites EDC or EDUKY.
- When running compound VM commands through `loomai exec` or REST execution,
  wrap them as `bash -lc '<command>'`.
- Before claiming success, include real verification output such as slice
  state, ping, curl, iperf, SSH command output, or background-run output.
- Before running or publishing a newly authored artifact, call the read-only
  artifact checker: `POST /api/artifacts/validate` (or the `validate_artifact`
  MCP tool) with `dir_name` or inline `weave_json`/`scripts`; fix any errors
  before `run_weave` or `publish_artifact`.
- For destructive actions, act only on the exact requested slice or artifact
  and require scoped confirmation for delete/recreate operations.
- Harness config files under `/home/fabric/work` and `/home/fabric` are
  LoomAI-generated defaults. Put user-specific overrides in those runtime files;
  `loomai tools sync` preserves unowned keys and user files while restoring
  LoomAI-managed defaults.
- Run `loomai tools sync` (or `loomai ai tools sync`) after changing AI assets,
  repairing harness setup, or switching users. The generated mapping is
  `/home/fabric/work/.loomai/harness-defaults/MAPPING.md`.
- In the WebUI, Settings > AI Tools > Harnesses shows configured,
  user-modified, or stale status and offers per-harness Configure/Sync and
  Docs actions for OpenCode, Goose, Pi, Aider, Crush, Codex, and Claude Code.
"""


AI_RENCI_MODEL_IDS = ["gpt-5.5", "Kimi-K2.6"]
FABRIC_MODEL_IDS = ["qwen3-coder-30b", "gpt-oss-20b", "gemma-4-27b", "nemotron-nano-30b"]
NRP_MODEL_IDS = [
    "minimax-m2",
    "qwen3",
    "glm-5",
    "gemma",
    "gemma-small",
    "gemma-small-e4b",
    "gpt-oss",
    "kimi",
]

FABRIC_MODELS: dict[str, dict[str, Any]] = harness_models_for_provider("fabric", FABRIC_MODEL_IDS)
AI_RENCI_MODELS: dict[str, dict[str, Any]] = harness_models_for_provider("ai-renci", AI_RENCI_MODEL_IDS)
NRP_MODELS: dict[str, dict[str, Any]] = harness_models_for_provider("nrp", NRP_MODEL_IDS)


def _runtime_ai_settings() -> dict[str, Any]:
    """Return current AI settings if available; defaults are fine at image build."""
    try:
        from app.settings_manager import load_settings

        return dict(load_settings().get("ai", {}) or {})
    except Exception:
        return {}


def _model_id_from_entry(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("id") or entry.get("name") or "").strip()
    return str(entry or "").strip()


def _model_entry_map(entries: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(entries, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        model_id = _model_id_from_entry(entry)
        if not model_id:
            continue
        result[model_id] = dict(entry) if isinstance(entry, dict) else {"id": model_id, "name": model_id}
    return result


def _models_from_entries(entries: Any) -> list[str]:
    return list(_model_entry_map(entries).keys())


def _provider_v1_url(base_url: str) -> str:
    cleaned = str(base_url or "").strip().rstrip("/")
    if not cleaned:
        return ""
    return cleaned if cleaned.endswith("/v1") else f"{cleaned}/v1"


def _custom_provider_id(name: str) -> str:
    return f"custom-{_safe_slug(name).lower()}"


def _custom_provider_env_keys(name: str) -> tuple[str, str]:
    try:
        from app.settings_manager import custom_provider_base_url_env_key, custom_provider_env_key

        return custom_provider_base_url_env_key(name), custom_provider_env_key(name)
    except Exception:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", str(name or "custom").strip()).strip("_").upper()
        slug = slug or "CUSTOM"
        return f"LOOMAI_CUSTOM_PROVIDER_{slug}_BASE_URL", f"LOOMAI_CUSTOM_PROVIDER_{slug}_API_KEY"


def _normalize_endpoint_style(value: Any) -> str:
    try:
        from app.settings_manager import normalize_ai_endpoint_style

        return normalize_ai_endpoint_style(value)
    except Exception:
        lowered = str(value or "auto").strip().lower().replace("_", "-")
        aliases = {"responses-api": "responses", "chat-completions": "chat", "nonchat": "non-chat"}
        return aliases.get(lowered, lowered if lowered in {"auto", "chat", "responses", "non-chat"} else "auto")


def _profile_for_model(model_id: str, provider: str) -> dict[str, Any]:
    try:
        from app.settings_manager import get_model_capability_profile

        profile = get_model_capability_profile(f"{provider}:{model_id}")
        if not profile:
            profile = get_model_capability_profile(model_id)
        return profile if isinstance(profile, dict) else {}
    except Exception:
        return {}


def _apply_capability_profile(model: dict[str, Any], profile: dict[str, Any]) -> None:
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
            model[dest] = profile[src]


def _harness_model_entry(model_id: str, provider: str, discovered: dict[str, Any] | None = None) -> dict[str, Any]:
    model = harness_model_config(model_id, provider)
    profile = _profile_for_model(model_id, provider)
    _apply_capability_profile(model, profile)
    discovered = discovered or {}
    if discovered.get("context_length"):
        model["context_window"] = discovered["context_length"]
    if discovered.get("endpoint_style") and "endpoint_style" not in profile:
        model["endpoint_style"] = _normalize_endpoint_style(discovered["endpoint_style"])
    elif discovered.get("model_type") in {"chat", "responses", "non-chat"} and "endpoint_style" not in profile:
        model["endpoint_style"] = _normalize_endpoint_style(discovered["model_type"])
    if "supports_tools" in discovered:
        model["supports_tools"] = bool(discovered["supports_tools"])
    if discovered.get("tier") and "orchestration_tier" not in model:
        model["orchestration_tier"] = discovered["tier"]
    return model


def _provider_models(provider: str, fallback_ids: list[str], ai_settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
    discovered = ai_settings.get("discovered_models", {}) if isinstance(ai_settings, dict) else {}
    entry_map = _model_entry_map(discovered.get(provider, [])) if isinstance(discovered, dict) else {}
    model_ids = list(entry_map) or list(fallback_ids)
    return {
        model_id: _harness_model_entry(model_id, provider, entry_map.get(model_id))
        for model_id in model_ids
    }


def _custom_model_ids(provider: dict[str, Any], ai_settings: dict[str, Any]) -> tuple[list[str], dict[str, dict[str, Any]]]:
    name = str(provider.get("name") or "custom").strip() or "custom"
    discovered = ai_settings.get("discovered_models", {}) if isinstance(ai_settings, dict) else {}
    custom = discovered.get("custom", {}) if isinstance(discovered, dict) else {}
    entry_map = _model_entry_map(custom.get(name, [])) if isinstance(custom, dict) else {}
    ids = list(entry_map)
    raw_models = provider.get("models")
    if not ids and isinstance(raw_models, list):
        ids = [_model_id_from_entry(item) for item in raw_models]
        ids = [item for item in ids if item]
    raw_model = provider.get("model")
    if not ids and raw_model:
        ids = [str(raw_model)]
    default_model = str(ai_settings.get("default_model") or "")
    default_source = str(ai_settings.get("default_model_source") or "")
    if not ids and default_model and default_source == f"custom:{name}":
        ids = [default_model.split(":", 1)[-1]]
    return ids, entry_map


def _custom_provider_catalog(ai_settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
    providers: dict[str, dict[str, Any]] = {}
    for provider in ai_settings.get("custom_providers", []) or []:
        if not isinstance(provider, dict):
            continue
        name = str(provider.get("name") or "custom").strip() or "custom"
        base_url = _provider_v1_url(provider.get("base_url", ""))
        if not base_url:
            continue
        provider_id = _custom_provider_id(name)
        _base_env, api_env = _custom_provider_env_keys(name)
        model_ids, entry_map = _custom_model_ids(provider, ai_settings)
        endpoint_style = _normalize_endpoint_style(provider.get("endpoint_style"))
        models = {
            model_id: _harness_model_entry(model_id, name, entry_map.get(model_id))
            for model_id in model_ids
        }
        if endpoint_style != "auto":
            for model in models.values():
                model["endpoint_style"] = endpoint_style
        providers[provider_id] = {
            "id": provider_id,
            "label": name,
            "base_url": base_url,
            "api_key_env": api_env,
            "endpoint_style": endpoint_style,
            "models": models,
            "custom": True,
        }
    return providers


def _provider_catalog(ai_settings: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    ai_settings = ai_settings or _runtime_ai_settings()
    fabric_url = _provider_v1_url(ai_settings.get("ai_server_url") or "https://ai.fabric-testbed.net")
    nrp_url = _provider_v1_url(ai_settings.get("nrp_server_url") or "https://ellm.nrp-nautilus.io")
    _ai_renci_base_env, ai_renci_api_env = _custom_provider_env_keys("ai-renci")
    providers = {
        "ai-renci": {
            "id": "ai-renci",
            "label": "ai-renci",
            "base_url": "https://ai-renci.fabric-testbed.net/v1",
            "api_key_env": ai_renci_api_env,
            "endpoint_style": "auto",
            "models": _provider_models("ai-renci", AI_RENCI_MODEL_IDS, ai_settings),
            "custom": False,
        },
        "fabric": {
            "id": "fabric",
            "label": "FABRIC AI",
            "base_url": fabric_url,
            "api_key_env": "FABRIC_AI_API_KEY",
            "endpoint_style": "auto",
            "models": _provider_models("fabric", FABRIC_MODEL_IDS, ai_settings),
            "custom": False,
        },
        "nrp": {
            "id": "nrp",
            "label": "NRP",
            "base_url": nrp_url,
            "api_key_env": "NRP_API_KEY",
            "endpoint_style": "auto",
            "models": _provider_models("nrp", NRP_MODEL_IDS, ai_settings),
            "custom": False,
        },
    }
    providers.update(_custom_provider_catalog(ai_settings))
    return providers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shared-root", type=Path, default=DEFAULT_SHARED_ROOT)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    result = sync_harness_defaults(args.shared_root, args.workspace, args.home)
    if not args.quiet:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def sync_harness_defaults(
    shared_root: Path | str = DEFAULT_SHARED_ROOT,
    workspace: Path | str = DEFAULT_WORKSPACE,
    home: Path | str = DEFAULT_HOME,
    harnesses: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Render default harness configuration into workspace and home paths."""
    shared_root = Path(shared_root)
    workspace = Path(workspace)
    home = Path(home)
    if not shared_root.exists():
        raise FileNotFoundError(f"shared AI asset root not found: {shared_root}")
    workspace.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    selected = _normalize_harnesses(harnesses)

    agents = _load_assets(shared_root / "agents")
    skills = _load_assets(shared_root / "skills")
    fabric_ai = _read_text(shared_root / "FABRIC_AI.md")
    agents_md = _shared_context(fabric_ai)

    _write_managed_text(workspace / "AGENTS.md", agents_md)
    if "opencode" in selected:
        _render_opencode(workspace, agents_md, agents, skills)
    if "aider" in selected:
        _render_aider(workspace, home, agents_md)
    if "crush" in selected:
        _render_crush(workspace, home, agents_md, agents, skills)
    if "goose" in selected:
        _render_goose(workspace, home, agents_md, agents, skills)
    if "pi" in selected:
        _render_pi(workspace, home, agents_md, skills)
    if "codex" in selected:
        _render_codex(workspace, home, agents_md, agents, skills)
    if "claude" in selected:
        _render_claude(workspace, home, agents_md, agents, skills)
    if "antigravity" in selected:
        _render_antigravity(workspace, agents_md, agents, skills)
    _render_mapping(workspace)

    return {
        "workspace": str(workspace),
        "home": str(home),
        "agents": len(agents),
        "skills": len(skills),
        "providers": list(_provider_catalog().keys()),
        "harnesses": list(selected),
    }


def normalize_harness_name(name: str) -> str:
    normalized = HARNESS_ALIASES.get(name.strip().lower(), name.strip().lower())
    if normalized not in ALL_MANAGED_HARNESSES:
        allowed = ", ".join(PUBLIC_MANAGED_HARNESSES)
        raise ValueError(f"unknown managed harness {name!r}; expected one of: {allowed}")
    return normalized


def managed_harnesses() -> list[dict[str, str]]:
    return [
        {
            "name": name,
            "label": HARNESS_METADATA[name]["label"],
            "description": HARNESS_METADATA[name]["description"],
        }
        for name in PUBLIC_MANAGED_HARNESSES
    ]


def harness_statuses(
    shared_root: Path | str = DEFAULT_SHARED_ROOT,
    workspace: Path | str = DEFAULT_WORKSPACE,
    home: Path | str = DEFAULT_HOME,
    harnesses: Iterable[str] | None = None,
) -> dict[str, Any]:
    shared_root = Path(shared_root)
    workspace = Path(workspace)
    home = Path(home)
    selected = _normalize_harnesses(harnesses, default=PUBLIC_MANAGED_HARNESSES)

    with tempfile.TemporaryDirectory(prefix="loomai-harness-canonical-") as tmp:
        tmp_root = Path(tmp)
        canonical_workspace = tmp_root / "work"
        canonical_home = tmp_root / "home"
        sync_harness_defaults(shared_root, canonical_workspace, canonical_home, selected)
        rows = [
            _status_for_harness(name, workspace, home, canonical_workspace, canonical_home)
            for name in selected
            if name in PUBLIC_MANAGED_HARNESSES
        ]

    return {
        "workspace": str(workspace),
        "home": str(home),
        "harnesses": rows,
    }


def harness_status(
    name: str,
    shared_root: Path | str = DEFAULT_SHARED_ROOT,
    workspace: Path | str = DEFAULT_WORKSPACE,
    home: Path | str = DEFAULT_HOME,
) -> dict[str, Any]:
    normalized = normalize_harness_name(name)
    if normalized not in PUBLIC_MANAGED_HARNESSES:
        raise ValueError(f"harness {name!r} is not exposed in Settings")
    statuses = harness_statuses(shared_root, workspace, home, [normalized])
    return statuses["harnesses"][0]


def reset_harness_defaults(
    name: str,
    shared_root: Path | str = DEFAULT_SHARED_ROOT,
    workspace: Path | str = DEFAULT_WORKSPACE,
    home: Path | str = DEFAULT_HOME,
) -> dict[str, Any]:
    """Overwrite one public harness's expected files with canonical defaults."""
    normalized = normalize_harness_name(name)
    if normalized not in PUBLIC_MANAGED_HARNESSES:
        raise ValueError(f"harness {name!r} is not exposed in Settings")

    shared_root = Path(shared_root)
    workspace = Path(workspace)
    home = Path(home)
    workspace.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="loomai-harness-reset-") as tmp:
        tmp_root = Path(tmp)
        canonical_workspace = tmp_root / "work"
        canonical_home = tmp_root / "home"
        sync_harness_defaults(shared_root, canonical_workspace, canonical_home, [normalized])
        files = _expected_harness_files(normalized, workspace, home, canonical_workspace, canonical_home)
        reset_files = 0
        for _root, rel_path, actual_base, canonical_base in files:
            canonical_path = canonical_base / rel_path
            if not canonical_path.is_file():
                continue
            actual_path = actual_base / rel_path
            actual_path.parent.mkdir(parents=True, exist_ok=True)
            text = _normalize_canonical_text(_read_text(canonical_path), actual_base, canonical_base)
            actual_path.write_text(text, encoding="utf-8")
            if _is_executable(canonical_path):
                actual_path.chmod(0o755)
            reset_files += 1

    return {
        "status": "ok",
        "workspace": str(workspace),
        "home": str(home),
        "reset_files": reset_files,
        "harness": harness_status(normalized, shared_root=shared_root, workspace=workspace, home=home),
    }


def cleanup_harness_uninstall(
    name: str,
    *,
    remove_config: bool = False,
    shared_root: Path | str = DEFAULT_SHARED_ROOT,
    workspace: Path | str = DEFAULT_WORKSPACE,
    home: Path | str = DEFAULT_HOME,
) -> dict[str, Any]:
    """Remove safe harness-owned runtime state, and optionally generated config."""
    normalized = normalize_harness_name(name)
    if normalized not in PUBLIC_MANAGED_HARNESSES:
        return {"removed_paths": [], "removed_config_files": 0}

    shared_root = Path(shared_root)
    workspace = Path(workspace)
    home = Path(home)
    removed_paths: list[str] = []
    removed_config_files = 0

    runtime_dirs = [
        workspace / ".loomai" / "harness-defaults" / normalized,
    ]
    for path in runtime_dirs:
        if path.exists() and _is_relative_to(path, workspace):
            shutil.rmtree(path, ignore_errors=True)
            removed_paths.append(str(path))

    if remove_config:
        with tempfile.TemporaryDirectory(prefix="loomai-harness-uninstall-") as tmp:
            tmp_root = Path(tmp)
            canonical_workspace = tmp_root / "work"
            canonical_home = tmp_root / "home"
            sync_harness_defaults(shared_root, canonical_workspace, canonical_home, [normalized])
            files = _expected_harness_files(normalized, workspace, home, canonical_workspace, canonical_home)
            for _root, rel_path, actual_base, _canonical_base in files:
                actual_path = actual_base / rel_path
                if actual_path.is_file() and _is_relative_to(actual_path, actual_base):
                    actual_path.unlink()
                    removed_config_files += 1
                    removed_paths.append(str(actual_path))

    return {
        "removed_paths": removed_paths,
        "removed_config_files": removed_config_files,
    }


def harness_docs_markdown(
    name: str,
    workspace: Path | str = DEFAULT_WORKSPACE,
    home: Path | str = DEFAULT_HOME,
) -> str:
    status = harness_status(name, workspace=workspace, home=home)
    label = status["label"]
    lines = [
        f"# {label} LoomAI Harness Defaults",
        "",
        HARNESS_METADATA[status["name"]]["description"],
        "",
        f"Status: {status['status_label']}",
        "",
        "## Managed Files",
        "",
    ]
    for file_status in status["files"]:
        root_label = "workspace" if file_status["root"] == "workspace" else "home"
        lines.append(f"- `{root_label}:{file_status['path']}` - {file_status['state_label']}")
    lines.extend([
        "",
        "## Sync Behavior",
        "",
        "`loomai tools sync` and the Settings Configure/Sync action regenerate LoomAI-managed defaults while preserving user-owned files and unowned JSON keys.",
        "Use the Settings Reset action or `POST /api/ai/tools/harnesses/{name}/reset` only when you intend to discard local overrides for that harness.",
        "Use Settings Uninstall to remove installed packages and LoomAI-owned runtime state. Config is preserved by default; selecting the remove-configuration option calls `POST /api/ai/tools/{name}/uninstall?remove_config=true` and removes this harness's expected generated config files.",
        "",
        "## Optional MCP Metatools",
        "",
        "OpenAPI MCP metatools are off by default at `ai.harnesses.mcp_metatools=false`. Enable them with a partial `PUT /api/settings` to add read-only `list-endpoints` and `describe-endpoint` tools to `loomai-harness`; when disabled, the normal tool surface is unchanged.",
        "",
        "## Weak-Model Evidence-Closure Hints",
        "",
        "When `ai.assistant.weak_model_context_management=true` AND the harness model's capability profile opts into weak-model context management, `loomai-harness` appends a `next_step_hint` field to SUCCESS results of state-changing tools (`submit_slice`, `run_weave`, `execute_recipe`, `configure_networking`) and to succeeded `get_job_status` results for those jobs. The MCP server reads the session model key from the `LOOMAI_MCP_MODEL` (or `LOOMAI_MODEL`) environment variable inherited from the harness launcher. Strong profiles and the flag-off state keep tool results byte-identical; existing fields never change.",
        "",
        "## Post-Deploy Verification",
        "",
        "After an owner-approved rebuild, run `python3 /app/scripts/verify_harness_lifecycle.py --execute` inside the container to verify install, reset, default uninstall, remove-config uninstall, and reinstall outcomes for all managed harnesses.",
        "",
        "## Mapping",
        "",
    ])
    mapping_path = Path(workspace) / ".loomai" / "harness-defaults" / "MAPPING.md"
    mapping_text = _read_text(mapping_path)
    if mapping_text:
        lines.append(mapping_text.strip())
    else:
        lines.append("Run Configure/Sync once to write `.loomai/harness-defaults/MAPPING.md`.")
    return "\n".join(lines).rstrip() + "\n"


def _normalize_harnesses(
    harnesses: Iterable[str] | None,
    *,
    default: tuple[str, ...] = ALL_MANAGED_HARNESSES,
) -> tuple[str, ...]:
    if harnesses is None:
        return default
    selected: list[str] = []
    for name in harnesses:
        normalized = normalize_harness_name(str(name))
        if normalized not in selected:
            selected.append(normalized)
    return tuple(selected)


def _status_for_harness(
    name: str,
    workspace: Path,
    home: Path,
    canonical_workspace: Path,
    canonical_home: Path,
) -> dict[str, Any]:
    files = _expected_harness_files(name, workspace, home, canonical_workspace, canonical_home)
    file_rows = [
        _compare_harness_file(root, rel_path, actual_base, canonical_base)
        for root, rel_path, actual_base, canonical_base in files
    ]
    stale_count = sum(1 for row in file_rows if row["state"] in {"missing", "stale"})
    user_modified_count = sum(1 for row in file_rows if row["state"] == "user_modified")
    configured_count = sum(1 for row in file_rows if row["state"] == "configured")

    if stale_count:
        status = "stale"
        status_label = "Stale"
    elif user_modified_count:
        status = "user_modified"
        status_label = "User-modified"
    else:
        status = "configured"
        status_label = "Configured"

    metadata = HARNESS_METADATA[name]
    return {
        "name": name,
        "label": metadata["label"],
        "description": metadata["description"],
        "status": status,
        "status_label": status_label,
        "configured": status == "configured",
        "needs_sync": stale_count > 0,
        "expected_files": len(file_rows),
        "configured_files": configured_count,
        "stale_files": stale_count,
        "user_modified_files": user_modified_count,
        "docs_url": f"/api/ai/tools/harnesses/{name}/docs",
        "files": file_rows,
    }


def _expected_harness_files(
    name: str,
    workspace: Path,
    home: Path,
    canonical_workspace: Path,
    canonical_home: Path,
) -> list[tuple[str, str, Path, Path]]:
    spec = _HARNESS_FILE_SPECS[name]
    rows: list[tuple[str, str, Path, Path]] = []
    seen: set[tuple[str, str]] = set()

    def add(root: str, rel_path: str) -> None:
        key = (root, rel_path)
        if key in seen:
            return
        seen.add(key)
        if root == "workspace":
            rows.append((root, rel_path, workspace, canonical_workspace))
        else:
            rows.append((root, rel_path, home, canonical_home))

    for rel_path in spec.get("workspace_files", []):
        add("workspace", rel_path)
    for pattern in spec.get("workspace_globs", []):
        for path in sorted(canonical_workspace.glob(pattern)):
            if path.is_file():
                add("workspace", path.relative_to(canonical_workspace).as_posix())
    for rel_path in spec.get("home_files", []):
        add("home", rel_path)
    for pattern in spec.get("home_globs", []):
        for path in sorted(canonical_home.glob(pattern)):
            if path.is_file():
                add("home", path.relative_to(canonical_home).as_posix())

    return rows


def _compare_harness_file(root: str, rel_path: str, actual_base: Path, canonical_base: Path) -> dict[str, Any]:
    actual_path = actual_base / rel_path
    canonical_path = canonical_base / rel_path
    row = {
        "root": root,
        "path": rel_path,
        "state": "configured",
        "state_label": "Configured",
        "reason": "",
    }

    if not actual_path.is_file():
        return {**row, "state": "missing", "state_label": "Missing", "reason": "Expected generated file is absent."}
    if _is_json_path(rel_path):
        return {**row, **_compare_json_file(actual_path, canonical_path, actual_base, canonical_base)}

    actual_text = _read_text(actual_path)
    canonical_text = _normalize_canonical_text(_read_text(canonical_path), actual_base, canonical_base)
    executable_stale = _is_executable(canonical_path) and not _is_executable(actual_path)
    if actual_text == canonical_text and not executable_stale:
        return row
    if _contains_managed_marker(actual_text):
        reason = "Managed file differs from current canonical defaults."
        if executable_stale:
            reason = "Managed executable is missing execute permission."
        return {**row, "state": "stale", "state_label": "Stale", "reason": reason}
    return {
        **row,
        "state": "user_modified",
        "state_label": "User-modified",
        "reason": "User-owned file differs from generated defaults and will not be overwritten by sync.",
    }


def _compare_json_file(actual_path: Path, canonical_path: Path, actual_base: Path, canonical_base: Path) -> dict[str, str]:
    try:
        actual = json.loads(actual_path.read_text(encoding="utf-8"))
        canonical_text = _normalize_canonical_text(canonical_path.read_text(encoding="utf-8"), actual_base, canonical_base)
        canonical = json.loads(canonical_text)
    except (OSError, json.JSONDecodeError):
        return {"state": "stale", "state_label": "Stale", "reason": "JSON file cannot be parsed and will be regenerated by sync."}
    missing: list[str] = []
    changed: list[str] = []
    extra: list[str] = []
    _compare_json_defaults(actual, canonical, "", missing, changed, extra)
    if missing:
        preview = ", ".join(missing[:3])
        return {"state": "stale", "state_label": "Stale", "reason": f"Missing generated defaults: {preview}"}
    if changed or extra:
        details = changed[:2] + extra[:2]
        preview = ", ".join(details)
        return {"state": "user_modified", "state_label": "User-modified", "reason": f"Differs from canonical defaults: {preview}"}
    return {"state": "configured", "state_label": "Configured", "reason": ""}


def _normalize_canonical_text(text: str, actual_base: Path, canonical_base: Path) -> str:
    canonical = str(canonical_base)
    actual = str(actual_base)
    if canonical and canonical != actual:
        return text.replace(canonical, actual)
    return text


def _compare_json_defaults(
    actual: Any,
    canonical: Any,
    path: str,
    missing: list[str],
    changed: list[str],
    extra: list[str],
) -> None:
    if isinstance(canonical, dict):
        if not isinstance(actual, dict):
            changed.append(path or "$")
            return
        for key, canonical_value in canonical.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key not in actual:
                missing.append(child_path)
                continue
            _compare_json_defaults(actual[key], canonical_value, child_path, missing, changed, extra)
        for key in actual:
            if key not in canonical:
                extra.append(f"{path}.{key}" if path else str(key))
        return
    if actual != canonical:
        changed.append(path or "$")


def _contains_managed_marker(text: str) -> bool:
    return (
        MANAGED_TEXT_MARKER in text
        or MANAGED_TOML_MARKER in text
        or MANAGED_CODE_MARKER in text
        or MANAGED_SHELL_MARKER in text
        or _looks_like_legacy_managed(text)
    )


def _is_json_path(rel_path: str) -> bool:
    return rel_path.endswith(".json")


def _is_executable(path: Path) -> bool:
    try:
        return bool(path.stat().st_mode & 0o111)
    except OSError:
        return False


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except (OSError, ValueError):
        return False


def _shared_context(fabric_ai: str) -> str:
    return f"{MANAGED_TEXT_MARKER}\n\n{fabric_ai.rstrip()}\n\n{HARNESS_CONTRACT}\n"


def _load_assets(src_dir: Path) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    if not src_dir.is_dir():
        return assets
    for path in sorted(src_dir.glob("*.md")):
        text = _read_text(path)
        parsed = parse_markdown_asset(text)
        metadata = dict(parsed.metadata)
        asset_id = str(metadata.get("id") or metadata.get("name") or path.stem).strip() or path.stem
        description = str(metadata.get("description") or _first_sentence(parsed.body) or asset_id)
        assets.append({
            "id": asset_id,
            "filename": path.name,
            "description": description,
            "body": parsed.body.strip() + "\n",
            "text": text,
        })
    return assets


def _render_opencode(workspace: Path, agents_md: str, agents: list[dict[str, Any]], skills: list[dict[str, Any]]) -> None:
    opencode_dir = workspace / ".opencode"
    prompts_dir = opencode_dir / "agent-prompts"
    skills_dir = opencode_dir / "skills"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)

    for agent in agents:
        _write_if_missing(prompts_dir / f"{agent['id']}.md", agent["body"])
    for skill in skills:
        skill_dir = skills_dir / _safe_slug(skill["id"])
        skill_dir.mkdir(parents=True, exist_ok=True)
        _write_if_missing(skill_dir / "SKILL.md", skill["text"])

    defaults = {
        "$schema": "https://opencode.ai/config.json",
        "model": "ai-renci/gpt-5.5",
        "small_model": "fabric/qwen3-coder-30b",
        "provider": _opencode_providers(),
        "agent": {
            agent["id"]: {
                "description": agent["description"],
                "prompt": f"{{file:.opencode/agent-prompts/{agent['id']}.md}}",
                "mode": "primary" if agent["id"] in {"fabric-slice-operator", "fabric-query-reporter"} else "subagent",
            }
            for agent in agents
        },
        "command": {
            skill["id"]: {
                "description": skill["description"],
                "template": f"Use the `{skill['id']}` skill instructions from `.opencode/skills/{_safe_slug(skill['id'])}/SKILL.md`. $input",
            }
            for skill in skills
        },
        "mcp": _opencode_mcp(workspace),
        "permission": _opencode_permissions(),
    }
    _merge_json_file(workspace / "opencode.json", defaults)
    prune_stale_mcp_entries(workspace / "opencode.json", "mcp")
    _write_managed_text(workspace / "opencode" / "AGENTS.md", agents_md)


def _opencode_providers() -> dict[str, Any]:
    providers: dict[str, Any] = {}
    for provider_id, provider in _provider_catalog().items():
        providers[provider_id] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": provider["label"],
            "options": {
                "baseURL": provider["base_url"],
                "apiKey": f"{{env:{provider['api_key_env']}}}",
            },
            "models": provider["models"],
        }
    return providers


MANAGED_SCRIPT_MARKER = "# LoomAI-managed MCP wrapper — remove this line to keep local edits."

# Resolve the FABRIC token file the same way `settings_manager.get_token_path()`
# does: FABRIC_TOKEN_FILE -> ~/.tokens.json -> config_dir/id_token.json. The
# Python fast-path is exact (it honours the settings `paths.token_file`
# override); the shell chain is the fallback for when `app` is not importable.
_RESOLVE_TOKEN_SH = """resolve_token_file() {
  local resolved
  resolved="$(python3 -c 'from app.settings_manager import get_token_path; print(get_token_path())' 2>/dev/null || true)"
  if [ -n "$resolved" ] && [ -f "$resolved" ]; then
    printf '%s' "$resolved"
    return 0
  fi
  if [ -n "${FABRIC_TOKEN_FILE:-}" ]; then
    printf '%s' "$FABRIC_TOKEN_FILE"
  elif [ -f "$HOME/.tokens.json" ]; then
    printf '%s' "$HOME/.tokens.json"
  elif [ -n "${FABRIC_TOKEN_LOCATION:-}" ]; then
    printf '%s' "$FABRIC_TOKEN_LOCATION"
  else
    printf '%s' "${FABRIC_CONFIG_DIR:-/home/fabric/work/fabric_config}/id_token.json"
  fi
}"""


def _mcp_remote_script(server: "MCPServer") -> str:
    """Bash wrapper that launches `npx mcp-remote` against a remote server."""
    if server.auth != "fabric_token":
        return f"""#!/usr/bin/env bash
{MANAGED_SCRIPT_MARKER}
set -euo pipefail
exec npx -y mcp-remote "{server.url}"
"""
    return f"""#!/usr/bin/env bash
{MANAGED_SCRIPT_MARKER}
set -euo pipefail
{_RESOLVE_TOKEN_SH}
TOKEN_FILE="$(resolve_token_file)"
TOKEN="$(TOKEN_FILE="$TOKEN_FILE" python3 -c 'import json, os; print(json.load(open(os.environ["TOKEN_FILE"]))["id_token"])')"
exec npx -y mcp-remote "{server.url}" --header "Authorization: Bearer ${{TOKEN}}"
"""


def _write_managed_script(path: Path, text: str) -> None:
    """Write a generated script, refreshing it unless the user took it over.

    Unlike :func:`_write_if_missing`, this regenerates on every sync so a
    changed server URL or auth mode actually reaches the wrapper. A script the
    user edited (marker line removed) is left untouched.
    """
    if path.is_file():
        current = path.read_text(encoding="utf-8", errors="replace")
        if MANAGED_SCRIPT_MARKER not in current:
            return
        if current == text:
            path.chmod(0o755)
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def sync_mcp_wrapper_scripts(workspace: Path) -> dict[str, Path]:
    """Generate one `mcp-remote` wrapper per remote server; drop stale ones.

    Returns ``{server name: script path}``. Both OpenCode and Claude Code point
    at these same scripts, so the token-resolution logic exists once.
    """
    from app.mcp_registry import managed_server_names, remote_harness_servers

    mcp_dir = workspace / ".opencode" / "mcp-scripts"
    mcp_dir.mkdir(parents=True, exist_ok=True)

    scripts: dict[str, Path] = {}
    for server in remote_harness_servers():
        script = mcp_dir / f"{server.name}.sh"
        _write_managed_script(script, _mcp_remote_script(server))
        scripts[server.name] = script

    # Remove wrappers for servers LoomAI no longer generates (disabled, or
    # dropped from ai.mcp_servers). Never touch a user-authored script.
    for stale in managed_server_names() - set(scripts):
        path = mcp_dir / f"{stale}.sh"
        if not path.is_file():
            continue
        if MANAGED_SCRIPT_MARKER in path.read_text(encoding="utf-8", errors="replace"):
            path.unlink()
    return scripts


def prune_stale_mcp_entries(config_path: Path, key: str) -> None:
    """Drop LoomAI-managed MCP entries that are no longer registered.

    ``_merge_json_file`` preserves every existing key, so disabling a server
    would otherwise leave it configured forever. Only names the registry owns
    are removed — servers the user added by hand stay.
    """
    from app.mcp_registry import harness_servers, managed_server_names

    if not config_path.is_file():
        return
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    if not isinstance(config, dict) or not isinstance(config.get(key), dict):
        return

    desired = {s.name for s in harness_servers()}
    stale = (managed_server_names() - desired) & set(config[key])
    if not stale:
        return
    for name in stale:
        config[key].pop(name, None)
    config_path.write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _opencode_mcp(workspace: Path) -> dict[str, Any]:
    """Wire every registered MCP server into OpenCode's `mcp` block."""
    from app.mcp_registry import harness_servers

    scripts = sync_mcp_wrapper_scripts(workspace)

    config: dict[str, Any] = {}
    for server in harness_servers():
        if server.transport == "stdio":
            config[server.name] = {
                "type": "local",
                "command": list(server.command),
                "enabled": True,
                "timeout": 30000,
            }
            continue
        config[server.name] = {
            "type": "local",
            "command": ["bash", str(scripts[server.name])],
            "enabled": True,
            "timeout": 15000,
        }
    return config


def _opencode_permissions() -> dict[str, Any]:
    return {
        "bash": {
            "*": "deny",
            "loomai *": "allow",
            "curl http://localhost:8000/*": "allow",
            "curl -s http://localhost:8000/*": "allow",
            "curl -s -X * http://localhost:8000/*": "allow",
            "mkdir -p /home/fabric/work/my_artifacts/*": "allow",
            "tee /home/fabric/work/my_artifacts/*": "allow",
            "cat /home/fabric/work/my_artifacts/*": "allow",
            "find /home/fabric/work/my_artifacts/*": "allow",
            "chmod * /home/fabric/work/my_artifacts/*": "allow",
            "python3 -m json.tool": "allow",
        },
        "edit": "deny",
        "webfetch": "deny",
        "external_directory": "deny",
    }


def _render_aider(workspace: Path, home: Path, agents_md: str) -> None:
    _write_managed_text(workspace / "CONVENTIONS.md", agents_md)
    ai_renci = _provider_catalog().get("ai-renci", {})
    defaults = {
        "model": "openai/ai-renci:gpt-5.5",
        "openai-api-base": ai_renci.get("base_url", "https://ai-renci.fabric-testbed.net/v1"),
        "openai-api-key": f"{{env:{ai_renci.get('api_key_env', 'LOOMAI_CUSTOM_PROVIDER_AI_RENCI_API_KEY')}}}",
        "read": ["CONVENTIONS.md", "AGENTS.md"],
        "auto-commits": False,
        "edit-format": "whole",
    }
    text = _simple_yaml(defaults)
    _write_if_missing(workspace / ".aider.conf.yml", text)
    _write_if_missing(home / ".aider.conf.yml", text)
    ignore = ".git\n__pycache__\n.loomai/\nfabric_config/\n"
    _write_if_missing(workspace / ".aiderignore", ignore)
    _write_if_missing(home / ".aiderignore", ignore)


def _render_crush(workspace: Path, home: Path, agents_md: str, agents: list[dict[str, Any]], skills: list[dict[str, Any]]) -> None:
    _write_managed_text(workspace / "CRUSH.md", agents_md)
    providers = {
        provider_id: {
            "id": provider_id,
            "type": "openai",
            "base_url": provider["base_url"],
            "api_key_env": provider["api_key_env"],
            "models": [{"id": key, **value} for key, value in provider["models"].items()],
        }
        for provider_id, provider in _provider_catalog().items()
    }
    defaults = {
        "$schema": "https://charm.land/crush.json",
        "model": "ai-renci:gpt-5.5",
        "providers": providers,
        "instructions": "CRUSH.md",
        "tools": {"shell": {"allowed": ["loomai", "curl http://localhost:8000"], "editing": False}},
    }
    _merge_json_file(workspace / ".crush.json", defaults)
    config_dir = home / ".config" / "crush"
    config_dir.mkdir(parents=True, exist_ok=True)
    _merge_json_file(config_dir / "crush.json", defaults)
    for skill in skills:
        _write_if_missing(workspace / ".crush" / "skills" / f"{skill['id']}.md", skill["text"])
    for agent in agents:
        _write_if_missing(workspace / ".crush" / "agents" / f"{agent['id']}.md", agent["text"])


def _render_goose(
    workspace: Path,
    home: Path,
    agents_md: str,
    agents: list[dict[str, Any]],
    skills: list[dict[str, Any]],
) -> None:
    goose_dir = workspace / ".config" / "goose"
    goose_dir.mkdir(parents=True, exist_ok=True)
    _write_managed_text(workspace / "goose" / "AGENTS.md", agents_md)
    for skill in skills:
        _write_if_missing(workspace / ".goose" / "skills" / _safe_slug(skill["id"]) / "SKILL.md", skill["text"])
    for agent in agents:
        _write_if_missing(workspace / ".goose" / "agents" / f"{agent['id']}.md", agent["text"])
    providers = {
        provider_id: {
            "type": "openai",
            "base_url": provider["base_url"],
            "api_key_env": provider["api_key_env"],
            "models": provider["models"],
        }
        for provider_id, provider in _provider_catalog().items()
    }
    config_payload = {
        "providers": providers,
        "default_provider": "ai-renci",
        "default_model": "gpt-5.5",
        "instructions": "/home/fabric/work/AGENTS.md",
        "extensions": {
            "loomai-harness": {
                "enabled": True,
                "type": "stdio",
                "name": "loomai-harness",
                "cmd": "python3",
                "args": ["-m", "app.harness_mcp_server"],
                "envs": {"LOOMAI_URL": "http://127.0.0.1:8000"},
                "timeout": 3600,
            },
        },
    }
    config = """\
# LoomAI generated Goose defaults.
# Goose external runs can select providers by setting:
#   GOOSE_PROVIDER=openai
#   GOOSE_MODEL=<model>
#   OPENAI_BASE_URL=<provider /v1 URL>
#   OPENAI_API_KEY=<matching API key>
""" + _simple_yaml(config_payload)
    _write_if_missing(goose_dir / "config.yaml", config)
    _write_if_missing(home / ".config" / "goose" / "config.yaml", config)


def _render_pi(workspace: Path, home: Path, agents_md: str, skills: list[dict[str, Any]]) -> None:
    pi_dir = workspace / "pi"
    agent_dir = pi_dir / "agent"
    home_agent_dir = home / ".pi" / "agent"

    _write_managed_text(pi_dir / "AGENTS.md", agents_md)
    _merge_json_file(workspace / ".pi" / "extensions" / "pi-permission-system" / "config.json", _pi_permission_config())
    _render_pi_agent_profile(agent_dir, workspace, skills)
    _render_pi_agent_profile(home_agent_dir, workspace, skills, session_dir=home_agent_dir / "sessions")
    _write_managed_text(pi_dir / "README.md", _pi_readme())
    _write_managed_executable(pi_dir / "pi-fabric", _pi_launcher())
    _write_managed_executable(home / ".local" / "bin" / "pi-fabric", _pi_path_launcher())


def _render_pi_agent_profile(
    agent_dir: Path,
    workspace: Path,
    skills: list[dict[str, Any]],
    *,
    session_dir: Path | None = None,
) -> None:
    skills_dir = agent_dir / "skills"
    extensions_dir = agent_dir / "extensions"
    extensions_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)

    for skill in skills:
        _write_if_missing(skills_dir / _safe_slug(skill["id"]) / "SKILL.md", skill["text"])
    _merge_json_file(agent_dir / "models.json", _pi_models_config())
    _merge_json_file(agent_dir / "settings.json", _pi_settings_config(workspace, session_dir=session_dir))
    _ensure_pi_settings_stack(agent_dir / "settings.json")
    _merge_json_file(agent_dir / "mcp.json", _pi_mcp_config())
    _merge_json_file(agent_dir / "lsp.json", _pi_lsp_config())
    _merge_json_file(agent_dir / "web-search.json", _pi_web_access_config())
    _merge_json_file(extensions_dir / "pi-permission-system" / "config.json", _pi_permission_config())
    _write_managed_code(extensions_dir / "loomai-surface-guard.ts", _pi_surface_guard_extension())
    _copy_pi_installed_extensions(agent_dir)


def _pi_npm_modules_dir() -> Path:
    try:
        from app.settings_manager import get_ai_tools_dir

        return Path(get_ai_tools_dir()) / "npm" / "lib" / "node_modules"
    except Exception:
        return Path(os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")) / ".ai-tools" / "npm" / "lib" / "node_modules"


def _copy_pi_installed_extensions(agent_dir: Path) -> None:
    """Copy installed Pi extension packages into an agent profile when present."""
    modules_dir = _pi_npm_modules_dir()
    extensions_dir = agent_dir / "extensions"
    for package_name, _version, entry_path in PI_EXTENSION_PACKAGES:
        src = modules_dir / package_name
        if not (src / entry_path).exists():
            continue
        dest = extensions_dir / package_name
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)


def _pi_models_config() -> dict[str, Any]:
    common_compat = {"supportsDeveloperRole": False, "supportsReasoningEffort": False}
    providers: dict[str, Any] = {}
    for provider_id, provider in _provider_catalog().items():
        models = provider["models"]
        if provider_id == "ai-renci":
            responses = {
                model_id: model
                for model_id, model in models.items()
                if model.get("endpoint_style") == "responses"
            }
            chat = {
                model_id: model
                for model_id, model in models.items()
                if model.get("endpoint_style") != "responses"
            }
            providers["ai-renci"] = {
                "baseUrl": provider["base_url"],
                "api": "openai-responses",
                "apiKey": f"${provider['api_key_env']}",
                "authHeader": True,
                "compat": common_compat,
                "models": [_pi_model_entry(model_id, model) for model_id, model in responses.items()],
            }
            providers["ai-renci-chat"] = {
                "baseUrl": provider["base_url"],
                "api": "openai-completions",
                "apiKey": f"${provider['api_key_env']}",
                "authHeader": True,
                "compat": common_compat,
                "models": [_pi_model_entry(model_id, model) for model_id, model in chat.items()],
            }
            continue
        responses = {
            model_id: model
            for model_id, model in models.items()
            if model.get("endpoint_style") == "responses"
        }
        chat = {
            model_id: model
            for model_id, model in models.items()
            if model.get("endpoint_style") != "responses"
        }
        if responses:
            providers[provider_id] = {
                "baseUrl": provider["base_url"],
                "api": "openai-responses",
                "apiKey": f"${provider['api_key_env']}",
                "authHeader": True,
                "compat": common_compat,
                "models": [_pi_model_entry(model_id, model) for model_id, model in responses.items()],
            }
        if chat:
            chat_id = f"{provider_id}-chat" if responses else provider_id
            providers[chat_id] = {
                "baseUrl": provider["base_url"],
                "api": "openai-completions",
                "apiKey": f"${provider['api_key_env']}",
                "authHeader": True,
                "compat": common_compat,
                "models": [_pi_model_entry(model_id, model) for model_id, model in chat.items()],
            }
    return {"providers": providers}


def _pi_model_entry(model_id: str, model: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": model.get("name") or model_id,
        "name": model.get("name") or model_id,
        "reasoning": bool(model.get("reasoning_model")),
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": int(model.get("context_window") or model.get("contextWindow") or 131072),
        "maxTokens": int(model.get("max_tokens") or model.get("max_output_tokens") or model.get("maxTokens") or 32768),
    }


def _pi_settings_config(workspace: Path, *, session_dir: Path | None = None) -> dict[str, Any]:
    session_dir = session_dir or workspace / ".loomai" / "harness-defaults" / "pi" / "sessions"
    return {
        "defaultProvider": "ai-renci",
        "defaultModel": "gpt-5.5",
        "defaultThinkingLevel": "off",
        "defaultProjectTrust": "always",
        "enableInstallTelemetry": False,
        "enableAnalytics": False,
        "quietStartup": True,
        "transport": "sse",
        "skills": ["skills/*/SKILL.md"],
        "extensions": [
            "extensions/loomai-surface-guard.ts",
            "extensions/pi-mcp-adapter/index.ts",
            "extensions/@gotgenes/pi-permission-system/src/index.ts",
            "extensions/pi-subagents/src/extension/index.ts",
            "extensions/pi-web-access/index.ts",
            "extensions/@lebronj/pi-lsp/dist/index.js",
        ],
        "enableSkillCommands": True,
        "retry": {
            "enabled": True,
            "maxRetries": 1,
            "baseDelayMs": 2000,
            "provider": {"timeoutMs": 3600000, "maxRetries": 0, "maxRetryDelayMs": 60000},
        },
        "sessionDir": str(session_dir),
    }


def _ensure_pi_settings_stack(path: Path) -> None:
    """Ensure managed Pi extension defaults survive upgrades from older configs."""
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    defaults = _pi_settings_config(DEFAULT_WORKSPACE)
    required_extensions = defaults["extensions"]
    current_extensions = settings.get("extensions")
    if not isinstance(current_extensions, list):
        current_extensions = []
    for extension in required_extensions:
        if extension not in current_extensions:
            current_extensions.append(extension)
    settings["extensions"] = current_extensions
    settings.pop("permission", None)
    path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _pi_permission_config() -> dict[str, Any]:
    return {
        "permission": {
            "*": "allow",
            "read": "allow",
            "write": "allow",
            "edit": "allow",
            "loomai_harness_*": "allow",
            "loomai_harness_delete_*": "ask",
            "bash": {
                "*": "allow",
                "rm -rf *": "ask",
                "rm -r *": "ask",
                "sudo rm *": "ask",
                "loomai * delete*": "ask",
                "git push --force*": "ask",
                "git push -f*": "ask",
            },
            "mcp": {
                "*": "allow",
                "loomai_harness_*": "allow",
                "loomai_harness_delete_*": "ask",
                "*delete*": "ask",
            },
            "path": {
                "*": "allow",
                "~/.ssh/*": "ask",
                "*.env": "ask",
            },
            "external_directory": "allow",
        }
    }


def _pi_mcp_config() -> dict[str, Any]:
    return {
        "settings": {
            "toolPrefix": "server",
            "idleTimeout": 10,
            "requestTimeoutMs": 3600000,
            "outputGuard": True,
            "directTools": True,
        },
        "mcpServers": {
            "loomai-harness": {
                "command": "python3",
                "args": ["-m", "app.harness_mcp_server"],
                "env": {"PYTHONPATH": "/app", "LOOMAI_URL": "http://127.0.0.1:8000"},
                "lifecycle": "eager",
                "idleTimeout": 10,
                "requestTimeoutMs": 3600000,
            }
        },
    }


def _pi_lsp_config() -> dict[str, Any]:
    return {
        "idleTimeoutMs": 600000,
        "servers": {
            "python": {
                "command": "pyright-langserver",
                "args": ["--stdio"],
                "fileTypes": [".py", ".pyi"],
                "rootMarkers": ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", ".git"],
            }
        },
    }


def _pi_web_access_config() -> dict[str, Any]:
    return {
        "webSearch": {"enabled": True},
        "provider": "auto",
        "workflow": "none",
        "allowBrowserCookies": False,
        "githubClone": {
            "enabled": True,
            "maxRepoSizeMB": 350,
            "cloneTimeoutSeconds": 30,
            "clonePath": "/tmp/pi-github-repos",
        },
        "ssrf": {"allowRanges": []},
    }


def _pi_surface_guard_extension() -> str:
    return f"""{MANAGED_CODE_MARKER}
import type {{ ExtensionAPI }} from "@earendil-works/pi-coding-agent";

const BLOCKED_PATHS = [
  "/app",
  "/home/fabric/work/.loomai",
  "INSTRUCTIONS_EXTERNAL_CODEX.md",
];

const BLOCKED_PATTERNS = [
  /\\bsudo\\b/i,
  /\\brm\\s+(-rf?|--recursive)\\b/i,
  /\\bfablib\\b/i,
  /\\bimport\\s+fabrictestbed_extensions\\b/i,
  /\\b(EDC|EDUKY)\\b/,
];

export default function (pi: ExtensionAPI) {{
  pi.on("tool_call", async (event) => {{
    const payload = JSON.stringify(event.input ?? {{}});
    const command = String((event.input as any)?.command ?? "");
    if ((event.toolName === "write" || event.toolName === "edit")) {{
      return {{ block: true, reason: "Pi harness disables write/edit tools; use loomai CLI or REST only." }};
    }}
    if (event.toolName === "bash") {{
      if (BLOCKED_PATHS.some((path) => payload.includes(path))) {{
        return {{ block: true, reason: "Protected path is outside the Pi harness contract." }};
      }}
      if (BLOCKED_PATTERNS.some((pattern) => pattern.test(command))) {{
        return {{ block: true, reason: "Shell command is outside the LoomAI CLI/REST benchmark contract." }};
      }}
    }}
    return undefined;
  }});
}}
"""


def _pi_readme() -> str:
    return """\
# Pi Harness Config

This directory is generated from the shared LoomAI AI assets for the Pi coding
agent. It is safe to regenerate with `loomai tools sync`; user-authored files
without LoomAI managed markers are preserved.

Provider mapping:
- FABRIC AI uses `https://ai.fabric-testbed.net/v1` with `FABRIC_AI_API_KEY`.
- ai-renci gpt-5.5 uses the Responses API at
  `https://ai-renci.fabric-testbed.net/v1` with
  `LOOMAI_CUSTOM_PROVIDER_AI_RENCI_API_KEY`.
- ai-renci chat models use a separate OpenAI-compatible provider entry with
  the same `LOOMAI_CUSTOM_PROVIDER_AI_RENCI_API_KEY`.
- NRP uses `https://ellm.nrp-nautilus.io/v1` with `NRP_API_KEY`.

Pi does not ship built-in MCP support in the pinned 0.80.3 release. LoomAI
installs `pi-mcp-adapter@2.10.0` with Pi and writes `agent/mcp.json` so the
local `loomai-harness` MCP server is available through the adapter.

Pinned Pi extension stack installed by the Settings install button:
- `pi-mcp-adapter@2.10.0` for LoomAI MCP access.
- `@gotgenes/pi-permission-system@16.0.1` plus the local
  `loomai-surface-guard.ts` for allow/deny enforcement.
- `pi-subagents@0.33.1` for delegated child-agent workflows.
- `pi-web-access@0.10.7` for web search and fetch tools.
- `@lebronj/pi-lsp@0.0.3` plus `pyright@1.1.411` with Python-only
  `agent/lsp.json` defaults.

The Pi permission-system extension does not read `settings.json.permission`.
LoomAI writes its real config to `agent/extensions/pi-permission-system/config.json`
and to the project-level `.pi/extensions/pi-permission-system/config.json`.
The interactive default allows read/write/edit/bash/MCP tools, including
`loomai_harness_*`, and asks on destructive deletes, force-pushes, `~/.ssh/*`,
and `*.env` paths. For fully headless benchmark runs where prompts are not
acceptable, replace that real config with:

```json
{"yoloMode": true, "permission": {"*": "allow"}}
```

The `pi-fabric` wrapper uses isolated runtime config and session directories
under `/home/fabric/work/.loomai/harness-defaults/pi`, loads shared LoomAI
skills, enables only read/list/search plus bash tools, and installs a guard
extension that blocks writes and out-of-contract protected paths/commands.
The same defaults are also seeded into `~/.pi/agent/` so plain `pi` starts
with LoomAI providers, skills, MCP, web, LSP, and extension defaults. A
managed `~/.local/bin/pi-fabric` launcher is written for PATH-based access.

From the WebUI, use Settings > AI Tools > Harnesses > Pi to check whether these
files are configured, re-sync only Pi defaults, or open generated docs. The same
per-harness sync preserves user-owned overrides.
"""


def _pi_launcher() -> str:
    return f"""#!/usr/bin/env bash
{MANAGED_SHELL_MARKER}
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_ROOT="$(cd "$ROOT/.." && pwd)"
STATIC_AGENT_DIR="$ROOT/agent"
RUNTIME_ROOT="${{PI_LOOMAI_RUNTIME_ROOT:-$WORKSPACE_ROOT/.loomai/harness-defaults/pi}}"
PI_BIN="${{PI_BIN:-}}"
if [ -z "$PI_BIN" ]; then
  PI_BIN="$(command -v pi || true)"
fi
if [ -z "$PI_BIN" ]; then
  echo "Pi is not installed. Install it from Settings > AI Tools or run loomai tools sync after installing." >&2
  exit 127
fi
PI_PREFIX="$(cd "$(dirname "$PI_BIN")/.." && pwd)"
export PI_CODING_AGENT_DIR="${{PI_CODING_AGENT_DIR:-$RUNTIME_ROOT/agent}}"
export PI_CODING_AGENT_SESSION_DIR="${{PI_CODING_AGENT_SESSION_DIR:-$RUNTIME_ROOT/sessions}}"
export PI_PACKAGE_DIR="${{PI_PACKAGE_DIR:-$PI_PREFIX/lib/node_modules/@earendil-works/pi-coding-agent}}"
export PI_TELEMETRY="${{PI_TELEMETRY:-0}}"
export PI_SKIP_VERSION_CHECK="${{PI_SKIP_VERSION_CHECK:-1}}"
export PI_OFFLINE="${{PI_OFFLINE:-0}}"
PI_MODE="${{PI_MODE:-json}}"
mkdir -p "$PI_CODING_AGENT_DIR" "$PI_CODING_AGENT_SESSION_DIR" "$RUNTIME_ROOT/cache"
cp "$STATIC_AGENT_DIR/models.json" "$PI_CODING_AGENT_DIR/models.json"
cp "$STATIC_AGENT_DIR/settings.json" "$PI_CODING_AGENT_DIR/settings.json"
cp "$STATIC_AGENT_DIR/mcp.json" "$PI_CODING_AGENT_DIR/mcp.json"
cp "$STATIC_AGENT_DIR/lsp.json" "$PI_CODING_AGENT_DIR/lsp.json"
cp "$STATIC_AGENT_DIR/web-search.json" "$PI_CODING_AGENT_DIR/web-search.json"
mkdir -p "$PI_CODING_AGENT_DIR/extensions"
cp "$STATIC_AGENT_DIR/extensions/loomai-surface-guard.ts" "$PI_CODING_AGENT_DIR/extensions/loomai-surface-guard.ts"
EXTENSION_FLAGS=("--extension" "$PI_CODING_AGENT_DIR/extensions/loomai-surface-guard.ts")
copy_extension() {{
  local package_name="$1"
  local entry_path="$2"
  local package_dir="$PI_PREFIX/lib/node_modules/$package_name"
  local dest_dir="$PI_CODING_AGENT_DIR/extensions/$package_name"
  if [ -e "$package_dir/$entry_path" ]; then
    mkdir -p "$(dirname "$dest_dir/$entry_path")"
    rm -rf "$dest_dir"
    cp -R "$package_dir" "$dest_dir"
    EXTENSION_FLAGS+=("--extension" "$dest_dir/$entry_path")
  else
    echo "Warning: Pi extension $package_name entry $entry_path not found under $package_dir" >&2
  fi
}}
copy_extension "pi-mcp-adapter" "index.ts"
copy_extension "@gotgenes/pi-permission-system" "src/index.ts"
copy_extension "pi-subagents" "src/extension/index.ts"
copy_extension "pi-web-access" "index.ts"
copy_extension "@lebronj/pi-lsp" "dist/index.js"
rm -rf "$PI_CODING_AGENT_DIR/skills"
cp -R "$STATIC_AGENT_DIR/skills" "$PI_CODING_AGENT_DIR/"
exec "$PI_BIN" \\
  --approve \\
  --mode "$PI_MODE" \\
  --tools bash,read,grep,find,ls \\
  --skill "$PI_CODING_AGENT_DIR/skills" \\
  "${{EXTENSION_FLAGS[@]}}" \\
  --session-dir "$PI_CODING_AGENT_SESSION_DIR" \\
  "$@"
"""


def _pi_path_launcher() -> str:
    return f"""#!/usr/bin/env bash
{MANAGED_SHELL_MARKER}
set -euo pipefail
WORKSPACE="${{LOOMAI_WORKSPACE:-}}"
if [ -z "$WORKSPACE" ]; then
  WORKSPACE="$(PYTHONPATH="${{PYTHONPATH:-/app}}" python3 -c 'from app.settings_manager import get_storage_dir; print(get_storage_dir())' 2>/dev/null || true)"
fi
if [ -z "$WORKSPACE" ]; then
  WORKSPACE="${{FABRIC_STORAGE_DIR:-/home/fabric/work}}"
fi
TARGET="$WORKSPACE/pi/pi-fabric"
if [ ! -x "$TARGET" ]; then
  echo "Pi LoomAI launcher not configured at $TARGET. Run loomai tools sync or use Settings > AI Tools > Harnesses > Pi." >&2
  exit 127
fi
exec "$TARGET" "$@"
"""


def _render_codex(workspace: Path, home: Path, agents_md: str, agents: list[dict[str, Any]], skills: list[dict[str, Any]]) -> None:
    _write_managed_text(workspace / "codex" / "AGENTS.md", agents_md)
    codex_dir = home / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# LoomAI generated Codex defaults. Existing user config.toml files are not",
        "# overwritten; this file is written only when config.toml is missing or was",
        "# previously LoomAI-managed.",
        'model = "gpt-5.5"',
        'model_provider = "ai-renci"',
        'model_reasoning_effort = "medium"',
        "",
    ]
    for provider_id, provider in _provider_catalog().items():
        endpoint = provider.get("endpoint_style")
        if endpoint == "auto":
            styles = {model.get("endpoint_style") for model in provider["models"].values()}
            endpoint = "responses" if styles == {"responses"} else "chat"
        wire_api = "responses" if endpoint == "responses" else "chat"
        lines.extend([
            f"[model_providers.{provider_id}]",
            f"name = {json.dumps(provider['label'])}",
            f"base_url = {json.dumps(provider['base_url'])}",
            f"env_key = {json.dumps(provider['api_key_env'])}",
            f"wire_api = {json.dumps(wire_api)}",
            "",
        ])
    config = "\n".join(lines)
    _write_managed_toml(codex_dir / "config.toml", config)
    for skill in skills:
        skill_dir = workspace / ".codex" / "skills" / _safe_slug(skill["id"])
        _write_if_missing(skill_dir / "SKILL.md", skill["text"])
    for agent in agents:
        _write_if_missing(workspace / ".codex" / "agents" / f"{agent['id']}.md", agent["text"])


def _render_claude(
    workspace: Path,
    home: Path,
    agents_md: str,
    agents: list[dict[str, Any]],
    skills: list[dict[str, Any]],
) -> None:
    _write_managed_text(workspace / "CLAUDE.md", agents_md)
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    _write_managed_text(claude_dir / "CLAUDE.md", agents_md)
    _merge_json_file(
        workspace / ".mcp.json", {"mcpServers": claude_mcp_servers(workspace)}
    )
    prune_stale_mcp_entries(workspace / ".mcp.json", "mcpServers")
    for skill in skills:
        _write_if_missing(workspace / ".claude" / "commands" / f"{skill['id']}.md", skill["body"])
    for agent in agents:
        _write_if_missing(workspace / ".claude" / "agents" / f"{agent['id']}.md", agent["text"])


def claude_mcp_servers(workspace: Path) -> dict[str, Any]:
    """`mcpServers` block for Claude Code, built from the MCP registry.

    Remote servers reuse the same generated wrapper scripts OpenCode uses, so
    token resolution lives in exactly one place.
    """
    from app.mcp_registry import harness_servers

    scripts = sync_mcp_wrapper_scripts(workspace)

    servers: dict[str, Any] = {}
    for server in harness_servers():
        if server.transport == "stdio":
            servers[server.name] = {
                "command": server.command[0],
                "args": list(server.command[1:]),
                "env": {"LOOMAI_URL": "http://127.0.0.1:8000"},
            }
            continue
        servers[server.name] = {"command": "bash", "args": [str(scripts[server.name])]}
    return servers


def _render_antigravity(workspace: Path, agents_md: str, agents: list[dict[str, Any]], skills: list[dict[str, Any]]) -> None:
    _write_managed_text(workspace / "antigravity" / "AGENTS.md", agents_md)
    for skill in skills:
        _write_if_missing(workspace / ".antigravity" / "skills" / f"{skill['id']}.md", skill["text"])
    for agent in agents:
        _write_if_missing(workspace / ".antigravity" / "agents" / f"{agent['id']}.md", agent["text"])


def _render_mapping(workspace: Path) -> None:
    mapping = """\
# LoomAI Harness Default Mapping

Source root: `/app/ai-tools/shared`

- Shared `FABRIC_AI.md` plus the external-harness operating contract renders to
  workspace `AGENTS.md`, Aider `CONVENTIONS.md`, Crush `CRUSH.md`, Goose
  `goose/AGENTS.md`, Pi `pi/AGENTS.md`, Codex `codex/AGENTS.md`, and Claude Code context.
- Network-service hard limits from `FABRIC_AI.md` are part of every generated
  harness context: L2Bridge is one site, L2STS is exactly two sites, L2PTP is
  exactly two interfaces, and FABNetv4/v6/Ext services are one site with up to
  255 VMs; multi-site L3 uses one FABNet service per site or per-node
  `add_fabnet`.
- Shared agents render to OpenCode, Crush, Codex, Claude Code, and Antigravity agent
  directories.
- Shared skills render to OpenCode, Crush, Pi, Codex, Claude Code command, and
  Antigravity skill directories.
- Provider defaults include ai-renci, FABRIC AI, NRP, and any configured custom
  providers via environment-key references. Existing user config values are
  preserved.
- Per-model defaults come from LoomAI's bundled and runtime model capability
  profiles plus cached model discovery:
  gpt-5.5 uses Responses-style reasoning with temperature omitted,
  qwen3-coder-30b uses temperature 0.3, gemma-4-27b keeps its 262K context,
  GLM-5 uses output-preferred reasoning budget defaults, and unknown models
  fall back to safe standard-tier settings instead of being omitted.
- Config-level campaign blockers are encoded in defaults: ai-renci Kimi uses
  the bare `Kimi-K2.6` provider model id, NRP gemma-class entries mark
  `omit_tool_choice`, and the local `loomai-harness` MCP schemas default
  submit/renew/weave leases to six hours; the backend enforces the user's
  Agent Lease Limit on every agent-initiated lease.
- The `loomai-harness` MCP server is shipped in the backend image as
  `python3 -m app.harness_mcp_server`; external harnesses launch it over stdio
  and it proxies calls to the local LoomAI backend.
- Goose defaults include a native stdio extension for `loomai-harness`, and
  Claude Code defaults include workspace `.mcp.json` wiring for the same local
  MCP server.
- Pi defaults render to `pi/agent/*`, `~/.pi/agent/*`, `pi/pi-fabric`, and
  `~/.local/bin/pi-fabric`; Pi 0.80.3 has no built-in MCP support, so LoomAI
  installs `pi-mcp-adapter` lazily and wires the local `loomai-harness` MCP
  server through that adapter with `PYTHONPATH=/app`, direct tools, eager
  lifecycle, and one-hour request timeouts. The ai-renci gpt-5.5 entry uses
  the Responses API path.
- Run `loomai tools sync` (alias: `loomai ai tools sync`) to regenerate these
  LoomAI-managed defaults without rebuilding or restarting the container.
- Settings > AI Tools > Harnesses shows status for OpenCode, Goose, Pi, Aider,
  Crush, Codex, and Claude Code, can run per-harness Configure/Sync without
  touching user-owned overrides, and can Reset a harness after confirmation to
  overwrite its expected config files with pristine defaults. It can also
  Uninstall a harness, removing installed packages and LoomAI-owned runtime
  state while preserving config by default; the optional remove-configuration
  path removes expected generated config files and refuses active harness
  processes. Backend APIs are
  `GET /api/ai/tools/harnesses`, `GET /api/ai/tools/harnesses/{name}/status`,
  `POST /api/ai/tools/harnesses/{name}/sync`,
  `POST /api/ai/tools/harnesses/{name}/reset`,
  `POST /api/ai/tools/{name}/uninstall?remove_config=true`, and
  `GET /api/ai/tools/harnesses/{name}/docs`.
- Post-deploy lifecycle parity checks are source-controlled at
  `/app/scripts/verify_harness_lifecycle.py`; after an owner-approved rebuild,
  run `python3 /app/scripts/verify_harness_lifecycle.py --execute` to cover
  install-button, reset-button, default uninstall, remove-config uninstall, and
  reinstall outcomes for all managed harnesses.
"""
    _write_managed_text(workspace / ".loomai" / "harness-defaults" / "MAPPING.md", mapping)


def _merge_json_file(path: Path | str, defaults: dict[str, Any]) -> None:
    path = Path(path)
    existing: Any = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    merged = _merge_defaults(existing if isinstance(existing, dict) else {}, defaults)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _merge_defaults(existing: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(defaults)
    for key, value in existing.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_defaults(value, merged[key])
        else:
            merged[key] = value
    return merged


def _write_managed_text(path: Path, text: str) -> None:
    if path.is_file():
        current = path.read_text(encoding="utf-8", errors="replace")
        if MANAGED_TEXT_MARKER not in current and not _looks_like_legacy_managed(current):
            return
    if MANAGED_TEXT_MARKER not in text:
        text = f"{MANAGED_TEXT_MARKER}\n\n{text}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_managed_toml(path: Path, text: str) -> None:
    if path.is_file():
        current = path.read_text(encoding="utf-8", errors="replace")
        if MANAGED_TOML_MARKER not in current and "LoomAI generated Codex defaults" not in current:
            return
    if MANAGED_TOML_MARKER not in text:
        text = f"{MANAGED_TOML_MARKER}\n\n{text}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_managed_code(path: Path, text: str) -> None:
    if path.is_file():
        current = path.read_text(encoding="utf-8", errors="replace")
        if MANAGED_CODE_MARKER not in current:
            return
    if MANAGED_CODE_MARKER not in text:
        text = f"{MANAGED_CODE_MARKER}\n{text}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_managed_executable(path: Path, text: str) -> None:
    if path.is_file():
        current = path.read_text(encoding="utf-8", errors="replace")
        if MANAGED_SHELL_MARKER not in current:
            return
    if MANAGED_SHELL_MARKER not in text:
        lines = text.splitlines()
        if lines and lines[0].startswith("#!"):
            text = "\n".join([lines[0], MANAGED_SHELL_MARKER, *lines[1:]]) + "\n"
        else:
            text = f"{MANAGED_SHELL_MARKER}\n{text}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _write_if_missing(path: Path, text: str, *, mode: int | None = None) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if mode is not None:
            path.chmod(mode)


def _looks_like_legacy_managed(text: str) -> bool:
    head = text[:4096]
    return (
        "<!-- LoomAI-managed AGENTS.md" in head
        or head.startswith("# FABRIC AI")
        or head.startswith("# How to Execute FABRIC Operations")
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _first_sentence(text: str) -> str:
    compact = re.sub(r"\s+", " ", text.strip())
    return compact.split(". ", 1)[0][:180] if compact else ""


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return slug or "skill"


def _simple_yaml(value: Any, indent: int = 0) -> str:
    spaces = " " * indent
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{spaces}{key}:")
                lines.append(_simple_yaml(item, indent + 2).rstrip())
            else:
                lines.append(f"{spaces}{key}: {json.dumps(item)}")
        return "\n".join(lines) + "\n"
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{spaces}-")
                lines.append(_simple_yaml(item, indent + 2).rstrip())
            else:
                lines.append(f"{spaces}- {json.dumps(item)}")
        return "\n".join(lines) + "\n"
    return f"{spaces}{json.dumps(value)}\n"


if __name__ == "__main__":
    raise SystemExit(main())
