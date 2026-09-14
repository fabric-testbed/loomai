"""WebSocket AI terminal endpoints — PTY-based terminals for AI coding tools."""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import shutil
import signal
import struct
import subprocess
import termios
import time
import urllib.request
from typing import Iterable

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from app import terminal_sessions as _term_sessions
from app import terminal_auth as _term_auth

from app.ai_tool_adapters import (
    load_tool_assets,
    render_asset_index,
    render_body_only,
    render_canonical_markdown,
    sync_markdown_files,
    sync_skill_directories,
    write_text,
)
from app.settings_manager import (
    get_ai_renci_api_key as _get_ai_renci_api_key,
    get_fabric_api_key as _get_ai_api_key,
    get_nrp_api_key as _get_nrp_api_key,
    normalize_ai_endpoint_style,
)
from app.tracking_headers import add_tracking_headers, get_tracking_headers
from app.tool_installer import (
    is_tool_installed, install_tool, uninstall_tool, get_tool_binary_path,
    get_tool_env, get_all_tool_status, TOOL_REGISTRY,
    check_disk_space, tool_needs_upgrade,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _is_public_managed_harness_tool(tool_id: str) -> bool:
    try:
        from app.harness_config import PUBLIC_MANAGED_HARNESSES

        return tool_id in PUBLIC_MANAGED_HARNESSES
    except Exception:
        return tool_id in {"opencode", "goose", "pi", "aider", "crush", "codex", "claude"}

def _contract_mode() -> bool:
    return os.environ.get("LOOMAI_CONTRACT_MODE", "").strip() == "1"


def _contract_model_data() -> dict:
    return {
        "fabric": [
            {
                "id": "fabric/contract-model",
                "name": "fabric/contract-model",
                "healthy": True,
                "model_type": "chat",
                "context_length": 131072,
                "tier": "large",
                "supports_tools": True,
            }
        ],
        "nrp": [],
        "custom": {},
        "default": "fabric/contract-model",
        "has_key": {"fabric": True, "nrp": False},
        "errors": {"fabric": "", "nrp": ""},
        "models": ["fabric/contract-model"],
        "nrp_models": [],
    }


def _ai_server_url() -> str:
    from app.settings_manager import get_ai_server_url
    return get_ai_server_url()

def _nrp_server_url() -> str:
    from app.settings_manager import get_nrp_server_url
    return get_nrp_server_url()


def _ai_renci_api_key_or_fabric(fabric_api_key: str = "") -> str:
    return _get_ai_renci_api_key() or fabric_api_key


def _model_proxy_port() -> int:
    from app.settings_manager import get_model_proxy_port
    return get_model_proxy_port()

# Keep string constants for backward compat with existing references
AI_SERVER_URL = "https://ai.fabric-testbed.net"
NRP_SERVER_URL = "https://ellm.nrp-nautilus.io"

# Preferred model for the primary/default slot — first match wins
_PREFERRED_MODELS = [
    "qwen3-coder-30b",
    "qwen3-coder",
    "qwen3-30b",
    "qwen3",
    "deepseek-coder",
]

# Preferred small model (for title, summary, compaction)
_PREFERRED_SMALL = [
    "qwen3-coder-8b",
    "qwen3-8b",
    "qwen3-coder-30b",
]

# Default context sizes for NRP models (NRP doesn't report context via API)
_NRP_CONTEXT_DEFAULTS: dict[str, int] = {
    "gpt-oss": 131072,
    "kimi": 131072,
    "minimax-m2": 131072,
    "olmo": 32768,
    "glm-4.7": 131072,
    "glm-5": 32768,
    "qwen3": 32768,
    "qwen3-small": 32768,
    "qwen3-4bit": 32768,
    "qwen3-27b": 131072,
    "gemma": 32768,
    "gemma-small": 32768,
    "gemma-small-e4b": 32768,
    "gh200-test": 32768,
}
_NRP_EXCLUDE = {"qwen3-embedding"}  # Embedding models, not for chat

# Fallback context sizes for FABRIC AI models (if /v1/model/info fails).
# These match the values advertised by FABRIC AI's LiteLLM proxy and are used
# as a safety net so the chat handler never falls back to the 32K tier default.
_FABRIC_CONTEXT_DEFAULTS: dict[str, int] = {
    "gpt-oss-20b": 131072,
    "qwen3-coder-30b": 262144,
    "nemotron-nano-30b": 262144,
    "gemma-4-27b": 262144,
}


def _fetch_models(api_key: str) -> list[dict]:
    """Query the FABRIC AI server for available models with metadata."""
    url = f"{_ai_server_url()}/v1/models"
    req = urllib.request.Request(url, headers=add_tracking_headers({
        "Authorization": f"Bearer {api_key}",
    }))
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
        return [
            {
                "id": m["id"],
                "context_length": m.get("context_length") or m.get("context_window"),
            }
            for m in body.get("data", [])
        ]
    except Exception as e:
        logger.warning("Could not fetch models from %s: %s", url, e)
        return []


def _fetch_nrp_models(api_key: str) -> list[dict]:
    """Query the NRP LLM server for available models with metadata."""
    url = f"{_nrp_server_url()}/v1/models"
    req = urllib.request.Request(url, headers=add_tracking_headers({
        "Authorization": f"Bearer {api_key}",
    }))
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
        return [
            {
                "id": m["id"],
                "context_length": m.get("context_length") or m.get("context_window"),
            }
            for m in body.get("data", [])
        ]
    except Exception as e:
        logger.warning("Could not fetch models from %s: %s", url, e)
        return []


def _fetch_fabric_model_info(api_key: str) -> list[dict]:
    """Fetch models from FABRIC AI /v1/model/info (includes context sizes).

    Returns list of {"id": str, "context_length": int}.
    Falls back to empty list on error.
    """
    import httpx

    url = f"{_ai_server_url()}/v1/model/info"
    try:
        resp = httpx.get(
            url,
            headers={"x-litellm-api-key": api_key, **get_tracking_headers()},
            timeout=10.0,
        )
        if resp.status_code == 404:
            logger.warning("FABRIC /v1/model/info not available (404) — will fall back to /v1/models")
            return []
        resp.raise_for_status()
        body = resp.json()
        results = []
        for entry in body.get("data", []):
            model_name = entry.get("model_name", "")
            model_info = entry.get("model_info", {})
            max_tokens = model_info.get("max_tokens")
            if model_name:
                results.append({
                    "id": model_name,
                    "context_length": max_tokens,
                })
        return results
    except Exception as e:
        logger.warning("Could not fetch model info from %s: %s", url, e)
        return []


def _try_chat_completions(server_url: str, headers: dict, model_id: str,
                          timeout: int) -> tuple[bool, str, str]:
    """Try the standard /v1/chat/completions endpoint.
    Returns (success, error_body, err_code_str)."""
    data = json.dumps({
        "model": model_id,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 16,
    }).encode()
    req = urllib.request.Request(
        f"{server_url}/v1/chat/completions", data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200, "", ""
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        return False, err_body, str(e.code)
    except Exception as e:
        return False, str(e), "timeout"


def _try_responses_api(server_url: str, headers: dict, model_id: str,
                       timeout: int) -> bool:
    """Try the OpenAI Responses API (/v1/responses) as a fallback.
    Some newer models (e.g. gpt-5.5) use 'input' instead of 'messages'."""
    data = json.dumps({
        "model": model_id,
        "input": "hi",
        "max_output_tokens": 16,
    }).encode()
    req = urllib.request.Request(
        f"{server_url}/v1/responses", data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _check_model_health(server_url: str, api_key: str, model_id: str,
                        timeout: int = 30) -> tuple[bool, str]:
    """Verify a model is reachable.

    Returns (healthy, model_type) where model_type is one of:
    - "chat"      : model responded to /v1/chat/completions
    - "responses" : model uses the OpenAI Responses API (/v1/responses)
    - "non-chat"  : model is listed by the provider but doesn't support text
                    generation (e.g. image, audio, embedding). Still healthy.
    - "down"      : model is unreachable, timed out, or returned an auth error.

    No model names are hard-coded; the type is inferred from the API response.
    """
    headers = add_tracking_headers({
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    })

    # 1. Try standard chat completions
    ok, err_body, err_code = _try_chat_completions(
        server_url, headers, model_id, timeout)
    if ok:
        return True, "chat"

    # 2. Auth errors — model is inaccessible for this user
    if err_code in ("401", "403"):
        logger.debug("Model %s returned HTTP %s (auth error): %s",
                     model_id, err_code, err_body[:200])
        return False, "down"

    # 3. If the error mentions Responses API / 'input' parameter, try that
    if err_code == "400" and ("responses" in err_body.lower()
                              or "'input'" in err_body.lower()
                              or '"input"' in err_body.lower()):
        logger.info("Model %s rejected chat completions but hints at "
                    "Responses API — retrying with /v1/responses", model_id)
        if _try_responses_api(server_url, headers, model_id, timeout):
            logger.info("Model %s is healthy via Responses API", model_id)
            return True, "responses"
        # Responses API also failed — could be down or misconfigured
        logger.info("Model %s failed on both chat completions and "
                    "Responses API — marking down", model_id)
        return False, "down"

    # 4. Other client errors (400 without Responses hint, 404, 405, 422)
    #    indicate non-chat models (image generation, audio, embeddings)
    if err_code.isdigit() and 400 <= int(err_code) < 500:
        logger.info("Model %s returned HTTP %s on chat completions — "
                     "non-chat model; marking healthy. Error: %s",
                     model_id, err_code, err_body[:200])
        return True, "non-chat"

    # 5. Timeouts and server errors
    logger.debug("Model health check failed for %s (code=%s): %s",
                 model_id, err_code, err_body[:200])
    return False, "down"


def _check_model_health_with_endpoint_style(
    server_url: str,
    api_key: str,
    model_id: str,
    endpoint_style: str = "auto",
    timeout: int = 30,
) -> tuple[bool, str]:
    """Verify model health while honoring a forced endpoint style."""
    style = normalize_ai_endpoint_style(endpoint_style)
    if style == "auto":
        return _check_model_health(server_url, api_key, model_id, timeout=timeout)
    headers = add_tracking_headers({
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    })
    if style == "responses":
        ok = _try_responses_api(server_url, headers, model_id, timeout)
        return ok, "responses" if ok else "down"
    if style == "chat":
        ok, _err_body, _err_code = _try_chat_completions(
            server_url,
            headers,
            model_id,
            timeout,
        )
        return ok, "chat" if ok else "down"
    if style == "non-chat":
        return True, "non-chat"
    return _check_model_health(server_url, api_key, model_id, timeout=timeout)


def _model_ids(models: list) -> list[str]:
    """Extract model IDs from a list that may be strings or dicts."""
    return [m["id"] if isinstance(m, dict) else m for m in models]


def _pick_model(models: list, preferences: list[str], fallback: str) -> str:
    """Pick the best model from available list using preference order."""
    ids = _model_ids(models)
    for pref in preferences:
        for m in ids:
            if pref in m.lower():
                return m
    return ids[0] if ids else fallback


def _build_opencode_config(
    api_key: str,
    model_override: str = "",
    workspace_config: dict | None = None,
) -> dict:
    """Build an opencode.json config with models from the FABRIC AI server.

    Generates a provider-based config using @ai-sdk/openai-compatible that
    connects directly to the FABRIC AI server with all available models.
    Also includes NRP models if an NRP API key is configured.

    If workspace_config is provided, merges mcp, agent, and command sections.

    Returns dict with internal keys _default and _allowed (stripped before
    writing to file).
    """
    models = _fetch_models(api_key)

    if model_override:
        default = model_override
        logger.info("Using user-selected model: %s", default)
    elif not models:
        default = "qwen3-coder-30b"
        logger.info("No models from server, using fallback: %s", default)
    else:
        logger.info("Available models from %s: %s", _ai_server_url(), models)
        default = _pick_model(models, _PREFERRED_MODELS, "qwen3-coder-30b")

    small = _pick_model(models, _PREFERRED_SMALL, default) if models else default

    from app.model_capability_defaults import harness_model_config

    try:
        from app.harness_config import _opencode_providers

        providers: dict = _opencode_providers()
    except Exception:
        providers = {}

    # Build models dict — each available model gets an ideal harness entry.
    models_dict = {}
    for m in (_model_ids(models) if models else [default]):
        models_dict[m] = harness_model_config(m, "fabric")
    if default not in models_dict:
        models_dict[default] = harness_model_config(default, "fabric")
    if small not in models_dict:
        models_dict[small] = harness_model_config(small, "fabric")

    providers["fabric"] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "FABRIC AI",
            "options": {
                "baseURL": f"{_ai_server_url()}/v1",
                "apiKey": "{env:FABRIC_AI_API_KEY}",
            },
            "models": models_dict,
    }

    # Add NRP provider if key is available
    nrp_key = _get_nrp_api_key()
    if nrp_key:
        nrp_models = _fetch_nrp_models(nrp_key)
        if nrp_models:
            nrp_models_dict = {m: harness_model_config(m, "nrp") for m in _model_ids(nrp_models)}
            providers["nrp"] = {
                "npm": "@ai-sdk/openai-compatible",
                "name": "NRP",
                "options": {
                    "baseURL": f"{_nrp_server_url()}/v1",
                    "apiKey": "{env:NRP_API_KEY}",
                },
                "models": nrp_models_dict,
            }
            logger.info("NRP models added: %s", nrp_models)

    config: dict = {
        "$schema": "https://opencode.ai/config.json",
        "provider": providers,
        "model": f"fabric/{default}",
        "small_model": f"fabric/{small}",
        # Internal: used to configure the model proxy (not written to JSON)
        "_default": default,
        "_allowed": _model_ids(models) if models else [default],
    }

    # Merge workspace config (mcp, agent, command)
    if workspace_config:
        for key in ("mcp", "agent", "command"):
            if key in workspace_config:
                config[key] = workspace_config[key]

    return config


_MODEL_PROXY_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "scripts", "model_proxy.py",
)
_MODEL_PROXY_PORT = 9199  # Fallback; prefer _model_proxy_port() accessor

# Paths to AI tool assets (inside the container)
_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_AI_TOOLS_DIR = os.path.join(_APP_ROOT, "ai-tools")
_SHARED_DIR = os.path.join(_AI_TOOLS_DIR, "shared")
_FABRIC_AI_MD_PATH = os.path.join(_SHARED_DIR, "FABRIC_AI.md")
_AIDER_DEFAULTS_DIR = os.path.join(_AI_TOOLS_DIR, "aider")
_CLAUDE_DEFAULTS_DIR = os.path.join(_AI_TOOLS_DIR, "claude-code")
_CRUSH_DEFAULTS_DIR = os.path.join(_AI_TOOLS_DIR, "crush")
_DEEPAGENTS_DEFAULTS_DIR = os.path.join(_AI_TOOLS_DIR, "deepagents")

# Skills to skip (conflict with OpenCode internals)
_SKIP_SKILLS = {"compact", "help"}


def _custom_asset_dir(kind: str) -> str | None:
    """Return user-custom asset dir for 'skills' or 'agents' if available."""
    try:
        from app.settings_manager import get_storage_dir
        path = os.path.join(get_storage_dir(), ".loomai", kind)
    except Exception:
        return None
    return path if os.path.isdir(path) else None


def _load_tool_skills(*, excluded_ids: Iterable[str] = ()) -> list:
    return load_tool_assets(
        os.path.join(_SHARED_DIR, "skills"),
        custom_dir=_custom_asset_dir("skills"),
        asset_type="skill",
        excluded_ids=excluded_ids,
    )


def _load_tool_agents(*, excluded_ids: Iterable[str] = ()) -> list:
    return load_tool_assets(
        os.path.join(_SHARED_DIR, "agents"),
        custom_dir=_custom_asset_dir("agents"),
        asset_type="agent",
        excluded_ids=excluded_ids,
    )


def _write_asset_index(cwd: str) -> None:
    """Write compact read-only skill/agent inventory for context-only tools."""
    skills = _load_tool_skills(excluded_ids=_SKIP_SKILLS)
    agents = _load_tool_agents()
    write_text(os.path.join(cwd, "AI_ASSETS.md"), render_asset_index(skills, agents))

# Per-tool preambles explaining how each tool should execute FABRIC operations.
# Prepended to AGENTS.md so the AI knows its available methods.
_TOOL_PREAMBLES = {
    "opencode": """\
# How to Execute FABRIC Operations (OpenCode)

You are running inside the LoomAI container. **Always use the `loomai` CLI** as your
primary way to manage FABRIC slices, resources, SSH, and file transfers. It is faster
and more reliable than curl, and outputs structured data (`--format json` for parsing).

**Quick reference:**
```bash
loomai slices list                                # List slices
loomai slices create my-exp                       # Create draft
loomai nodes add my-exp node1 --site RENC --cores 4 --ram 16 --disk 50
loomai slices submit my-exp --wait                # Submit and wait for ready
loomai ssh my-exp node1 -- hostname               # Run command on node
loomai exec my-exp "apt update" --all --parallel  # Run on all nodes
loomai scp my-exp node1 ./file.sh /tmp/file.sh    # Upload file
loomai sites find --cores 8 --gpu GPU_RTX6000     # Find sites
loomai weaves run Hello_FABRIC --args SLICE_NAME=test  # Run weave
loomai artifacts list --remote                    # Browse marketplace
```

**Fallback methods** (for complex automation only):
- curl to `http://localhost:8000/api/*`
- Python scripts using FABlib (`from fabrictestbed_extensions.fablib.fablib import FablibManager`)

**MCP Tool Calling (advanced):**
OpenCode can also call FABRIC operations via MCP tool servers (configured in `.opencode/mcp-scripts/`).
These provide direct API access without shell commands. Prefer `loomai` CLI for most tasks.

---

""",
    "aider": """\
# How to Execute FABRIC Operations (Aider)

You are running inside the LoomAI container. **Use the `loomai` CLI** for all FABRIC
operations. You do NOT have tool-calling — run shell commands or write code files.

```bash
loomai slices list                    # List slices
loomai slices create my-exp           # Create draft
loomai nodes add my-exp node1 --site auto --cores 4 --ram 16 --disk 50
loomai slices submit my-exp --wait    # Submit and wait
loomai ssh my-exp node1 -- hostname   # SSH command
loomai exec my-exp "cmd" --all        # Run on all nodes
loomai sites list --available         # Available sites
```

All commands support `--format json` for structured output.

---

""",
    "claude-code": """\
# How to Execute FABRIC Operations (Claude Code)

You are running inside the LoomAI container. **Use the `loomai` CLI** for all FABRIC
operations — it's the fastest and most reliable method.

```bash
loomai slices list                                # List slices
loomai slices create my-exp && loomai nodes add my-exp node1 --site RENC --cores 4 --ram 16
loomai slices submit my-exp --wait --timeout 600  # Submit and wait
loomai ssh my-exp node1 -- "uname -a"             # SSH command
loomai exec my-exp "df -h" --all --parallel       # Multi-node exec
loomai sites find --gpu GPU_RTX6000               # Find GPU sites
loomai --format json slices show my-exp           # JSON output for parsing
```

---

""",
    "crush": """\
# How to Execute FABRIC Operations (Crush)

You are running inside the LoomAI container. **Use the `loomai` CLI** for FABRIC operations.

```bash
loomai slices list                    # List slices
loomai sites list --available         # Available sites
loomai ssh my-exp node1 -- hostname   # SSH command
loomai exec my-exp "cmd" --all        # Multi-node exec
```

---

""",
    "deepagents": """\
# How to Execute FABRIC Operations (Deep Agents)

You are running inside the LoomAI container. **Use the `loomai` CLI** as your primary
tool for managing FABRIC slices, SSH, file transfers, and resource queries.

```bash
loomai slices list                                # List slices
loomai slices create my-exp                       # Create draft
loomai nodes add my-exp node1 --site auto --cores 4 --ram 16 --disk 50
loomai slices submit my-exp --wait                # Submit and wait
loomai exec my-exp "apt update" --all --parallel  # Multi-node parallel exec
loomai scp my-exp ./data.tar.gz /tmp/ --all       # Upload to all nodes
loomai sites find --cores 16 --ram 64             # Find matching sites
```

---

""",
    "antigravity": """\
# How to Execute FABRIC Operations (Antigravity)

You are running inside the LoomAI container. **Use the `loomai` CLI** as your primary
tool for managing FABRIC slices, SSH, file transfers, and resource queries.

```bash
loomai slices list                                # List slices
loomai slices create my-exp                       # Create draft
loomai nodes add my-exp node1 --site auto --cores 4 --ram 16 --disk 50
loomai slices submit my-exp --wait                # Submit and wait
loomai exec my-exp "apt update" --all --parallel  # Multi-node parallel exec
loomai scp my-exp ./data.tar.gz /tmp/ --all       # Upload to all nodes
loomai sites find --cores 16 --ram 64             # Find matching sites
```

---

""",
    "codex": """\
# How to Execute FABRIC Operations (Codex)

You are running inside the LoomAI container. **Use the `loomai` CLI** as your primary
tool for managing FABRIC slices, SSH, file transfers, and resource queries.

```bash
loomai slices list                                # List slices
loomai slices create my-exp                       # Create draft
loomai nodes add my-exp node1 --site auto --cores 4 --ram 16 --disk 50
loomai slices submit my-exp --wait                # Submit and wait
loomai exec my-exp "apt update" --all --parallel  # Multi-node parallel exec
loomai scp my-exp ./data.tar.gz /tmp/ --all       # Upload to all nodes
loomai sites find --cores 16 --ram 64             # Find matching sites
```

For direct REST calls and weave helpers, honor `LOOMAI_API_URL` or `LOOMAI_URL`.
Use `http://127.0.0.1:8000` on the Docker host or inside the backend container,
and `http://backend:8000` from another docker-compose service. If localhost
works on the host but fails in Codex, treat it as a network namespace or sandbox
issue and rerun through the backend-owned path or set the correct URL.

---

""",
}


_GENERATED_AGENTS_MARKER = "<!-- LoomAI-managed AGENTS.md; edit ai-tools/shared/FABRIC_AI.md instead. -->"


def _is_managed_agents_md(path: str) -> bool:
    try:
        with open(path) as f:
            head = f.read(4096)
    except OSError:
        return False
    return (
        _GENERATED_AGENTS_MARKER in head
        or head.startswith("# How to Execute FABRIC Operations")
        or head.startswith("# FABRIC AI Assistant")
        or head.startswith("# FABRIC AI Coding Assistant")
    )


def _write_agents_md(cwd: str, tool_name: str) -> None:
    """Write AGENTS.md with a tool-specific preamble + shared FABRIC_AI.md content."""
    agents_md = os.path.join(cwd, "AGENTS.md")
    if os.path.isfile(agents_md) and not _is_managed_agents_md(agents_md):
        return  # Don't overwrite custom user instructions.
    if not os.path.isfile(_FABRIC_AI_MD_PATH):
        return
    preamble = _TOOL_PREAMBLES.get(tool_name, "")
    with open(_FABRIC_AI_MD_PATH) as f:
        content = f.read()
    with open(agents_md, "w") as f:
        f.write(f"{_GENERATED_AGENTS_MARKER}\n\n{preamble}{content}")
    logger.info("Wrote AGENTS.md for %s (with preamble)", tool_name)


def _setup_opencode_workspace(cwd: str) -> dict:
    """Set up FABRIC tools, skills, agents, MCP servers, and instructions.

    Creates the following in the working directory:
    - AGENTS.md — comprehensive FABRIC instructions (from FABRIC_AI.md)
    - .opencode/skills/<name>/SKILL.md — FABRIC skill definitions
    - .opencode/agent-prompts/<name>.md — agent prompt files
    - .opencode/mcp-scripts/<name>.sh — MCP server wrapper scripts

    Returns dict with extra opencode.json config sections: mcp, agent, command.
    """
    from app.user_context import get_token_path
    config_dir = os.environ.get(
        "FABRIC_CONFIG_DIR", os.path.join(cwd, "fabric_config"),
    )
    token_file = get_token_path()
    oc_dir = os.path.join(cwd, ".opencode")

    # --- AGENTS.md (auto-discovered by OpenCode as project instructions) ---
    _write_agents_md(cwd, "opencode")

    # --- Skills → .opencode/skills/<name>/SKILL.md ---
    skills = _load_tool_skills(excluded_ids=_SKIP_SKILLS)
    skill_count = sync_skill_directories(
        skills,
        os.path.join(oc_dir, "skills"),
        renderer=render_canonical_markdown,
    )
    logger.info("Created %d OpenCode skills", skill_count)

    # --- Agent prompts → .opencode/agent-prompts/<name>.md ---
    prompts_dir = os.path.join(oc_dir, "agent-prompts")
    os.makedirs(prompts_dir, exist_ok=True)
    agent_cfg: dict = {}
    agents = _load_tool_agents()
    expected_prompts = set()
    for agent in agents:
        name = agent.asset_id
        expected_prompts.add(f"{name}.md")
        write_text(os.path.join(prompts_dir, f"{name}.md"), render_body_only(agent))

        agent_cfg[name] = {
            "description": str(agent.metadata.get("description", "")),
            "prompt": "{file:.opencode/agent-prompts/" + name + ".md}",
            "mode": "subagent",
        }
    for fname in os.listdir(prompts_dir):
        if fname.endswith(".md") and fname not in expected_prompts:
            os.remove(os.path.join(prompts_dir, fname))
    logger.info("Created %d OpenCode agents", len(agent_cfg))

    # --- MCP server wrapper scripts ---
    # Only fabric-reports is included here. fabric-api MCP is intentionally
    # excluded — in-container AI tools should use the FABlib Python API
    # directly (via fabric_* tools) which is faster and more reliable.
    mcp_dir = os.path.join(oc_dir, "mcp-scripts")
    os.makedirs(mcp_dir, exist_ok=True)
    # Remove stale fabric-api script from previous versions
    stale_api_script = os.path.join(mcp_dir, "fabric-api.sh")
    if os.path.exists(stale_api_script):
        os.remove(stale_api_script)
    mcp_cfg: dict = {}
    for sname, url in [
        ("fabric-reports", "https://reports.fabric-testbed.net/mcp"),
    ]:
        script = os.path.join(mcp_dir, f"{sname}.sh")
        py_cmd = (
            f'import json; print(json.load(open("{token_file}"))["id_token"])'
        )
        with open(script, "w") as f:
            f.write("#!/bin/bash\n")
            f.write("set -euo pipefail\n")
            f.write(f"TOKEN=$(python3 -c '{py_cmd}')\n")
            f.write(
                f'exec npx -y mcp-remote "{url}"'
                f' --header "Authorization: Bearer $TOKEN"\n'
            )
        os.chmod(script, 0o755)
        mcp_cfg[sname] = {
            "type": "local",
            "command": ["bash", script],
            "enabled": True,
            "timeout": 15000,
        }
    mcp_cfg["loomai-harness"] = {
        "type": "local",
        "command": ["python3", "-m", "app.harness_mcp_server"],
        "enabled": True,
        "timeout": 30000,
    }
    logger.info("Created MCP wrapper scripts for %s", list(mcp_cfg.keys()))

    # --- Custom commands ---
    cmd_cfg = {
        "create-slice": {
            "description": "Create a new FABRIC slice",
            "template": (
                "Create a new FABRIC slice based on the user's requirements. "
                "Use fabric_create_slice or fabric_create_from_template. $input"
            ),
        },
        "deploy": {
            "description": "Deploy a slice from a template",
            "template": (
                "Deploy a FABRIC slice from a template. List available "
                "templates, create the draft, and submit it. $input"
            ),
        },
        "sites": {
            "description": "Show FABRIC site availability",
            "template": "Show available FABRIC sites and resources. $input",
        },
        "slices": {
            "description": "List all FABRIC slices",
            "template": "List all FABRIC slices with current status. $input",
        },
    }

    return {"mcp": mcp_cfg, "agent": agent_cfg, "command": cmd_cfg}


def _setup_aider_workspace(cwd: str) -> None:
    """Seed Aider configuration and FABRIC context into the workspace.

    Copies:
    - .aider.conf.yml from ai-tools/aider/
    - AGENTS.md (shared FABRIC context, also used by Aider as read-only)

    NRP support: Aider connects via the model proxy (OPENAI_API_BASE in
    TOOL_CONFIGS) which routes to both FABRIC and NRP providers.
    """
    # Shared FABRIC context with Aider-specific preamble
    _write_agents_md(cwd, "aider")
    _write_asset_index(cwd)

    # Aider config
    src_conf = os.path.join(_AIDER_DEFAULTS_DIR, ".aider.conf.yml")
    if os.path.isfile(src_conf):
        dst_conf = os.path.join(cwd, ".aider.conf.yml")
        if not os.path.isfile(dst_conf):
            shutil.copy2(src_conf, dst_conf)
            logger.info("Wrote .aider.conf.yml")

    # Aider ignore patterns
    src_ignore = os.path.join(_AIDER_DEFAULTS_DIR, ".aiderignore")
    if os.path.isfile(src_ignore):
        dst_ignore = os.path.join(cwd, ".aiderignore")
        if not os.path.isfile(dst_ignore):
            shutil.copy2(src_ignore, dst_ignore)
            logger.info("Wrote .aiderignore")


def _setup_claude_workspace(cwd: str) -> None:
    """Seed Claude Code CLI configuration and FABRIC context into the workspace.

    Copies:
    - CLAUDE.md from ai-tools/claude-code/
    - AGENTS.md (shared FABRIC context, referenced by CLAUDE.md)
    - .claude/commands/*.md — shared skills as Claude Code slash commands
    """
    # Shared FABRIC context with Claude Code-specific preamble
    _write_agents_md(cwd, "claude-code")

    # Claude Code project instructions
    src_claude = os.path.join(_CLAUDE_DEFAULTS_DIR, "CLAUDE.md")
    if os.path.isfile(src_claude):
        dst_claude = os.path.join(cwd, "CLAUDE.md")
        shutil.copy2(src_claude, dst_claude)
        logger.info("Wrote CLAUDE.md for Claude Code CLI")

    # Shared skills → .claude/commands/<name>.md (Claude Code slash commands)
    cmds_dir = os.path.join(cwd, ".claude", "commands")
    skill_count = sync_markdown_files(
        _load_tool_skills(),
        cmds_dir,
        renderer=render_body_only,
    )
    logger.info("Created %d Claude Code commands from shared skills", skill_count)


def _setup_crush_workspace(cwd: str, api_key: str, model_override: str = "") -> None:
    """Seed Crush configuration and FABRIC context into the workspace.

    Creates:
    - AGENTS.md (shared FABRIC context)
    - .crush.json with FABRIC and NRP LLM providers configured
    """
    # Shared FABRIC context with Crush-specific preamble
    _write_agents_md(cwd, "crush")

    # Build .crush.json with FABRIC and NRP providers
    models = _fetch_models(api_key) if api_key else []
    default_model = model_override if model_override else (
        _pick_model(models, _PREFERRED_MODELS, "qwen3-coder-30b") if models else "qwen3-coder-30b"
    )

    fabric_model_ids = _model_ids(models) if models else [default_model]
    fabric_models = [{"id": model_id, "name": model_id} for model_id in fabric_model_ids]

    providers: dict = {
        "fabric": {
            "id": "fabric",
            "base_url": f"{_ai_server_url()}/v1",
            "type": "openai",
            "api_key": api_key,
            "models": fabric_models,
        }
    }

    nrp_key = _get_nrp_api_key()
    if nrp_key:
        nrp_models = _fetch_nrp_models(nrp_key)
        if nrp_models:
            nrp_model_ids = _model_ids(nrp_models)
            providers["nrp"] = {
                "id": "nrp",
                "base_url": f"{_nrp_server_url()}/v1",
                "type": "openai",
                "api_key": nrp_key,
                "models": [{"id": model_id, "name": model_id} for model_id in nrp_model_ids],
            }

    crush_config: dict = {
        "$schema": "https://charm.land/crush.json",
        "providers": providers,
        "model": f"fabric:{default_model}",
    }

    # Copy template from ai-tools/crush/ if exists, else write generated config
    src_template = os.path.join(_CRUSH_DEFAULTS_DIR, ".crush.json")
    if os.path.isfile(src_template):
        with open(src_template) as f:
            try:
                template = json.load(f)
                # Merge providers and model into the template
                template["providers"] = providers
                template["model"] = f"fabric:{default_model}"
                crush_config = template
            except json.JSONDecodeError:
                pass

    dst = os.path.join(cwd, ".crush.json")
    from app.harness_config import _merge_json_file
    _merge_json_file(dst, crush_config)
    logger.info("Wrote .crush.json for Crush with %d providers", len(providers))

    # Adapt shared + user-custom skills and agents so Crush has FABRIC context.
    skill_count = sync_markdown_files(
        _load_tool_skills(),
        os.path.join(cwd, ".crush", "skills"),
        renderer=render_canonical_markdown,
    )
    agent_count = sync_markdown_files(
        _load_tool_agents(),
        os.path.join(cwd, ".crush", "agents"),
        renderer=render_canonical_markdown,
    )
    logger.info("Synced %d skills and %d agents to .crush/", skill_count, agent_count)


def _setup_deepagents_workspace(cwd: str, api_key: str = "", model_override: str = "") -> None:
    """Seed Deep Agents configuration and FABRIC context into the workspace.

    Creates:
    - AGENTS.md (shared FABRIC context)
    - .deepagents/AGENTS.md (Deep Agents project instructions)
    - .deepagents/config.json (FABRIC + NRP provider config with models)
    """
    # Shared FABRIC context with Deep Agents-specific preamble
    _write_agents_md(cwd, "deepagents")

    # Deep Agents project instructions
    da_dir = os.path.join(cwd, ".deepagents")
    os.makedirs(da_dir, exist_ok=True)
    src_agents = os.path.join(_DEEPAGENTS_DEFAULTS_DIR, "AGENTS.md")
    if os.path.isfile(src_agents):
        shutil.copy2(src_agents, os.path.join(da_dir, "AGENTS.md"))
        logger.info("Wrote .deepagents/AGENTS.md for Deep Agents")

    # Adapt shared + user-custom skills and agents into .deepagents/.
    skill_count = sync_markdown_files(
        _load_tool_skills(),
        os.path.join(da_dir, "skills"),
        renderer=render_canonical_markdown,
    )
    agent_count = sync_markdown_files(
        _load_tool_agents(),
        os.path.join(da_dir, "agents"),
        renderer=render_canonical_markdown,
    )
    logger.info("Synced %d skills and %d agents to .deepagents/", skill_count, agent_count)

    # Build provider config with available models (like Crush)
    models = _fetch_models(api_key) if api_key else []
    default_model = model_override if model_override else (
        _pick_model(models, _PREFERRED_MODELS, "qwen3-coder-30b") if models else "qwen3-coder-30b"
    )

    providers: dict = {
        "fabric": {
            "id": "fabric",
            "base_url": f"{_ai_server_url()}/v1",
            "type": "openai",
            "api_key": api_key,
            "models": _model_ids(models) if models else [default_model],
        }
    }

    nrp_key = _get_nrp_api_key()
    if nrp_key:
        nrp_models = _fetch_nrp_models(nrp_key)
        if nrp_models:
            providers["nrp"] = {
                "id": "nrp",
                "base_url": f"{_nrp_server_url()}/v1",
                "type": "openai",
                "api_key": nrp_key,
                "models": _model_ids(nrp_models),
            }

    config = {
        "providers": providers,
        "default_provider": "fabric",
        "default_model": default_model,
    }

    config_path = os.path.join(da_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    logger.info("Wrote .deepagents/config.json with %d providers, default model: %s",
                len(providers), default_model)


def _setup_antigravity_workspace(cwd: str) -> None:
    """Seed Antigravity CLI configuration and FABRIC context into the workspace.

    Copies AGENTS.md (shared FABRIC context) so the tool has domain knowledge.
    """
    _write_agents_md(cwd, "antigravity")
    _write_asset_index(cwd)
    sync_markdown_files(
        _load_tool_skills(),
        os.path.join(cwd, ".antigravity", "skills"),
        renderer=render_canonical_markdown,
    )
    sync_markdown_files(
        _load_tool_agents(),
        os.path.join(cwd, ".antigravity", "agents"),
        renderer=render_canonical_markdown,
    )
    logger.info("Set up Antigravity workspace at %s", cwd)


def _toml_safe_id(name: str) -> str:
    """Convert a provider display name to a TOML-safe bare key (lowercase, hyphens)."""
    import re
    safe = re.sub(r'[^a-zA-Z0-9-]', '-', name.strip().lower())
    safe = re.sub(r'-+', '-', safe).strip('-')
    return safe or "custom"


# Preferred model patterns for Codex (in priority order).
# Matches are checked as substrings against model IDs.
_CODEX_MODEL_PREFERENCES = [
    "codex",       # purpose-built for Codex
    "gpt-5",       # latest GPT
    "gpt-4",       # GPT-4 family
    "claude",      # Anthropic
    "qwen",        # Qwen family
    "llama",       # Meta Llama
    "deepseek",    # DeepSeek
]


def _discover_codex_model(base_url: str, api_key: str) -> str:
    """Query a provider's /models endpoint and pick the best model for Codex.

    Returns the model ID string. Falls back to the first available model,
    or a generic default if discovery fails.
    """
    try:
        url = f"{base_url.rstrip('/')}/models"
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
        model_ids = [m["id"] for m in body.get("data", []) if m.get("id")]
        if not model_ids:
            return "gpt-4o"

        # Pick the best model by preference order
        for pref in _CODEX_MODEL_PREFERENCES:
            for mid in model_ids:
                if pref in mid.lower():
                    return mid

        # No preference matched — return the first model
        return model_ids[0]
    except Exception as e:
        logger.warning("Failed to discover models from %s: %s", base_url, e)
        return "gpt-4o"


def _setup_codex_workspace(cwd: str) -> None:
    """Seed Codex CLI configuration and FABRIC context into the workspace.

    If a custom provider is flagged with codex_provider=true, writes
    ~/.codex/config.toml pointing Codex to that provider.
    Copies AGENTS.md (shared FABRIC context) so the tool has domain knowledge.
    """
    _write_agents_md(cwd, "codex")
    _write_asset_index(cwd)
    sync_skill_directories(
        _load_tool_skills(),
        os.path.join(cwd, ".codex", "skills"),
        renderer=render_canonical_markdown,
    )
    sync_markdown_files(
        _load_tool_agents(),
        os.path.join(cwd, ".codex", "agents"),
        renderer=render_canonical_markdown,
    )

    # Check if any custom provider is flagged for Codex
    from app.settings_manager import get_custom_providers
    codex_provider = None
    for p in get_custom_providers():
        if p.get("codex_provider") and p.get("base_url"):
            codex_provider = p
            break

    codex_dir = os.path.join(os.path.expanduser("~"), ".codex")
    os.makedirs(codex_dir, exist_ok=True)
    config_path = os.path.join(codex_dir, "config.toml")

    if codex_provider:
        base_url = codex_provider["base_url"].rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        provider_name = codex_provider.get("name") or "Custom"
        api_key = codex_provider.get("api_key", "")

        # Discover the best model from the provider
        model_id = _discover_codex_model(base_url, api_key)

        toml_lines = [
            f'model = "{model_id}"',
            f'model_provider = "{_toml_safe_id(provider_name)}"',
            'model_reasoning_effort = "medium"',
            "",
            f"[model_providers.{_toml_safe_id(provider_name)}]",
            f'name = "{provider_name}"',
            f'base_url = "{base_url}"',
            'wire_api = "responses"',
        ]
        if api_key:
            toml_lines.append(f'experimental_bearer_token = "{api_key}"')

        with open(config_path, "w") as f:
            f.write("\n".join(toml_lines) + "\n")
        logger.info("Wrote Codex config.toml: provider=%s model=%s url=%s",
                     provider_name, model_id, base_url)
    else:
        # No provider flagged — keep existing config.toml. It may be a
        # user-authored file or the generated container default.
        if os.path.isfile(config_path):
            logger.info("Keeping existing Codex config.toml — no provider flagged")

    logger.info("Set up Codex workspace at %s", cwd)


def _start_model_proxy(
    api_key: str, default_model: str, allowed_models: list[str], env: dict,
) -> subprocess.Popen | None:
    """Start the model-rewriting proxy as a background subprocess."""
    if not os.path.exists(_MODEL_PROXY_SCRIPT):
        logger.warning("Model proxy script not found: %s", _MODEL_PROXY_SCRIPT)
        return None

    proxy_port = _model_proxy_port()
    server_url = _ai_server_url()
    allowed_csv = ",".join(allowed_models) if allowed_models else default_model
    cmd = [
        "python3", _MODEL_PROXY_SCRIPT,
        str(proxy_port),
        f"{server_url}/v1",
        default_model,
        allowed_csv,
    ]
    proxy_env = {**env, "OPENAI_API_KEY": api_key}
    try:
        proc = subprocess.Popen(
            cmd, env=proxy_env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,
        )
        logger.info(
            "Model proxy started (pid=%d) on :%d → %s (default=%s, allowed=%s)",
            proc.pid, proxy_port, server_url, default_model, allowed_csv,
        )
        return proc
    except Exception:
        logger.exception("Failed to start model proxy")
        return None

def _codex_env(fabric_key: str) -> dict[str, str]:
    """Build env vars for Codex CLI.

    Auth is handled via experimental_bearer_token in config.toml,
    so no env vars are needed.
    """
    return {}


def _custom_provider_env() -> dict[str, str]:
    try:
        from app.settings_manager import (
            custom_provider_base_url_env_key,
            custom_provider_env_key,
            get_custom_providers,
        )
    except Exception:
        return {}
    env: dict[str, str] = {}
    for provider in get_custom_providers() or []:
        if not isinstance(provider, dict):
            continue
        name = str(provider.get("name") or "custom").strip()
        if not name:
            continue
        base_url = str(provider.get("base_url") or "").strip()
        api_key = str(provider.get("api_key") or "")
        if base_url:
            env[custom_provider_base_url_env_key(name)] = base_url.rstrip("/")
        if api_key:
            api_env = custom_provider_env_key(name)
            env[api_env] = api_key
            if api_env == "LOOMAI_CUSTOM_PROVIDER_AI_RENCI_API_KEY":
                env["AI_RENCI_API_KEY"] = api_key
    return env


# Tool definitions: env setup and command for each AI tool
TOOL_CONFIGS = {
    "antigravity": {
        "env": lambda key: {},
        "cmd": ["agy"],
        "needs_key": False,
    },
    "codex": {
        "env": lambda key: _codex_env(key),
        "cmd": ["codex"],
        "needs_key": False,
    },
    "claude": {
        "env": lambda key: {"NODE_OPTIONS": "--dns-result-order=ipv4first"},
        "cmd": ["claude"],
        "needs_key": False,
    },
    "aider": {
        "env": lambda key: {
            "OPENAI_API_KEY": key,
            "OPENAI_API_BASE": f"http://localhost:{_model_proxy_port()}/v1",
        },
        "cmd": [
            "aider",
            "--architect",
            "--model", "openai/qwen3-coder-30b",
            "--no-auto-lint",
            "--no-auto-test",
            "--no-git-commit-verify",
        ],
        "needs_key": True,
    },
    "opencode": {
        "env": lambda key: {
            "OPENAI_API_KEY": key,
            "FABRIC_AI_API_KEY": key,
            "OPENAI_BASE_URL": f"{_ai_server_url()}/v1",
        },
        "cmd": ["opencode"],
        "needs_key": True,
    },
    "goose": {
        "env": lambda key: {
            "OPENAI_API_KEY": key,
            "FABRIC_AI_API_KEY": key,
            "AI_RENCI_API_KEY": _ai_renci_api_key_or_fabric(key),
            "OPENAI_BASE_URL": f"{_ai_server_url()}/v1",
            "GOOSE_PROVIDER": "openai",
            "GOOSE_MODEL": "qwen3-coder-30b",
        },
        "cmd": ["goose"],
        "needs_key": True,
    },
    "crush": {
        "env": lambda key: {
            "OPENAI_API_KEY": key,
            "OPENAI_BASE_URL": f"{_ai_server_url()}/v1",
        },
        "cmd": ["crush"],
        "needs_key": True,
    },
    "pi": {
        "env": lambda key: {
            "OPENAI_API_KEY": key,
            "FABRIC_AI_API_KEY": key,
            "AI_RENCI_API_KEY": _ai_renci_api_key_or_fabric(key),
            "OPENAI_BASE_URL": f"{_ai_server_url()}/v1",
            "PI_MODE": "text",
        },
        "cmd": ["pi"],
        "needs_key": True,
    },
    "deepagents": {
        "env": lambda key: {
            "OPENAI_API_KEY": key,
            "OPENAI_BASE_URL": f"{_ai_server_url()}/v1",
            "NRP_API_KEY": _get_nrp_api_key() or "",
            "NRP_BASE_URL": f"{_nrp_server_url()}/v1",
        },
        "cmd": ["deepagents"],
        "needs_key": True,
    },
}


_OPENCODE_WEB_PORT = 9198
_opencode_web_proc: subprocess.Popen | None = None
_opencode_web_proxy: subprocess.Popen | None = None


@router.get("/api/ai/tools/status")
async def tool_install_status():
    """Return install status of all lazy-installed AI tools."""
    return get_all_tool_status()


@router.get("/api/ai/tools/disk-space")
async def get_disk_space(tool_id: str = ""):
    """Return disk usage info, optionally checking if a specific tool can be installed."""
    if tool_id:
        return check_disk_space(tool_id)
    # General disk space info
    return check_disk_space("__general__")


@router.post("/api/ai/tools/{tool_id}/install")
async def trigger_tool_install(tool_id: str):
    """Trigger installation of an AI tool. Returns when complete."""
    if tool_id not in TOOL_REGISTRY:
        return {"error": f"Unknown tool: {tool_id}", "status": "error"}
    needs_upgrade = tool_needs_upgrade(tool_id)
    if is_tool_installed(tool_id) and not needs_upgrade:
        if _is_public_managed_harness_tool(tool_id):
            lines: list[str] = []

            async def collect(line: str):
                lines.append(line)

            await install_tool(tool_id, progress_callback=collect)
            return {
                "status": "already_installed",
                "tool": tool_id,
                "output": "".join(lines),
            }
        return {"status": "already_installed", "tool": tool_id}
    lines: list[str] = []
    async def collect(line: str):
        lines.append(line)
    success = await install_tool(tool_id, progress_callback=collect)
    return {
        "status": (
            "upgraded" if needs_upgrade else "installed"
        ) if success else "error",
        "tool": tool_id,
        "output": "".join(lines),
    }


@router.post("/api/ai/tools/{tool_id}/install-stream")
async def trigger_tool_install_stream(tool_id: str):
    """Stream tool installation progress as SSE events."""
    if tool_id not in TOOL_REGISTRY:
        async def _err():
            yield f"data: {json.dumps({'type': 'error', 'message': f'Unknown tool: {tool_id}'})}\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    info = TOOL_REGISTRY[tool_id]

    needs_upgrade = tool_needs_upgrade(tool_id)

    if is_tool_installed(tool_id) and not needs_upgrade:
        if _is_public_managed_harness_tool(tool_id):
            async def _already_configured():
                queue: asyncio.Queue[str | None] = asyncio.Queue()

                async def progress_cb(line: str):
                    await queue.put(line)

                async def run_sync():
                    try:
                        await install_tool(tool_id, progress_callback=progress_cb)
                    finally:
                        await queue.put(None)

                task = asyncio.create_task(run_sync())
                yield f"data: {json.dumps({'type': 'start', 'tool': tool_id, 'display_name': info['display_name'], 'size_estimate': info['size_estimate']})}\n\n"
                while True:
                    line = await queue.get()
                    if line is None:
                        break
                    clean = line.replace("\x1b[36m", "").replace("\x1b[32m", "").replace("\x1b[31m", "").replace("\x1b[33m", "").replace("\x1b[0m", "").rstrip("\r\n")
                    if clean:
                        yield f"data: {json.dumps({'type': 'output', 'message': clean})}\n\n"
                await task
                yield f"data: {json.dumps({'type': 'done', 'status': 'already_installed', 'tool': tool_id})}\n\n"

            return StreamingResponse(_already_configured(), media_type="text/event-stream")

        async def _already():
            yield f"data: {json.dumps({'type': 'done', 'status': 'already_installed', 'tool': tool_id})}\n\n"
        return StreamingResponse(_already(), media_type="text/event-stream")

    async def _stream():
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        # Emit disk space check as the first event
        space = check_disk_space(tool_id)
        yield f"data: {json.dumps({'type': 'disk_check', **space})}\n\n"

        if not space["ok"]:
            yield f"data: {json.dumps({'type': 'error', 'message': space['message']})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'status': 'error', 'tool': tool_id})}\n\n"
            return

        async def progress_cb(line: str):
            await queue.put(line)

        async def run_install():
            try:
                success = await install_tool(tool_id, progress_callback=progress_cb)
                await queue.put(None)  # sentinel
                await queue.put("__SUCCESS__" if success else "__FAIL__")
            except Exception as e:
                await queue.put(f"Error: {e}\r\n")
                await queue.put(None)
                await queue.put("__FAIL__")

        task = asyncio.create_task(run_install())

        # Emit tool info
        yield f"data: {json.dumps({'type': 'start', 'tool': tool_id, 'display_name': info['display_name'], 'size_estimate': info['size_estimate']})}\n\n"

        while True:
            line = await queue.get()
            if line is None:
                break
            # Strip ANSI escape codes for the JSON output
            clean = line.replace("\x1b[36m", "").replace("\x1b[32m", "").replace("\x1b[31m", "").replace("\x1b[0m", "").rstrip("\r\n")
            if clean:
                yield f"data: {json.dumps({'type': 'output', 'message': clean})}\n\n"

        # Get final result
        result = await queue.get()
        await task
        status = (
            "upgraded" if needs_upgrade else "installed"
        ) if result == "__SUCCESS__" else "error"
        yield f"data: {json.dumps({'type': 'done', 'status': status, 'tool': tool_id})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


def _active_tool_reason(tool_id: str) -> str:
    if _term_sessions.has_live_type(f"ai-{tool_id}"):
        return f"{tool_id} has an active terminal session. Close or stop it before uninstalling."
    if tool_id == "claude" and _has_active_process("claude"):
        return "Claude Code is running in another process. Stop it before uninstalling Claude Code."
    if tool_id == "opencode":
        if (_opencode_web_proc and _opencode_web_proc.poll() is None) or (
            _opencode_web_proxy and _opencode_web_proxy.poll() is None
        ):
            return "OpenCode web is running. Stop it before uninstalling OpenCode."
    if tool_id == "aider" and _aider_web_proc and _aider_web_proc.poll() is None:
        return "Aider web is running. Stop it before uninstalling Aider."
    return ""


def _has_active_process(binary: str) -> bool:
    pattern = f"(^|[ /]){binary}($|[[:space:]])"
    try:
        result = subprocess.run(
            ["pgrep", "-af", pattern],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception as exc:
        logger.debug("Could not inspect active %s processes: %s", binary, exc)
        return False

    if result.returncode != 0:
        return False

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        try:
            if int(parts[0]) == os.getpid():
                continue
        except (ValueError, IndexError):
            pass
        command = parts[1] if len(parts) > 1 else ""
        if "pgrep" in command and pattern in command:
            continue
        return True
    return False


@router.post("/api/ai/tools/{tool_id}/uninstall")
async def trigger_tool_uninstall(tool_id: str, remove_config: bool = Query(False)):
    """Uninstall an AI tool. Returns when complete."""
    if tool_id not in TOOL_REGISTRY:
        return {"error": f"Unknown tool: {tool_id}", "status": "error"}
    active_reason = _active_tool_reason(tool_id)
    if active_reason:
        return {"error": active_reason, "status": "running", "tool": tool_id}
    if not is_tool_installed(tool_id):
        cleanup: dict = {}
        if remove_config and _is_public_managed_harness_tool(tool_id):
            from app.harness_config import cleanup_harness_uninstall

            workspace, home = _harness_workspace_home()
            cleanup = cleanup_harness_uninstall(tool_id, remove_config=True, workspace=workspace, home=home)
        return {"status": "not_installed", "tool": tool_id, **cleanup}
    lines: list[str] = []

    async def collect(line: str):
        lines.append(line)

    success = await uninstall_tool(tool_id, progress_callback=collect)
    cleanup = {}
    if success and _is_public_managed_harness_tool(tool_id):
        from app.harness_config import cleanup_harness_uninstall

        workspace, home = _harness_workspace_home()
        cleanup = cleanup_harness_uninstall(tool_id, remove_config=remove_config, workspace=workspace, home=home)
    return {
        "status": "uninstalled" if success else "error",
        "tool": tool_id,
        "output": "".join(lines),
        **cleanup,
    }


@router.post("/api/ai/opencode-web/start")
async def start_opencode_web(model: str = ""):
    """Start the OpenCode web server and return its port."""
    global _opencode_web_proc, _opencode_web_proxy

    # Already running?
    if _opencode_web_proc and _opencode_web_proc.poll() is None:
        return {"port": _OPENCODE_WEB_PORT, "status": "running"}

    api_key = _get_ai_api_key()
    if not api_key:
        return {"error": "AI API key not configured", "status": "error"}

    if not is_tool_installed("opencode"):
        return {"install_required": True, "tool": "opencode", "status": "not_installed"}

    from app.settings_manager import get_storage_dir as _storage
    cwd = _storage() if os.path.isdir(_storage()) else os.path.expanduser("~")
    _ensure_git_ready(cwd)

    # Set up workspace (skills, agents, MCP, AGENTS.md) and build config
    ws_config = _setup_opencode_workspace(cwd)
    oc_config = _build_opencode_config(
        api_key, model_override=model, workspace_config=ws_config,
    )
    write_cfg = {k: v for k, v in oc_config.items() if not k.startswith("_")}
    with open(os.path.join(cwd, "opencode.json"), "w") as f:
        json.dump(write_cfg, f, indent=2)
    logger.info("Wrote opencode.json for web mode, model=%s", write_cfg.get("model"))

    tool_env = {
        **os.environ,
        "TERM": "xterm-256color",
        "OPENAI_API_KEY": api_key,
        "FABRIC_AI_API_KEY": api_key,
        "AI_RENCI_API_KEY": _ai_renci_api_key_or_fabric(api_key),
        "OPENAI_BASE_URL": f"{_ai_server_url()}/v1",
    }
    nrp_key = _get_nrp_api_key()
    if nrp_key:
        tool_env["NRP_API_KEY"] = nrp_key
    tool_env.update(_custom_provider_env())

    # Start model proxy
    _opencode_web_proxy = _start_model_proxy(
        api_key, oc_config["_default"], oc_config["_allowed"], tool_env,
    )
    if _opencode_web_proxy:
        await asyncio.sleep(0.3)
        tool_env["OPENAI_BASE_URL"] = f"http://127.0.0.1:{_model_proxy_port()}/v1"

    cmd = [
        "opencode", "web",
        "--port", str(_OPENCODE_WEB_PORT),
        "--hostname", "0.0.0.0",
    ]
    installed_path = get_tool_binary_path("opencode")
    if installed_path:
        cmd[0] = installed_path
    tool_env.update({k: v for k, v in get_tool_env().items() if k == "PATH"})
    try:
        _opencode_web_proc = subprocess.Popen(
            cmd, cwd=cwd, env=tool_env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,
        )
        logger.info("OpenCode web started pid=%d on :%d", _opencode_web_proc.pid, _OPENCODE_WEB_PORT)
    except Exception:
        logger.exception("Failed to start opencode web")
        return {"error": "Failed to start OpenCode web server", "status": "error"}

    # Wait for it to bind
    await asyncio.sleep(2)

    return {"port": _OPENCODE_WEB_PORT, "status": "running"}


@router.post("/api/ai/opencode-web/stop")
async def stop_opencode_web():
    """Stop the OpenCode web server."""
    global _opencode_web_proc, _opencode_web_proxy
    for p in (_opencode_web_proc, _opencode_web_proxy):
        if p and p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                p.wait(timeout=3)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
    _opencode_web_proc = None
    _opencode_web_proxy = None
    return {"status": "stopped"}


@router.get("/api/ai/opencode-web/status")
async def opencode_web_status():
    """Check if the OpenCode web server is running."""
    running = _opencode_web_proc is not None and _opencode_web_proc.poll() is None
    return {"port": _OPENCODE_WEB_PORT if running else None, "status": "running" if running else "stopped"}


_AIDER_WEB_PORT = 9197
_aider_web_proc: subprocess.Popen | None = None


@router.post("/api/ai/aider-web/start")
async def start_aider_web(model: str = ""):
    """Start the Aider browser GUI (Streamlit) and return its port."""
    global _aider_web_proc

    # Already running?
    if _aider_web_proc and _aider_web_proc.poll() is None:
        return {"port": _AIDER_WEB_PORT, "status": "running"}

    api_key = _get_ai_api_key()
    if not api_key:
        return {"error": "AI API key not configured", "status": "error"}

    if not is_tool_installed("aider"):
        return {"install_required": True, "tool": "aider", "status": "not_installed"}

    from app.settings_manager import get_storage_dir as _storage
    cwd = _storage() if os.path.isdir(_storage()) else os.path.expanduser("~")
    _ensure_git_ready(cwd)
    _setup_aider_workspace(cwd)

    if not model:
        models = _fetch_models(api_key)
        model = _pick_model(models, _PREFERRED_MODELS, "qwen3-coder-30b")

    tool_env = {
        **os.environ,
        "OPENAI_API_KEY": api_key,
        "OPENAI_API_BASE": f"{_ai_server_url()}/v1",
    }

    cmd = [
        "aider", "--gui",
        "--model", f"openai/{model}",
        "--no-auto-lint",
        "--no-auto-test",
        "--no-git-commit-verify",
    ]
    installed_path = get_tool_binary_path("aider")
    if installed_path:
        cmd[0] = installed_path
    tool_env.update({k: v for k, v in get_tool_env().items() if k == "PATH"})
    # Streamlit needs server config via env or CLI args
    tool_env["STREAMLIT_SERVER_PORT"] = str(_AIDER_WEB_PORT)
    tool_env["STREAMLIT_SERVER_ADDRESS"] = "0.0.0.0"
    tool_env["STREAMLIT_SERVER_HEADLESS"] = "true"
    tool_env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    try:
        _aider_web_proc = subprocess.Popen(
            cmd, cwd=cwd, env=tool_env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,
        )
        logger.info("Aider GUI started pid=%d on :%d model=%s", _aider_web_proc.pid, _AIDER_WEB_PORT, model)
    except Exception:
        logger.exception("Failed to start aider GUI")
        return {"error": "Failed to start Aider GUI", "status": "error"}

    # Streamlit takes a moment to start
    await asyncio.sleep(3)

    return {"port": _AIDER_WEB_PORT, "status": "running"}


@router.post("/api/ai/aider-web/stop")
async def stop_aider_web():
    """Stop the Aider GUI server."""
    global _aider_web_proc
    if _aider_web_proc and _aider_web_proc.poll() is None:
        try:
            os.killpg(os.getpgid(_aider_web_proc.pid), signal.SIGTERM)
            _aider_web_proc.wait(timeout=3)
        except Exception:
            try:
                _aider_web_proc.kill()
            except Exception:
                pass
    _aider_web_proc = None
    return {"status": "stopped"}


@router.get("/api/ai/aider-web/status")
async def aider_web_status():
    """Check if the Aider GUI server is running."""
    running = _aider_web_proc is not None and _aider_web_proc.poll() is None
    return {"port": _AIDER_WEB_PORT if running else None, "status": "running" if running else "stopped"}


def _persist_model_list(models_data: dict) -> dict:
    """Save discovered models to settings.json, return diff summary.

    Compares the new model list against the previously persisted
    ``ai.discovered_models`` in settings and returns counts of added,
    removed, and updated (context_length changed) models.
    """
    from app.settings_manager import load_settings, save_settings

    settings = load_settings()
    old_discovered = settings.get("ai", {}).get("discovered_models", {})

    # Build lookup of old models keyed by (provider, model_id)
    old_lookup: dict[tuple[str, str], dict] = {}
    for provider in ("fabric", "nrp"):
        for m in old_discovered.get(provider, []):
            old_lookup[(provider, m["id"])] = m
    for cp_name, cp_models in old_discovered.get("custom", {}).items():
        for m in cp_models:
            old_lookup[(f"custom:{cp_name}", m["id"])] = m

    # Build lookup of new models
    new_lookup: dict[tuple[str, str], dict] = {}
    for provider in ("fabric", "nrp"):
        for m in models_data.get(provider, []):
            new_lookup[(provider, m["id"])] = m
    for cp_name, cp_models in models_data.get("custom", {}).items():
        for m in cp_models:
            new_lookup[(f"custom:{cp_name}", m["id"])] = m

    added = len(set(new_lookup.keys()) - set(old_lookup.keys()))
    removed = len(set(old_lookup.keys()) - set(new_lookup.keys()))
    updated = 0
    for key in set(new_lookup.keys()) & set(old_lookup.keys()):
        if any(
            new_lookup[key].get(field) != old_lookup[key].get(field)
            for field in (
                "context_length",
                "model_type",
                "endpoint_style",
                "healthy",
                "supports_tools",
            )
        ):
            updated += 1

    # Persist the new model list
    new_discovered = {
        "fabric": models_data.get("fabric", []),
        "nrp": models_data.get("nrp", []),
        "custom": models_data.get("custom", {}),
    }
    settings.setdefault("ai", {})["discovered_models"] = new_discovered
    save_settings(settings)

    return {"added": added, "removed": removed, "updated": updated}


def _fetch_all_models() -> dict:
    """Fetch models from both providers (sync, for call manager caching)."""
    if _contract_mode():
        return _contract_model_data()

    api_key = _get_ai_api_key()
    nrp_key = _get_nrp_api_key()

    # Try FABRIC models — prefer /v1/model/info (includes context sizes),
    # fall back to /v1/models with _FABRIC_CONTEXT_DEFAULTS
    fabric_models_raw: list[dict] = []
    fabric_error = ""
    try:
        key = api_key or "anonymous"
        # Try the rich /v1/model/info endpoint first
        fabric_models_raw = _fetch_fabric_model_info(key)
        if not fabric_models_raw:
            # Fall back to /v1/models and apply default context sizes
            fabric_models_raw = _fetch_models(key)
            for m in fabric_models_raw:
                if not m.get("context_length"):
                    m["context_length"] = _FABRIC_CONTEXT_DEFAULTS.get(m["id"])
    except Exception as e:
        fabric_error = str(e)

    # Try NRP models
    nrp_models_raw: list[dict] = []
    nrp_error = ""
    try:
        if nrp_key:
            nrp_models_raw = _fetch_nrp_models(nrp_key)
        else:
            nrp_models_raw = _fetch_nrp_models("anonymous")
    except Exception as e:
        nrp_error = str(e)

    # Filter out NRP embedding/excluded models and apply context defaults
    nrp_models_raw = [m for m in nrp_models_raw if m["id"] not in _NRP_EXCLUDE]
    for m in nrp_models_raw:
        if not m.get("context_length"):
            m["context_length"] = _NRP_CONTEXT_DEFAULTS.get(m["id"])

    # Extract IDs for backward compat
    fabric_model_ids = [m["id"] for m in fabric_models_raw]
    nrp_model_ids = [m["id"] for m in nrp_models_raw]

    # Health-check models: FABRIC first (preferred order), then NRP.
    fabric_server = _ai_server_url()
    fabric_key = api_key or "anonymous"
    default = ""

    # Sort FABRIC models so preferred ones are checked first
    preferred_order = []
    rest = []
    ctx_map: dict[str, int | None] = {}  # model_id → context_length
    for m in fabric_models_raw:
        mid = m["id"]
        ctx_map[mid] = m.get("context_length")
        if any(p in mid.lower() for p in [p.lower() for p in _PREFERRED_MODELS]):
            preferred_order.append(mid)
        else:
            rest.append(mid)
    ordered_fabric = preferred_order + rest

    from app.chat_context import get_model_profile

    fabric_entries = []
    for mid in ordered_fabric:
        healthy, model_type = _check_model_health(fabric_server, fabric_key, mid)
        ctx_val = ctx_map.get(mid) or _FABRIC_CONTEXT_DEFAULTS.get(mid) or 131072
        profile = get_model_profile(mid, context_length=ctx_val)
        fabric_entries.append({
            "id": mid, "name": mid, "healthy": healthy,
            "model_type": model_type,
            "context_length": ctx_val,
            "tier": profile["tier"],
            "supports_tools": profile.get("supports_tools", True),
        })
        if healthy and not default:
            default = mid
        logger.info("Model health: FABRIC/%s (ctx=%s) → %s%s", mid,
                     ctx_val,
                     "ok" if healthy else "FAILED",
                     " (default)" if mid == default else "")

    # Then check NRP models
    nrp_server = _nrp_server_url()
    nrp_entries = []
    for m in nrp_models_raw:
        mid = m["id"]
        ctx = m.get("context_length") or _NRP_CONTEXT_DEFAULTS.get(mid) or 131072
        healthy, model_type = _check_model_health(nrp_server, nrp_key or "anonymous", mid)
        profile = get_model_profile(mid, context_length=ctx)
        nrp_entries.append({
            "id": mid, "name": mid, "healthy": healthy,
            "model_type": model_type,
            "context_length": ctx,
            "tier": profile["tier"],
            "supports_tools": profile.get("supports_tools", True),
        })
        if healthy and not default:
            default = mid
        logger.info("Model health: NRP/%s (ctx=%s) → %s", mid, ctx, "ok" if healthy else "FAILED")

    # Check custom providers
    from app.settings_manager import _get_settings
    custom_providers_config = _get_settings().get("ai", {}).get("custom_providers", [])
    custom_entries: dict[str, list[dict]] = {}
    for cp in custom_providers_config:
        cp_name = cp.get("name", "custom")
        cp_url = cp.get("base_url", "")
        cp_key = cp.get("api_key", "")
        cp_endpoint_style = normalize_ai_endpoint_style(cp.get("endpoint_style"))
        if not cp_url:
            continue
        try:
            cp_base_url = cp_url.rstrip("/")
            url = f"{cp_base_url}/v1/models"
            req = urllib.request.Request(url, headers=add_tracking_headers({"Authorization": f"Bearer {cp_key}"}))
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
            cp_models = []
            for m in body.get("data", []):
                mid = m["id"]
                healthy, model_type = _check_model_health_with_endpoint_style(
                    cp_base_url,
                    cp_key,
                    mid,
                    cp_endpoint_style,
                )
                ctx = m.get("context_length") or m.get("context_window")
                profile = get_model_profile(mid, context_length=ctx)
                effective_endpoint = cp_endpoint_style if cp_endpoint_style != "auto" else model_type
                cp_models.append({
                    "id": mid,
                    "name": mid,
                    "healthy": healthy,
                    "model_type": model_type,
                    "endpoint_style": effective_endpoint,
                    "context_length": ctx,
                    "tier": profile["tier"],
                    "supports_tools": (
                        model_type != "non-chat"
                        and profile.get("supports_tools", True)
                    ),
                })
                if healthy and model_type in {"chat", "responses"} and not default:
                    default = f"{cp_name}:{mid}"
            custom_entries[cp_name] = cp_models
        except Exception as e:
            logger.warning("Custom provider '%s' failed: %s", cp_name, e)
            custom_entries[cp_name] = []

    # Set default_model only if none is configured yet (don't overwrite user choice)
    if default:
        from app import settings_manager
        current = settings_manager.get_default_model()
        if not current:
            source = "fabric"
            if any(m["id"] == default for m in nrp_entries):
                source = "nrp"
            for cp_name, cp_models in custom_entries.items():
                if any(m["id"] == default.replace(f"{cp_name}:", "") for m in cp_models):
                    source = f"custom:{cp_name}"
                    break
            settings_manager.set_default_model(default, source)
            logger.info("Set initial default_model: %s (%s)", default, source)

    return {
        "fabric": fabric_entries,
        "nrp": nrp_entries,
        "custom": custom_entries,
        "default": default,
        "has_key": {"fabric": bool(api_key), "nrp": bool(nrp_key)},
        "errors": {
            "fabric": fabric_error if not fabric_model_ids else "",
            "nrp": nrp_error if not nrp_model_ids else "",
        },
        # Backward compat
        "models": fabric_model_ids,
        "nrp_models": nrp_model_ids,
    }


def _find_first_healthy_model() -> dict:
    """Quickly find the first healthy model (checks preferred models only).

    Much faster than _fetch_all_models — stops after finding one healthy model.
    Used for immediate default model selection.
    """
    if _contract_mode():
        return {"default": "fabric/contract-model", "source": "fabric"}

    api_key = _get_ai_api_key()
    if not api_key:
        return {"default": "", "source": ""}

    server_url = _ai_server_url()
    model_ids = _model_ids(_fetch_models(api_key))

    # Check preferred models first
    for pref in _PREFERRED_MODELS:
        for m in model_ids:
            if pref in m.lower():
                ok, mtype = _check_model_health(server_url, api_key, m)
                if ok and mtype == "chat":
                    return {"default": m, "source": "fabric"}
                break  # This preferred model failed, try next preference

    # Check remaining FABRIC models
    for m in model_ids:
        ok, mtype = _check_model_health(server_url, api_key, m)
        if ok and mtype == "chat":
            return {"default": m, "source": "fabric"}

    # Try NRP
    nrp_key = _get_nrp_api_key()
    if nrp_key:
        nrp_ids = _model_ids(_fetch_nrp_models(nrp_key))
        for m in nrp_ids:
            ok, mtype = _check_model_health(_nrp_server_url(), nrp_key, m)
            if ok and mtype == "chat":
                return {"default": m, "source": "nrp"}

    return {"default": "", "source": ""}


def _persist_discovered_context_lengths() -> None:
    """Fetch per-provider model context lengths and persist to settings.ai.discovered_models.

    Runs at startup (best-effort). The chat handler reads this to size its
    context budget. Without this, models get the 32K default which triggers
    "context window nearly full" warnings very quickly for 256K-context models.
    """
    from app import settings_manager

    api_key = _get_ai_api_key()
    nrp_key = _get_nrp_api_key()
    fabric_list: list[dict] = []
    nrp_list: list[dict] = []

    # FABRIC AI: prefer /v1/model/info (rich metadata), fall back to /v1/models + defaults
    if api_key:
        try:
            rich = _fetch_fabric_model_info(api_key)
            if rich:
                fabric_list = [
                    {"id": m["id"], "context_length": m.get("context_length") or _FABRIC_CONTEXT_DEFAULTS.get(m["id"])}
                    for m in rich
                ]
            else:
                basic = _fetch_models(api_key)
                fabric_list = [
                    {"id": m["id"], "context_length": m.get("context_length") or _FABRIC_CONTEXT_DEFAULTS.get(m["id"])}
                    for m in basic
                ]
        except Exception as e:
            logger.warning("FABRIC model-info discovery failed: %s", e)

    # NRP: /v1/models doesn't advertise context, so apply NRP defaults
    if nrp_key:
        try:
            basic = _fetch_nrp_models(nrp_key)
            for m in basic:
                if m["id"] in _NRP_EXCLUDE:
                    continue
                nrp_list.append({
                    "id": m["id"],
                    "context_length": m.get("context_length") or _NRP_CONTEXT_DEFAULTS.get(m["id"]) or 131072,
                })
        except Exception as e:
            logger.warning("NRP model discovery failed: %s", e)

    if not (fabric_list or nrp_list):
        return

    try:
        settings = settings_manager.load_settings()

        # Preserve model_type from previous full discovery (health checks).
        # This lightweight startup path doesn't run health checks, so carry
        # forward any model_type values that were set by _fetch_all_models.
        old_discovered = settings.get("ai", {}).get("discovered_models", {})
        _old_types: dict[str, str] = {}  # model_id → model_type
        for _prov_key in ("fabric", "nrp"):
            for _om in old_discovered.get(_prov_key, []):
                if isinstance(_om, dict) and _om.get("model_type"):
                    _old_types[_om["id"]] = _om["model_type"]
        # Also check custom providers
        _old_custom = old_discovered.get("custom", {})
        if isinstance(_old_custom, dict):
            for _cp_models in _old_custom.values():
                if isinstance(_cp_models, list):
                    for _om in _cp_models:
                        if isinstance(_om, dict) and _om.get("model_type"):
                            _old_types[_om["id"]] = _om["model_type"]

        # Merge preserved model_type into the new lists
        for _entry in fabric_list + nrp_list:
            _mt = _old_types.get(_entry["id"])
            if _mt:
                _entry["model_type"] = _mt

        new_discovered: dict = {
            "fabric": fabric_list,
            "nrp": nrp_list,
        }
        # Preserve custom provider entries (this path doesn't re-fetch them)
        if _old_custom:
            new_discovered["custom"] = _old_custom

        settings.setdefault("ai", {})["discovered_models"] = new_discovered
        settings_manager.save_settings(settings)
        logger.info(
            "Persisted discovered_models: fabric=%d nrp=%d (sample: %s)",
            len(fabric_list), len(nrp_list),
            ", ".join(f"{m['id']}={m['context_length']}" for m in (fabric_list + nrp_list)[:3]),
        )
    except Exception as e:
        logger.warning("Failed to persist discovered_models: %s", e)


def discover_and_persist_default_model() -> dict:
    """Discover the first healthy model and persist it to settings.json.

    Called at startup. Only discovers a new model if no default is set.
    Never overwrites a user-chosen model — even if it's temporarily unhealthy.
    Also persists per-provider context lengths so the chat handler can
    correctly size its context budget.
    """
    from app import settings_manager

    # Always refresh discovered_models on startup — the chat handler relies on
    # the context_length values to size its budget correctly.
    _persist_discovered_context_lengths()

    current_model = settings_manager.get_default_model()
    current_source = settings_manager.get_default_model_source()

    if current_model:
        # User has a chosen model — respect it, don't overwrite
        logger.info("Default model already set: %s (%s) — keeping user choice",
                    current_model, current_source)
        return {"default": current_model, "source": current_source}

    # No default set — discover the first healthy model
    result = _find_first_healthy_model()

    if result["default"]:
        settings_manager.set_default_model(result["default"], result["source"])
        logger.info("Set initial default model to %s (source: %s)",
                    result["default"], result["source"])
    else:
        logger.warning("No healthy models found — default_model remains empty")

    return result


def _model_provider_and_bare_id(model_id: str, source: str = "") -> tuple[str, str, str]:
    """Return (provider, provider_name, bare_model_id) for a UI model id."""
    raw = str(model_id or "").strip()
    source = str(source or "").strip()
    if source.startswith("custom:"):
        provider_name = source.split(":", 1)[1]
        bare = raw.split(":", 1)[1] if ":" in raw else raw
        return "custom", provider_name, bare
    if source == "nrp" or raw.startswith("nrp:"):
        return "nrp", "nrp", raw[4:] if raw.startswith("nrp:") else raw
    if source == "fabric":
        return "fabric", "fabric", raw[7:] if raw.startswith("fabric:") else raw
    if ":" in raw:
        prefix, _, bare = raw.partition(":")
        if prefix == "nrp":
            return "nrp", "nrp", bare
        if prefix == "fabric":
            return "fabric", "fabric", bare
        return "custom", prefix, bare
    return "fabric", "fabric", raw


def _custom_provider_endpoint_style(provider_name: str) -> str:
    """Return configured endpoint style for a custom provider."""
    from app.settings_manager import get_custom_providers

    for provider in get_custom_providers():
        if isinstance(provider, dict) and provider.get("name") == provider_name:
            return normalize_ai_endpoint_style(provider.get("endpoint_style"))
    return "auto"


def _lookup_discovered_model(model_id: str, source: str = "") -> tuple[str, str, dict | None]:
    """Look up a model in persisted discovered_models."""
    from app.settings_manager import load_settings

    provider, provider_name, bare = _model_provider_and_bare_id(model_id, source)
    discovered = load_settings().get("ai", {}).get("discovered_models", {})
    if provider in {"fabric", "nrp"}:
        for entry in discovered.get(provider, []) or []:
            if isinstance(entry, dict) and entry.get("id") == bare:
                return provider, bare, entry
        return provider, bare, None
    custom = discovered.get("custom", {})
    if isinstance(custom, dict):
        for entry in custom.get(provider_name, []) or []:
            if isinstance(entry, dict) and entry.get("id") == bare:
                return f"custom:{provider_name}", bare, entry
    return f"custom:{provider_name}", bare, None


def _model_capabilities_payload(model_id: str, source: str = "") -> dict:
    """Build a stable capability payload for frontend warnings."""
    provider, bare, entry = _lookup_discovered_model(model_id, source)
    provider_kind, provider_name, _ = _model_provider_and_bare_id(model_id, source)
    profile_key = (
        f"{provider_name}:{bare}"
        if provider_kind == "custom"
        else f"{provider}:{bare}"
        if provider in {"fabric", "nrp"}
        else model_id
    )
    from app.settings_manager import get_model_capability_profile
    capability_profile = get_model_capability_profile(profile_key)
    configured_style = (
        _custom_provider_endpoint_style(provider_name)
        if provider_kind == "custom"
        else "auto"
    )
    found = isinstance(entry, dict)
    context_length = (
        capability_profile.get("context_window_tokens")
        or (entry or {}).get("context_length")
    )
    from app.chat_context import get_model_profile

    profile = get_model_profile(bare, context_length=context_length)
    model_type = str((entry or {}).get("model_type") or "").strip()
    endpoint_style = normalize_ai_endpoint_style(
        capability_profile.get("endpoint_style")
        or (entry or {}).get("endpoint_style")
        or (configured_style if configured_style != "auto" else model_type)
        or "auto"
    )
    if not model_type:
        model_type = endpoint_style if endpoint_style != "auto" else "chat"
    healthy = (entry or {}).get("healthy")
    supports_tools = (entry or {}).get("supports_tools")
    if "supports_tools" in capability_profile:
        supports_tools = capability_profile["supports_tools"]
    if supports_tools is None:
        supports_tools = model_type != "non-chat" and profile.get("supports_tools", True)

    warnings: list[str] = []
    if not found:
        warnings.append("Model metadata has not been refreshed yet.")
    if healthy is False:
        warnings.append("Model health check is currently failing.")
    if model_type == "non-chat":
        warnings.append("This model is listed by the provider but does not support chat.")
    elif supports_tools is False:
        warnings.append("Tool calling is not available for this model.")
    if provider_kind == "custom" and endpoint_style == "auto":
        warnings.append("Custom provider endpoint style is auto-detected; set it explicitly if calls fail.")

    return {
        "model": model_id,
        "id": bare,
        "provider": provider,
        "found": found,
        "healthy": healthy if healthy is not None else None,
        "model_type": model_type,
        "endpoint_style": endpoint_style,
        "context_length": context_length or profile.get("context_window"),
        "tier": (entry or {}).get("tier") or profile.get("tier"),
        "supports_tools": bool(supports_tools),
        "capability_profile": capability_profile or None,
        "warnings": warnings,
    }


@router.get("/api/ai/models/{model_id:path}/capabilities")
async def get_ai_model_capabilities(model_id: str, source: str = ""):
    """Return capability metadata and warnings for one assistant model."""
    if not model_id:
        return JSONResponse({"error": "model id is required"}, status_code=400)
    return _model_capabilities_payload(model_id, source)


@router.get("/api/models/{model_id:path}/capabilities")
async def get_model_capabilities_alias(model_id: str, source: str = ""):
    """Compatibility alias for model capability metadata."""
    if not model_id:
        return JSONResponse({"error": "model id is required"}, status_code=400)
    return _model_capabilities_payload(model_id, source)


@router.get("/api/ai/models/default")
async def get_default_model():
    """Return the default model. Fast path reads from settings; slow path discovers.

    Use this for immediate model selection. Call GET /api/ai/models for the
    full list with health status (slower, cached for 10 min).
    """
    from app import settings_manager

    # Fast path: return persisted default if set
    persisted = settings_manager.get_default_model()
    if persisted:
        return {
            "default": persisted,
            "source": settings_manager.get_default_model_source(),
        }

    # Slow path: discover and cache
    from app.fabric_call_manager import get_call_manager
    mgr = get_call_manager()
    result = await mgr.get(
        "ai:models:default",
        fetcher=_find_first_healthy_model,
        max_age=600,
        stale_while_revalidate=True,
    )

    # Persist for future fast-path returns
    if result.get("default"):
        settings_manager.set_default_model(result["default"], result.get("source", ""))

    return result


@router.put("/api/ai/models/default")
async def set_default_model_endpoint(request: Request):
    """Set the default model in shared settings.

    Body: {"model": "model-id", "source": "fabric"|"nrp"|"custom:name"}
    Both assistant panel and CLI call this to sync their model selection.
    """
    from app import settings_manager

    body = await request.json()
    model = body.get("model", "")
    source = body.get("source", "")

    if not model:
        return JSONResponse({"error": "model is required"}, status_code=400)

    # Auto-detect source if not provided
    if not source:
        if model.startswith("nrp:"):
            source = "nrp"
            model = model[4:]  # strip prefix for storage
        else:
            source = "fabric"

    settings_manager.set_default_model(model, source)
    logger.info("User set default model to %s (source: %s)", model, source)
    return {"default": model, "source": source}


@router.post("/api/ai/models/test")
async def test_model_health(request: Request):
    """Test a specific model's health with latency details.

    Body: {"model": "model-id", "source": "fabric"|"nrp"}
    Returns: {"healthy": bool, "latency_ms": int, "error": str}
    """
    import time

    body = await request.json()
    model_id = body.get("model", "")
    source = body.get("source", "fabric")

    if not model_id:
        return JSONResponse({"error": "model is required"}, status_code=400)

    if source == "nrp":
        server_url = _nrp_server_url()
        api_key = _get_nrp_api_key()
    else:
        server_url = _ai_server_url()
        api_key = _get_ai_api_key()

    if not api_key:
        return {"healthy": False, "latency_ms": 0, "error": "API key not configured",
                "model": model_id, "source": source}

    start = time.time()
    try:
        data = json.dumps({
            "model": model_id,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }).encode()
        req = urllib.request.Request(
            f"{server_url}/v1/chat/completions",
            data=data,
            headers=add_tracking_headers({
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }),
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            latency = int((time.time() - start) * 1000)
            return {"healthy": resp.status == 200, "latency_ms": latency,
                    "error": "", "model": model_id, "source": source}
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        return {"healthy": False, "latency_ms": latency,
                "error": str(e), "model": model_id, "source": source}


@router.post("/api/ai/models/refresh")
async def refresh_model_health():
    """Force-refresh all model health checks (ignores cache).

    Persists the discovered model list to settings and returns a diff
    summary showing how many models were added, removed, or updated.
    """
    from app.fabric_call_manager import get_call_manager
    mgr = get_call_manager()
    mgr.invalidate("ai:models")
    result = await mgr.get(
        "ai:models",
        fetcher=_fetch_all_models,
        max_age=0,
    )
    # Persist and compute diff
    diff = _persist_model_list(result)
    parts = []
    if diff["added"]:
        parts.append(f"{diff['added']} added")
    if diff["removed"]:
        parts.append(f"{diff['removed']} removed")
    if diff["updated"]:
        parts.append(f"{diff['updated']} updated")
    message = f"Updated models: {', '.join(parts)}" if parts else "No changes"
    result["added"] = diff["added"]
    result["removed"] = diff["removed"]
    result["updated"] = diff["updated"]
    result["message"] = message
    return result


@router.get("/api/ai/models")
async def list_ai_models():
    """Return available models from FABRIC AI and NRP servers, grouped by source.

    Always returns the model list even without API keys — users can browse
    what's available.  Uses the call manager for caching (10-minute TTL).
    Health checks run on each model (can take 30+ seconds on first call).
    """
    from app.fabric_call_manager import get_call_manager
    mgr = get_call_manager()
    return await mgr.get(
        "ai:models",
        fetcher=_fetch_all_models,
        max_age=600,  # 10-minute cache
        stale_while_revalidate=True,
    )


@router.get("/api/ai/browse-folders")
async def browse_folders(path: str = ""):
    """Return subdirectories of the given path for folder picking.

    If *path* is empty, returns children of the storage root directory.
    Only allows browsing within the storage root.
    """
    from app.settings_manager import get_storage_dir as _storage
    root = _storage()

    if not path:
        path = root

    # Security: ensure path is within root
    real_path = os.path.realpath(path)
    real_root = os.path.realpath(root)
    if not real_path.startswith(real_root):
        return {"error": "Access denied", "path": root, "folders": []}

    if not os.path.isdir(real_path):
        return {"error": "Not a directory", "path": root, "folders": []}

    folders = []
    try:
        for entry in sorted(os.listdir(real_path)):
            if entry.startswith("."):
                continue
            full = os.path.join(real_path, entry)
            if os.path.isdir(full):
                folders.append(entry)
    except PermissionError:
        return {"error": "Permission denied", "path": real_path, "folders": []}

    return {"path": real_path, "parent": os.path.dirname(real_path) if real_path != real_root else None, "folders": folders}


# ---------------------------------------------------------------------------
# Shared AI-tool launch preparation (used by both the persistent tmux-backed
# create route and the legacy spawn-on-connect WebSocket).
# ---------------------------------------------------------------------------

_terminal_model_proxy: subprocess.Popen | None = None


def _ensure_model_proxy(api_key: str, default_model: str, allowed_models: list[str]) -> bool:
    """Start the model-rewriting proxy once (singleton on the fixed port).

    Persists across terminal reconnects and is reused if already running, so a
    tmux-backed AI session keeps working after a browser reload.
    """
    global _terminal_model_proxy  # noqa: PLW0603
    if _terminal_model_proxy is not None and _terminal_model_proxy.poll() is None:
        return True
    proc = _start_model_proxy(api_key, default_model, allowed_models, {**os.environ})
    if proc:
        _terminal_model_proxy = proc
        time.sleep(0.3)  # let it bind
        return True
    return False


async def build_ai_tool_launch(tool: str, model: str = "", cwd: str = "", progress_cb=None):
    """Prepare an AI tool for launch; returns ``(argv, env_delta, cwd)``.

    ``env_delta`` holds only the tool-specific variables to layer on top of the
    inherited environment. For tmux-backed sessions it is injected via a
    self-deleting launcher so secrets never reach the process argv. Performs
    workspace setup, opencode config + model proxy, and lazy install (streamed
    through ``progress_cb`` when provided). Raises ``ValueError`` (unknown
    tool), ``PermissionError`` (missing key), or ``RuntimeError`` (install
    failed).
    """
    if tool not in TOOL_CONFIGS:
        raise ValueError(f"Unknown tool: {tool}")
    config = TOOL_CONFIGS[tool]
    fabric_api_key = _get_ai_api_key()
    api_key = fabric_api_key if config["needs_key"] else ""
    if config["needs_key"] and not api_key:
        raise PermissionError("AI API key not configured")

    env: dict[str, str] = {"TERM": "xterm-256color"}
    env.update(config["env"](api_key))
    if fabric_api_key:
        env.setdefault("OPENAI_API_KEY", fabric_api_key)
        env["FABRIC_AI_API_KEY"] = fabric_api_key
        env["AI_RENCI_API_KEY"] = _ai_renci_api_key_or_fabric(fabric_api_key)
    env.update(_custom_provider_env())

    from app.settings_manager import get_storage_dir as _storage
    default_cwd = _storage() if os.path.isdir(_storage()) else os.path.expanduser("~")
    if cwd and os.path.isdir(cwd):
        real_cwd = os.path.realpath(cwd)
        real_root = os.path.realpath(default_cwd)
        cwd = real_cwd if real_cwd.startswith(real_root) else default_cwd
    else:
        cwd = default_cwd

    nrp_key = _get_nrp_api_key()
    if nrp_key:
        env["NRP_API_KEY"] = nrp_key

    if _is_public_managed_harness_tool(tool):
        try:
            from app.harness_config import sync_harness_defaults
            sync_harness_defaults(workspace=default_cwd, home=os.path.expanduser("~"), harnesses=[tool])
        except Exception as e:
            logger.warning("Could not sync %s harness defaults: %s", tool, e)

    # Tool-specific workspace setup
    if tool == "antigravity":
        _setup_antigravity_workspace(cwd)
    elif tool == "codex":
        _setup_codex_workspace(cwd)
    elif tool == "aider":
        _ensure_git_ready(cwd)
        _setup_aider_workspace(cwd)
    elif tool == "claude":
        _setup_claude_workspace(cwd)
    elif tool == "crush":
        _ensure_git_ready(cwd)
        _setup_crush_workspace(cwd, api_key, model_override=model)
    elif tool == "goose":
        _ensure_git_ready(cwd)
    elif tool == "pi":
        pass
    elif tool == "deepagents":
        _ensure_git_ready(cwd)
        _setup_deepagents_workspace(cwd, api_key, model_override=model)

    # opencode: dynamic config + model proxy
    if tool == "opencode":
        _ensure_git_ready(cwd)
        try:
            ws_config = _setup_opencode_workspace(cwd)
            oc_config = _build_opencode_config(api_key, model_override=model, workspace_config=ws_config)
            write_cfg = {k: v for k, v in oc_config.items() if not k.startswith("_")}
            with open(os.path.join(cwd, "opencode.json"), "w") as f:
                json.dump(write_cfg, f, indent=2)
            logger.info("Wrote opencode.json with model=%s", write_cfg.get("model"))
            if _ensure_model_proxy(api_key, oc_config["_default"], oc_config["_allowed"]):
                env["OPENAI_BASE_URL"] = f"http://127.0.0.1:{_model_proxy_port()}/v1"
        except OSError:
            pass

    # Lazy install if the binary is missing
    if not is_tool_installed(tool):
        if progress_cb:
            await progress_cb(f"\x1b[36m[ai] {tool} is not installed. Installing now...\x1b[0m\r\n")
        if not await install_tool(tool, progress_callback=progress_cb):
            raise RuntimeError("Installation failed. Check your network connection and try again.")
        if progress_cb:
            await progress_cb(f"\x1b[32mInstallation complete. Launching {tool}...\x1b[0m\r\n")

    # Resolve binary path — prefer lazy-installed, fall back to system
    run_cmd = list(config["cmd"])
    installed_path = get_tool_binary_path(tool)
    if installed_path:
        run_cmd[0] = installed_path
    if tool == "pi":
        pi_wrapper = os.path.join(default_cwd, "pi", "pi-fabric")
        if os.path.isfile(pi_wrapper):
            run_cmd = [pi_wrapper]
    path_val = get_tool_env().get("PATH")
    if path_val:
        env["PATH"] = path_val
    return run_cmd, env, cwd


class CreateAiTerminalBody(BaseModel):
    tool: str
    model: str = ""
    cwd: str = ""


@router.post("/api/terminals/ai")
async def create_ai_terminal(body: CreateAiTerminalBody):
    """Create a persistent tmux-backed AI-tool terminal; returns id + ticket."""
    if body.tool not in TOOL_CONFIGS:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {body.tool!r}")
    try:
        argv, env, cwd = await build_ai_tool_launch(body.tool, model=body.model, cwd=body.cwd)
    except PermissionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    session = _term_sessions.create(
        type=f"ai-{body.tool}", command=argv, env=env, cwd=cwd, label=body.tool,
    )
    m = _term_sessions.meta(session)
    m["ticket"] = _term_auth.mint_ticket(session.id)
    return m


@router.websocket("/ws/terminal/ai/{tool}")
async def ai_terminal_ws(websocket: WebSocket, tool: str, model: str = "", cwd: str = ""):
    """WebSocket endpoint for interactive AI tool terminal.

    Legacy spawn-on-connect path (the UI now prefers the persistent
    `/ws/terminal/attach/{id}` + `POST /api/terminals/ai` flow). Authenticated
    like every other terminal socket.
    """
    if not _term_auth.ws_authorized(websocket):
        await websocket.close(code=1008)
        return
    if tool not in TOOL_CONFIGS:
        await websocket.close(code=4000, reason=f"Unknown tool: {tool}")
        return

    await websocket.accept()

    config = TOOL_CONFIGS[tool]
    api_key = _get_ai_api_key() if config["needs_key"] else ""

    if config["needs_key"] and not api_key:
        await websocket.send_text(
            "\x1b[31mError: AI API key not configured. Go to Settings > Advanced > AI Companion to set your key.\x1b[0m\r\n"
        )
        await websocket.close()
        return

    loop = asyncio.get_event_loop()
    master_fd = None
    proc = None

    async def _ws_progress(line: str):
        try:
            await websocket.send_text(line)
        except Exception:
            pass

    try:
        try:
            run_cmd, env_delta, launch_cwd = await build_ai_tool_launch(
                tool, model=model, cwd=cwd, progress_cb=_ws_progress,
            )
        except RuntimeError as e:
            await websocket.send_text(f"\r\n\x1b[31m{e}\x1b[0m\r\n")
            await websocket.close()
            return

        master_fd, slave_fd = pty.openpty()
        proc = subprocess.Popen(
            run_cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=launch_cwd,
            preexec_fn=os.setsid,
            env={**os.environ, **env_delta},
        )
        os.close(slave_fd)

        # Read from master fd and send to WebSocket
        async def read_pty():
            while True:
                try:
                    data = await loop.run_in_executor(None, _read_master, master_fd)
                    if data:
                        await websocket.send_text(data)
                    else:
                        await asyncio.sleep(0.05)
                except Exception:
                    break

        read_task = asyncio.create_task(read_pty())

        # Read from WebSocket and write to master fd
        while True:
            try:
                msg = await websocket.receive_text()
                parsed = json.loads(msg)
                if parsed.get("type") == "input":
                    os.write(master_fd, parsed["data"].encode("utf-8"))
                elif parsed.get("type") == "resize":
                    cols = parsed.get("cols", 80)
                    rows = parsed.get("rows", 24)
                    winsize = struct.pack("HHHH", rows, cols, 0, 0)
                    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
            except WebSocketDisconnect:
                break
            except Exception:
                break

        read_task.cancel()

    finally:
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        # Back up Claude Code config on session close
        if tool == "claude":
            try:
                _backup_claude_config()
            except Exception:
                pass


def _ensure_git_ready(cwd: str) -> None:
    """Make sure cwd has a usable git repo with user config and an initial commit."""
    # Initialize git repo if missing
    git_dir = os.path.join(cwd, ".git")
    if not os.path.isdir(git_dir):
        subprocess.run(["git", "init"], cwd=cwd, capture_output=True)

    try:
        subprocess.run(
            ["git", "config", "user.name"],
            cwd=cwd, capture_output=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        subprocess.run(
            ["git", "config", "--global", "user.name", "FABRIC User"],
            cwd=cwd, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "--global", "user.email", "user@fabric-testbed.net"],
            cwd=cwd, capture_output=True,
        )

    # Ensure there is at least one commit (aider requires it)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd, capture_output=True,
    )
    if result.returncode != 0:
        subprocess.run(["git", "add", "-A"], cwd=cwd, capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "Initial commit"],
            cwd=cwd, capture_output=True,
        )


# Subdirs inside ~/.claude/ that are session-local and should NOT be persisted
_CLAUDE_SKIP_DIRS = {"cache", "backups", "projects", "conversations", "todos"}


def _backup_claude_config() -> None:
    """Back up the entire ~/.claude/ directory and ~/.claude.json to persistent storage."""
    from app.settings_manager import get_tool_config_dir, get_storage_dir
    home = os.path.expanduser("~")
    claude_dir = os.path.join(home, ".claude")
    # Multi-user mounts ~/.claude as a symlink into the user's (persistent)
    # folder, so it's already persisted per-user — don't also copy it.
    if os.path.islink(claude_dir):
        return
    backup_dir = get_tool_config_dir("claude-code")

    # Copy all files from ~/.claude/ (skip session-local subdirs)
    if os.path.isdir(claude_dir):
        for entry in os.listdir(claude_dir):
            if entry in _CLAUDE_SKIP_DIRS:
                continue
            src = os.path.join(claude_dir, entry)
            dst = os.path.join(backup_dir, entry)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
            elif os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)

    # Back up ~/.claude.json (account/auth state stored at home root)
    claude_json = os.path.join(home, ".claude.json")
    if os.path.isfile(claude_json):
        shutil.copy2(claude_json, os.path.join(backup_dir, ".claude.json"))

    # Also back up workspace .mcp.json
    mcp_src = os.path.join(get_storage_dir(), ".mcp.json")
    if os.path.isfile(mcp_src):
        shutil.copy2(mcp_src, os.path.join(backup_dir, ".mcp.json"))


def _restore_claude_config() -> bool:
    """Restore Claude Code config from persistent storage to ~/.claude/.

    Returns True if config was restored (i.e. backup had meaningful content).
    """
    from app.settings_manager import get_tool_config_dir, get_storage_dir
    home = os.path.expanduser("~")
    claude_dir = os.path.join(home, ".claude")
    # Multi-user mounts ~/.claude from the user's folder — already persistent.
    if os.path.islink(claude_dir):
        return False
    backup_dir = get_tool_config_dir("claude-code")

    # Only restore if backup has settings.json or .credentials.json
    has_settings = os.path.isfile(os.path.join(backup_dir, "settings.json"))
    has_creds = os.path.isfile(os.path.join(backup_dir, ".credentials.json"))
    if not has_settings and not has_creds:
        return False

    os.makedirs(claude_dir, exist_ok=True)

    # Copy all files/dirs from backup into ~/.claude/ (except .claude.json and .mcp.json)
    for entry in os.listdir(backup_dir):
        if entry in (".claude.json", ".mcp.json"):
            continue
        src = os.path.join(backup_dir, entry)
        dst = os.path.join(claude_dir, entry)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
        elif os.path.isdir(src):
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    # Restore ~/.claude.json (account/auth state at home root)
    claude_json_backup = os.path.join(backup_dir, ".claude.json")
    if os.path.isfile(claude_json_backup):
        shutil.copy2(claude_json_backup, os.path.join(home, ".claude.json"))

    # Restore workspace .mcp.json
    mcp_backup = os.path.join(backup_dir, ".mcp.json")
    if os.path.isfile(mcp_backup):
        shutil.copy2(mcp_backup, os.path.join(get_storage_dir(), ".mcp.json"))

    return True


# ---------------------------------------------------------------------------
# Per-user AI-tool config swap (used when switching FABRIC users)
# ---------------------------------------------------------------------------

def _copy_tree_contents(src: str, dst: str) -> None:
    """Copy the contents of *src* into *dst* (files overwrite, dirs replaced).
    No-op (and doesn't create *dst*) when *src* is missing or empty."""
    if not os.path.isdir(src):
        return
    entries = os.listdir(src)
    if not entries:
        return
    os.makedirs(dst, exist_ok=True)
    for entry in entries:
        s = os.path.join(src, entry)
        d = os.path.join(dst, entry)
        if os.path.isfile(s):
            shutil.copy2(s, d)
        elif os.path.isdir(s):
            if os.path.exists(d):
                shutil.rmtree(d)
            shutil.copytree(s, d)


def _backup_codex_config() -> None:
    """Back up ~/.codex (Codex auth/config) to the active user's config dir."""
    from app.settings_manager import get_tool_config_dir
    _copy_tree_contents(os.path.join(os.path.expanduser("~"), ".codex"),
                        get_tool_config_dir("codex"))


def _restore_codex_config() -> None:
    """Restore the active user's ~/.codex from their config dir (if any)."""
    from app.settings_manager import get_tool_config_dir
    _copy_tree_contents(get_tool_config_dir("codex"),
                        os.path.join(os.path.expanduser("~"), ".codex"))


def backup_ai_tool_configs() -> None:
    """Persist the *current* (active) user's home AI-tool config to their
    per-user store. Call BEFORE changing the active user."""
    for fn in (_backup_claude_config, _backup_codex_config):
        try:
            fn()
        except Exception:                       # noqa: BLE001
            logger.warning("AI-tool config backup (%s) failed", fn.__name__, exc_info=True)


def restore_ai_tool_configs() -> None:
    """Replace the home AI-tool config with the *now-active* user's. Clears
    the home dirs first so the previous user's auth/config never leaks; if the
    new user has no saved config the tools start fresh (and re-seed on launch).
    Call AFTER changing the active user."""
    from app.settings_manager import manage_home_ai_paths
    if not manage_home_ai_paths():
        # Outside the container this would rmtree the developer's REAL
        # ~/.claude and ~/.codex.
        logger.debug("Skipping home AI-tool restore (not in the LoomAI container)")
        return
    home = os.path.expanduser("~")
    # Clear current state so nothing carries over from the previous user.
    shutil.rmtree(os.path.join(home, ".claude"), ignore_errors=True)
    shutil.rmtree(os.path.join(home, ".codex"), ignore_errors=True)
    for f in (".claude.json",):
        try:
            os.remove(os.path.join(home, f))
        except OSError:
            pass
    # Restore the active user's saved config (no-op if they have none).
    try:
        _restore_claude_config()
    except Exception:                           # noqa: BLE001
        logger.warning("Claude config restore failed", exc_info=True)
    try:
        _restore_codex_config()
    except Exception:                           # noqa: BLE001
        logger.warning("Codex config restore failed", exc_info=True)


def seed_ai_tool_defaults() -> None:
    """Seed AI tool configs into their default locations at container startup.

    Places configuration files where each tool expects to find them by default:
    - Claude Code: ~/.claude/CLAUDE.md, ~/.claude/settings.json, <cwd>/.mcp.json
    - OpenCode:    ~/.opencode.json, <cwd>/.opencode/ (skills, agents, MCP)
    - Aider:       ~/.aider.conf.yml, ~/.aiderignore, <cwd>/AI_ASSETS.md
    - Crush:       ~/.config/crush/crush.json, .crush/skills/, .crush/agents/
    - Pi:          pi/agent/models.json, pi/agent/settings.json, pi/pi-fabric
    - Deep Agents: .deepagents/AGENTS.md, config.json, skills/, agents/
    - Antigravity: .antigravity/skills/, .antigravity/agents/, AI_ASSETS.md
    - Codex:       .codex/skills/, .codex/agents/, AI_ASSETS.md
    - All tools:   <cwd>/AGENTS.md (shared FABRIC context with tool-specific preamble)
    """
    from app.settings_manager import get_storage_dir as _storage
    home = os.path.expanduser("~")
    cwd = _storage() if os.path.isdir(_storage()) else home

    try:
        from app.harness_config import sync_harness_defaults
        sync_harness_defaults(workspace=cwd, home=home)
    except Exception as e:
        logger.warning("Could not sync LoomAI harness defaults: %s", e)

    # --- Shared FABRIC context (AGENTS.md in workspace) ---
    agents_dst = os.path.join(cwd, "AGENTS.md")
    if os.path.isfile(_FABRIC_AI_MD_PATH) and not os.path.isfile(agents_dst):
        shutil.copy2(_FABRIC_AI_MD_PATH, agents_dst)

    # --- Claude Code: ~/.claude/ + .mcp.json (restore from persistent or seed fresh) ---
    restored = _restore_claude_config()
    if not restored:
        # First run or reset — seed from Docker image defaults
        claude_dir = os.path.join(home, ".claude")
        os.makedirs(claude_dir, exist_ok=True)

        src_claude_md = os.path.join(_CLAUDE_DEFAULTS_DIR, "CLAUDE.md")
        if os.path.isfile(src_claude_md):
            shutil.copy2(src_claude_md, os.path.join(claude_dir, "CLAUDE.md"))

        # settings.json — seed from Docker defaults or empty fallback
        settings_path = os.path.join(claude_dir, "settings.json")
        if not os.path.isfile(settings_path):
            src_settings = os.path.join(_CLAUDE_DEFAULTS_DIR, "settings.json")
            if os.path.isfile(src_settings):
                shutil.copy2(src_settings, settings_path)
            else:
                with open(settings_path, "w") as f:
                    json.dump({}, f)

        # .mcp.json in workspace — only fabric-reports MCP. fabric-api MCP is
        # intentionally excluded: in-container tools should use FABlib directly.
        from app.user_context import get_token_path as _gtp
        token_file = _gtp()
        mcp_json_path = os.path.join(cwd, ".mcp.json")
        py_cmd = f'import json; print(json.load(open("{token_file}"))["id_token"])'
        mcp_servers = {}
        for sname, url in [
            ("fabric-reports", "https://reports.fabric-testbed.net/mcp"),
        ]:
            mcp_servers[sname] = {
                "command": "bash",
                "args": [
                    "-c",
                    f"TOKEN=$(python3 -c '{py_cmd}') && "
                    f"exec npx -y mcp-remote \"{url}\" "
                    f"--header \"Authorization: Bearer $TOKEN\"",
                ],
            }
        with open(mcp_json_path, "w") as f:
            json.dump({"mcpServers": mcp_servers}, f, indent=2)

    # Always ensure CLAUDE.md in workspace and project .claude/ dir
    src_claude_md = os.path.join(_CLAUDE_DEFAULTS_DIR, "CLAUDE.md")
    proj_claude_dir = os.path.join(cwd, ".claude")
    os.makedirs(proj_claude_dir, exist_ok=True)
    if os.path.isfile(src_claude_md) and not os.path.isfile(os.path.join(cwd, "CLAUDE.md")):
        shutil.copy2(src_claude_md, os.path.join(cwd, "CLAUDE.md"))

    # --- OpenCode: ~/.opencode.json + workspace skills/agents ---
    # Global config — providers only (no workspace-specific settings)
    api_key = _get_ai_api_key()
    if api_key:
        try:
            ws_config = _setup_opencode_workspace(cwd)
            oc_config = _build_opencode_config(api_key, workspace_config=ws_config)
            write_cfg = {k: v for k, v in oc_config.items() if not k.startswith("_")}

            # Write to both global and workspace locations
            from app.harness_config import _merge_json_file
            _merge_json_file(os.path.join(home, ".opencode.json"), write_cfg)
            _merge_json_file(os.path.join(cwd, "opencode.json"), write_cfg)
        except Exception as e:
            logger.warning("Could not seed OpenCode config: %s", e)

    # --- Aider: ~/.aider.conf.yml ---
    src_aider_conf = os.path.join(_AIDER_DEFAULTS_DIR, ".aider.conf.yml")
    if os.path.isfile(src_aider_conf) and not os.path.isfile(os.path.join(home, ".aider.conf.yml")):
        shutil.copy2(src_aider_conf, os.path.join(home, ".aider.conf.yml"))

    src_aider_ignore = os.path.join(_AIDER_DEFAULTS_DIR, ".aiderignore")
    if os.path.isfile(src_aider_ignore):
        if not os.path.isfile(os.path.join(home, ".aiderignore")):
            shutil.copy2(src_aider_ignore, os.path.join(home, ".aiderignore"))
        if not os.path.isfile(os.path.join(cwd, ".aiderignore")):
            shutil.copy2(src_aider_ignore, os.path.join(cwd, ".aiderignore"))

    # --- Crush: ~/.config/crush/crush.json ---
    if api_key and not os.path.isfile(os.path.join(cwd, ".crush.json")):
        crush_global_dir = os.path.join(home, ".config", "crush")
        os.makedirs(crush_global_dir, exist_ok=True)
        try:
            _setup_crush_workspace(cwd, api_key)
            # Also copy to global location
            crush_workspace = os.path.join(cwd, ".crush.json")
            if os.path.isfile(crush_workspace):
                shutil.copy2(crush_workspace, os.path.join(crush_global_dir, "crush.json"))
        except Exception as e:
            logger.warning("Could not seed Crush config: %s", e)

    # --- Deep Agents: .deepagents/AGENTS.md + config.json ---
    try:
        _setup_deepagents_workspace(cwd, _get_ai_api_key())
    except Exception as e:
        logger.warning("Could not seed Deep Agents config: %s", e)

    # --- Antigravity: AGENTS.md ---
    try:
        _setup_antigravity_workspace(cwd)
    except Exception as e:
        logger.warning("Could not seed Antigravity workspace: %s", e)

    # --- Codex: AGENTS.md ---
    try:
        _setup_codex_workspace(cwd)
    except Exception as e:
        logger.warning("Could not seed Codex workspace: %s", e)

    # --- Git setup (needed by Aider, OpenCode, Crush, Pi, Deep Agents) ---
    _ensure_git_ready(cwd)

    logger.info("AI tool defaults seeded to home=%s, workspace=%s", home, cwd)


def _harness_workspace_home() -> tuple[str, str]:
    from app.settings_manager import get_storage_dir as _storage

    home = os.path.expanduser("~")
    workspace = _storage() if os.path.isdir(_storage()) else home
    return workspace, home


def sync_ai_tool_harness_defaults(harness: str | None = None) -> dict:
    """Regenerate source-controlled external harness defaults for this user."""
    from app.harness_config import harness_status, sync_harness_defaults

    workspace, home = _harness_workspace_home()
    selected = [harness] if harness else None
    result = sync_harness_defaults(workspace=workspace, home=home, harnesses=selected)
    mcp_servers: list[str] = []
    opencode_path = os.path.join(workspace, "opencode.json")
    try:
        with open(opencode_path) as f:
            opencode_config = json.load(f)
        mcp_servers = sorted((opencode_config.get("mcp") or {}).keys())
    except (OSError, json.JSONDecodeError, AttributeError):
        mcp_servers = []

    response = {
        "status": "ok",
        "workspace": result.get("workspace", workspace),
        "home": result.get("home", home),
        "agents": result.get("agents", 0),
        "skills": result.get("skills", 0),
        "providers": result.get("providers", []),
        "mcp_servers": mcp_servers,
        "mapping": os.path.join(workspace, ".loomai", "harness-defaults", "MAPPING.md"),
        "managed_service": {
            "name": "loomai-harness",
            "transport": "stdio",
            "command": "python3 -m app.harness_mcp_server",
            "backend_url_env": "LOOMAI_URL",
        },
    }
    if harness:
        response["harness"] = harness_status(harness, workspace=workspace, home=home)
    return response


def reset_ai_tool_harness_defaults(harness: str) -> dict:
    """Overwrite one LoomAI-managed external harness with pristine defaults."""
    from app.harness_config import reset_harness_defaults

    workspace, home = _harness_workspace_home()
    return reset_harness_defaults(harness, workspace=workspace, home=home)


def _harness_status_response(harness: str | None = None) -> dict:
    from app.harness_config import harness_status, harness_statuses

    workspace, home = _harness_workspace_home()
    if harness:
        return {"status": "ok", "workspace": workspace, "home": home, "harness": harness_status(harness, workspace=workspace, home=home)}
    return {"status": "ok", **harness_statuses(workspace=workspace, home=home)}


# ---------------------------------------------------------------------------
# Config propagation — update all AI tool workspace configs when settings change
# ---------------------------------------------------------------------------


def propagate_ai_configs() -> dict:
    """Re-generate workspace configs for all AI tools using current settings.

    Called as a background task after settings are saved so that changes to
    API keys, server URLs, or model preferences take effect without requiring
    a container restart or manual re-seed.

    Returns a dict mapping tool names to their propagation status.
    """
    from app.settings_manager import get_storage_dir as _storage

    home = os.path.expanduser("~")
    cwd = _storage() if os.path.isdir(_storage()) else home
    api_key = _get_ai_api_key()
    nrp_key = _get_nrp_api_key()

    results: dict[str, str] = {}

    # --- OpenCode: rebuild opencode.json with current providers/models ---
    try:
        if api_key:
            ws_config = _setup_opencode_workspace(cwd)
            oc_config = _build_opencode_config(api_key, workspace_config=ws_config)
            write_cfg = {k: v for k, v in oc_config.items() if not k.startswith("_")}

            from app.harness_config import _merge_json_file
            _merge_json_file(os.path.join(cwd, "opencode.json"), write_cfg)
            try:
                _merge_json_file(os.path.join(home, ".opencode.json"), write_cfg)
            except OSError as e:
                logger.debug("Skipped home OpenCode config copy: %s", e)
            results["opencode"] = "ok"
        else:
            results["opencode"] = "skipped (no API key)"
    except Exception as e:
        logger.warning("Failed to propagate OpenCode config: %s", e)
        results["opencode"] = f"error: {e}"

    # --- Aider: re-copy config files (uses model proxy for LLM access) ---
    try:
        _setup_aider_workspace(cwd)
        # Also update global aider config
        src_aider_conf = os.path.join(_AIDER_DEFAULTS_DIR, ".aider.conf.yml")
        if os.path.isfile(src_aider_conf):
            try:
                if not os.path.isfile(os.path.join(home, ".aider.conf.yml")):
                    shutil.copy2(src_aider_conf, os.path.join(home, ".aider.conf.yml"))
            except OSError as e:
                logger.debug("Skipped home Aider config copy: %s", e)
        src_aider_ignore = os.path.join(_AIDER_DEFAULTS_DIR, ".aiderignore")
        if os.path.isfile(src_aider_ignore):
            try:
                if not os.path.isfile(os.path.join(home, ".aiderignore")):
                    shutil.copy2(src_aider_ignore, os.path.join(home, ".aiderignore"))
            except OSError as e:
                logger.debug("Skipped home Aider ignore copy: %s", e)
            if not os.path.isfile(os.path.join(cwd, ".aiderignore")):
                shutil.copy2(src_aider_ignore, os.path.join(cwd, ".aiderignore"))
        results["aider"] = "ok"
    except Exception as e:
        logger.warning("Failed to propagate Aider config: %s", e)
        results["aider"] = f"error: {e}"

    # --- Claude Code: re-seed workspace context ---
    try:
        _setup_claude_workspace(cwd)
        results["claude"] = "ok"
    except Exception as e:
        logger.warning("Failed to propagate Claude Code config: %s", e)
        results["claude"] = f"error: {e}"

    # --- Crush: rebuild .crush.json with current providers/models ---
    try:
        if api_key:
            _setup_crush_workspace(cwd, api_key)
            # Also copy to global location
            crush_global_dir = os.path.join(home, ".config", "crush")
            crush_workspace = os.path.join(cwd, ".crush.json")
            try:
                os.makedirs(crush_global_dir, exist_ok=True)
                if os.path.isfile(crush_workspace):
                    shutil.copy2(crush_workspace, os.path.join(crush_global_dir, "crush.json"))
            except OSError as e:
                logger.debug("Skipped home Crush config copy: %s", e)
            results["crush"] = "ok"
        else:
            results["crush"] = "skipped (no API key)"
    except Exception as e:
        logger.warning("Failed to propagate Crush config: %s", e)
        results["crush"] = f"error: {e}"

    # --- Deep Agents: rebuild .deepagents/config.json with current providers ---
    try:
        _setup_deepagents_workspace(cwd, api_key or "")
        results["deepagents"] = "ok"
    except Exception as e:
        logger.warning("Failed to propagate Deep Agents config: %s", e)
        results["deepagents"] = f"error: {e}"

    # --- Antigravity: re-seed workspace context ---
    try:
        _setup_antigravity_workspace(cwd)
        results["antigravity"] = "ok"
    except Exception as e:
        logger.warning("Failed to propagate Antigravity config: %s", e)
        results["antigravity"] = f"error: {e}"

    # --- Codex: re-seed workspace context ---
    try:
        codex_workspaces = [cwd]
        users_dir = os.path.join(cwd, ".loomai", "users")
        if os.path.isdir(users_dir):
            for entry in os.listdir(users_dir):
                workspace = os.path.join(users_dir, entry)
                if os.path.isdir(workspace):
                    codex_workspaces.append(workspace)
        seen: set[str] = set()
        for workspace in codex_workspaces:
            real_workspace = os.path.realpath(workspace)
            if real_workspace in seen:
                continue
            seen.add(real_workspace)
            _setup_codex_workspace(workspace)
        results["codex"] = "ok"
    except Exception as e:
        logger.warning("Failed to propagate Codex config: %s", e)
        results["codex"] = f"error: {e}"

    # --- Jupyter AI: reconfigure with current providers ---
    try:
        from app.routes.jupyter import _configure_jupyter_ai
        # Build a minimal env dict — _configure_jupyter_ai reads from settings_manager
        env: dict[str, str] = dict(os.environ)
        if api_key:
            env["OPENAI_API_KEY"] = api_key
            env["FABRIC_AI_API_KEY"] = api_key
            env["OPENAI_BASE_URL"] = f"{_ai_server_url()}/v1"
        if nrp_key:
            env["NRP_API_KEY"] = nrp_key
        _configure_jupyter_ai(env)
        results["jupyter_ai"] = "ok"
    except Exception as e:
        logger.warning("Failed to propagate Jupyter AI config: %s", e)
        results["jupyter_ai"] = f"error: {e}"

    logger.info("AI config propagation complete: %s", results)
    return results


def refresh_live_ai_tools() -> dict:
    """Stop live AI tool processes that captured the API key in their env.

    Called after the FABRIC LLM key is replaced: OpenCode web, Aider web and
    the model proxies receive the key via environment at launch, so rewriting
    config files (propagate_ai_configs) does not reach the running processes.
    Stopped tools restart with the current key on next use — the terminal
    model proxy on the next AI terminal launch, the web tools when reopened.

    Returns a dict mapping tool names to "stopped"/"not_running".
    """
    global _opencode_web_proc, _opencode_web_proxy, _aider_web_proc, _terminal_model_proxy

    def _kill(proc: subprocess.Popen | None) -> bool:
        if proc is None or proc.poll() is not None:
            return False
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return True

    results = {}
    oc_stopped = _kill(_opencode_web_proc)
    oc_proxy_stopped = _kill(_opencode_web_proxy)
    results["opencode-web"] = "stopped" if (oc_stopped or oc_proxy_stopped) else "not_running"
    _opencode_web_proc = None
    _opencode_web_proxy = None

    results["aider-web"] = "stopped" if _kill(_aider_web_proc) else "not_running"
    _aider_web_proc = None

    results["model-proxy"] = "stopped" if _kill(_terminal_model_proxy) else "not_running"
    _terminal_model_proxy = None

    # PTY-backed AI tool terminal sessions also captured the key in their
    # env at launch (build_ai_tool_launch exports FABRIC_AI_API_KEY /
    # OPENAI_API_KEY for every tool, even needs_key=False ones) — kill them
    # all so the next launch picks up the current key. Plain shell terminals
    # are left alone.
    killed = 0
    try:
        for session_meta in _term_sessions.list_sessions():
            if not session_meta.get("type", "").startswith("ai-"):
                continue
            if _term_sessions.kill(session_meta["id"]):
                killed += 1
    except Exception as e:
        logger.warning("Failed to kill AI terminal sessions after key change: %s", e)
    results["ai-terminals"] = f"stopped {killed}" if killed else "not_running"

    # JupyterLab: the server receives OPENAI_API_KEY/base via env and reads
    # the Jupyter AI provider config only at startup, so a running instance
    # keeps the replaced key. Stop the backend-managed process; in the
    # combined-image/helm modes signal the supervisord-managed one (its
    # supervisor respawns it); in the split-image mode kill the unsupervised
    # entrypoint-started one and take over with a backend-managed instance.
    try:
        from app.routes import jupyter as _jupyter
        managed_stopped = _jupyter.stop_jupyter_sync("LLM key changed")
        outcome = "none" if managed_stopped else _jupyter.restart_external_jupyter()
        if outcome == "supervised":
            results["jupyterlab"] = "restarted"
        elif outcome == "stuck":
            results["jupyterlab"] = "error: old instance did not release the port"
        elif managed_stopped and not _jupyter.wait_jupyter_port_free():
            # start_jupyter() would mistake the dying instance's socket for
            # a running server and falsely report success without spawning.
            results["jupyterlab"] = "error: old instance did not release the port"
        elif managed_stopped or outcome == "unsupervised":
            # Usually running in a background-task worker thread (no loop);
            # fall back to a dedicated thread if a loop is already running.
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                start_result = asyncio.run(_jupyter.start_jupyter())
            else:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=1) as pool:
                    start_result = pool.submit(asyncio.run, _jupyter.start_jupyter()).result()
            status = start_result.get("status", "unknown")
            if status == "running" and start_result.get("ready", True):
                results["jupyterlab"] = "restarted (running)"
            elif status == "running":
                # Spawned, but the 30s readiness poll never saw it accept a
                # connection — a launch that cannot be verified is a failure,
                # not a success.
                logger.warning("JupyterLab takeover spawned a server that never became ready")
                results["jupyterlab"] = "error: replacement started but not responding"
            else:
                detail = start_result.get("error") or status
                logger.warning("JupyterLab takeover did not start a server: %s", detail)
                results["jupyterlab"] = f"error: takeover failed ({detail})"
        else:
            results["jupyterlab"] = "not_running"
    except Exception as e:
        logger.warning("Failed to restart JupyterLab after key change: %s", e)
        results["jupyterlab"] = f"error: {e}"

    logger.info("Live AI tool refresh after key change: %s", results)
    return results


@router.post("/api/ai/propagate-config")
async def propagate_config_endpoint():
    """Manually trigger AI config propagation to all tool workspaces.

    Re-generates workspace configuration files for all AI tools (OpenCode,
    Aider, Claude Code, Crush, Deep Agents, Antigravity, Codex, Jupyter AI) using the current
    settings.  Useful after changing API keys or server URLs.
    """
    results = propagate_ai_configs()
    return {"status": "ok", "tools": results}


@router.get("/api/ai/tools/harnesses")
async def list_ai_tool_harnesses_endpoint():
    """Return Configure-page status for LoomAI-managed external harnesses."""
    try:
        return _harness_status_response()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/ai/tools/harnesses/{harness_name}/status")
async def get_ai_tool_harness_status_endpoint(harness_name: str):
    """Return status for one LoomAI-managed external harness."""
    try:
        return _harness_status_response(harness_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/ai/tools/harnesses/{harness_name}/sync")
async def sync_ai_tool_harness_endpoint(harness_name: str):
    """Regenerate one LoomAI-managed external harness default."""
    try:
        return sync_ai_tool_harness_defaults(harness_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/ai/tools/harnesses/{harness_name}/reset")
async def reset_ai_tool_harness_endpoint(harness_name: str):
    """Overwrite one LoomAI-managed external harness with pristine defaults."""
    try:
        return reset_ai_tool_harness_defaults(harness_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/ai/tools/harnesses/{harness_name}/docs")
async def get_ai_tool_harness_docs_endpoint(harness_name: str):
    """Return markdown docs for one LoomAI-managed external harness."""
    from app.harness_config import harness_docs_markdown

    workspace, home = _harness_workspace_home()
    try:
        text = harness_docs_markdown(harness_name, workspace=workspace, home=home)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PlainTextResponse(text, media_type="text/markdown")


@router.post("/api/ai/tools/sync")
async def sync_ai_tools_endpoint():
    """Regenerate LoomAI-managed external harness defaults.

    This is the user-facing equivalent of the startup/build sync hook. It
    refreshes generated AGENTS/CLAUDE/Aider/Codex/OpenCode/Goose/Crush
    defaults, including the fabric-reports and loomai-harness MCP entries,
    while preserving user-owned config values.
    """
    return sync_ai_tool_harness_defaults()


def _read_master(fd: int) -> str:
    """Read available data from a PTY master fd."""
    try:
        data = os.read(fd, 4096)
        return data.decode("utf-8", errors="replace") if data else ""
    except OSError:
        return ""
