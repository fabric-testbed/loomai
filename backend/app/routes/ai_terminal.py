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

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse

from app.settings_manager import get_fabric_api_key as _get_ai_api_key, get_nrp_api_key as _get_nrp_api_key
from app.tool_installer import (
    is_tool_installed, install_tool, get_tool_binary_path,
    get_tool_env, get_all_tool_status, TOOL_REGISTRY,
)

logger = logging.getLogger(__name__)

router = APIRouter()

def _ai_server_url() -> str:
    from app.settings_manager import get_ai_server_url
    return get_ai_server_url()

def _nrp_server_url() -> str:
    from app.settings_manager import get_nrp_server_url
    return get_nrp_server_url()

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
    "minimax-m2": 1048576,
    "olmo": 32768,
    "glm-4.7": 131072,
    "qwen3": 131072,
    "qwen3-small": 131072,
    "qwen3-27b": 131072,
    "gemma": 8192,
    "gh200-test": 131072,
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
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key}",
    })
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
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key}",
    })
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
            headers={"x-litellm-api-key": api_key},
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


def _check_model_health(server_url: str, api_key: str, model_id: str) -> bool:
    """Send a minimal completion to verify the model actually works.

    Returns True if the model responds successfully, False otherwise.
    Uses max_tokens=1 to minimize cost/latency.
    """
    try:
        data = json.dumps({
            "model": model_id,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }).encode()
        req = urllib.request.Request(
            f"{server_url}/v1/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as e:
        logger.debug("Model health check failed for %s: %s", model_id, e)
        return False


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

    # Build models dict — each available model gets an entry
    models_dict = {}
    for m in (_model_ids(models) if models else [default]):
        models_dict[m] = {"name": m}
    if default not in models_dict:
        models_dict[default] = {"name": default}
    if small not in models_dict:
        models_dict[small] = {"name": small}

    providers: dict = {
        "fabric": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "FABRIC AI",
            "options": {
                "baseURL": f"{_ai_server_url()}/v1",
                "apiKey": "{env:FABRIC_AI_API_KEY}",
            },
            "models": models_dict,
        }
    }

    # Add NRP provider if key is available
    nrp_key = _get_nrp_api_key()
    if nrp_key:
        nrp_models = _fetch_nrp_models(nrp_key)
        if nrp_models:
            nrp_models_dict = {m: {"name": m} for m in _model_ids(nrp_models)}
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
_OPENCODE_DEFAULTS_DIR = _SHARED_DIR  # Skills and agents live in shared/
_AIDER_DEFAULTS_DIR = os.path.join(_AI_TOOLS_DIR, "aider")
_CLAUDE_DEFAULTS_DIR = os.path.join(_AI_TOOLS_DIR, "claude-code")
_CRUSH_DEFAULTS_DIR = os.path.join(_AI_TOOLS_DIR, "crush")
_DEEPAGENTS_DEFAULTS_DIR = os.path.join(_AI_TOOLS_DIR, "deepagents")

# Skills to skip (conflict with OpenCode internals)
_SKIP_SKILLS = {"compact", "help"}

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
}


def _write_agents_md(cwd: str, tool_name: str) -> None:
    """Write AGENTS.md with a tool-specific preamble + shared FABRIC_AI.md content."""
    agents_md = os.path.join(cwd, "AGENTS.md")
    if os.path.isfile(agents_md):
        return  # Don't overwrite existing
    if not os.path.isfile(_FABRIC_AI_MD_PATH):
        return
    preamble = _TOOL_PREAMBLES.get(tool_name, "")
    with open(_FABRIC_AI_MD_PATH) as f:
        content = f.read()
    with open(agents_md, "w") as f:
        f.write(preamble + content)
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
    skills_src = os.path.join(_OPENCODE_DEFAULTS_DIR, "skills")
    skill_count = 0
    if os.path.isdir(skills_src):
        for fname in os.listdir(skills_src):
            if not fname.endswith(".md"):
                continue
            skill_name = fname[:-3]
            if skill_name in _SKIP_SKILLS:
                continue
            skill_dir = os.path.join(oc_dir, "skills", skill_name)
            os.makedirs(skill_dir, exist_ok=True)

            with open(os.path.join(skills_src, fname)) as f:
                content = f.read()
            # Convert frontmatter to OpenCode YAML frontmatter
            if not content.startswith("---"):
                content = "---\n" + content

            with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
                f.write(content)
            skill_count += 1
    logger.info("Created %d OpenCode skills", skill_count)

    # --- Agent prompts → .opencode/agent-prompts/<name>.md ---
    prompts_dir = os.path.join(oc_dir, "agent-prompts")
    os.makedirs(prompts_dir, exist_ok=True)
    agent_cfg: dict = {}
    agents_src = os.path.join(_OPENCODE_DEFAULTS_DIR, "agents")
    if os.path.isdir(agents_src):
        for fname in os.listdir(agents_src):
            if not fname.endswith(".md"):
                continue
            name = fname[:-3]
            with open(os.path.join(agents_src, fname)) as f:
                raw = f.read()

            # Parse frontmatter
            desc = ""
            body_lines: list[str] = []
            past_sep = False
            for line in raw.split("\n"):
                if not past_sep:
                    if line.strip() == "---":
                        past_sep = True
                    elif line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip()
                else:
                    body_lines.append(line)
            body = "\n".join(body_lines).strip()

            prompt_file = os.path.join(prompts_dir, f"{name}.md")
            with open(prompt_file, "w") as f:
                f.write(body)

            agent_cfg[name] = {
                "description": desc,
                "prompt": "{file:.opencode/agent-prompts/" + name + ".md}",
                "mode": "subagent",
            }
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

    # Aider config
    src_conf = os.path.join(_AIDER_DEFAULTS_DIR, ".aider.conf.yml")
    if os.path.isfile(src_conf):
        dst_conf = os.path.join(cwd, ".aider.conf.yml")
        shutil.copy2(src_conf, dst_conf)
        logger.info("Wrote .aider.conf.yml")

    # Aider ignore patterns
    src_ignore = os.path.join(_AIDER_DEFAULTS_DIR, ".aiderignore")
    if os.path.isfile(src_ignore):
        shutil.copy2(src_ignore, os.path.join(cwd, ".aiderignore"))
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
    skills_src = os.path.join(_SHARED_DIR, "skills")
    if os.path.isdir(skills_src):
        cmds_dir = os.path.join(cwd, ".claude", "commands")
        os.makedirs(cmds_dir, exist_ok=True)
        skill_count = 0
        for fname in os.listdir(skills_src):
            if not fname.endswith(".md"):
                continue
            # Strip YAML frontmatter — Claude Code commands use the file directly
            with open(os.path.join(skills_src, fname)) as f:
                content = f.read()
            # Remove frontmatter (name:/description:/---) for Claude Code format
            lines = content.split("\n")
            body_start = 0
            if lines and lines[0].startswith("name:"):
                for i, line in enumerate(lines):
                    if line.strip() == "---":
                        body_start = i + 1
                        break
            body = "\n".join(lines[body_start:]).strip()
            if body:
                with open(os.path.join(cmds_dir, fname), "w") as f:
                    f.write(body + "\n")
                skill_count += 1
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

    fabric_models = [{"id": m, "name": m} for m in (models if models else [default_model])]

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
            providers["nrp"] = {
                "id": "nrp",
                "base_url": f"{_nrp_server_url()}/v1",
                "type": "openai",
                "api_key": nrp_key,
                "models": [{"id": m, "name": m} for m in nrp_models],
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
    with open(dst, "w") as f:
        json.dump(crush_config, f, indent=2)
    logger.info("Wrote .crush.json for Crush with %d providers", len(providers))

    # Copy shared skills and agents so Crush has FABRIC context
    skills_src = os.path.join(_SHARED_DIR, "skills")
    if os.path.isdir(skills_src):
        skills_dst = os.path.join(cwd, ".crush", "skills")
        os.makedirs(skills_dst, exist_ok=True)
        for fname in os.listdir(skills_src):
            if fname.endswith(".md"):
                shutil.copy2(os.path.join(skills_src, fname), os.path.join(skills_dst, fname))
        logger.info("Copied shared skills to .crush/skills/")
    agents_src = os.path.join(_SHARED_DIR, "agents")
    if os.path.isdir(agents_src):
        agents_dst = os.path.join(cwd, ".crush", "agents")
        os.makedirs(agents_dst, exist_ok=True)
        for fname in os.listdir(agents_src):
            if fname.endswith(".md"):
                shutil.copy2(os.path.join(agents_src, fname), os.path.join(agents_dst, fname))
        logger.info("Copied shared agents to .crush/agents/")


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

    # Copy shared skills and agents into .deepagents/
    shared_skills = os.path.join(_SHARED_DIR, "skills")
    shared_agents = os.path.join(_SHARED_DIR, "agents")
    da_skills = os.path.join(da_dir, "skills")
    da_agents = os.path.join(da_dir, "agents")
    if os.path.isdir(shared_skills) and not os.path.isdir(da_skills):
        shutil.copytree(shared_skills, da_skills)
        logger.info("Copied %d skills to .deepagents/skills/", len(os.listdir(da_skills)))
    if os.path.isdir(shared_agents) and not os.path.isdir(da_agents):
        shutil.copytree(shared_agents, da_agents)
        logger.info("Copied %d agents to .deepagents/agents/", len(os.listdir(da_agents)))

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
            "models": models if models else [default_model],
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
                "models": nrp_models,
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

# Tool definitions: env setup and command for each AI tool
TOOL_CONFIGS = {
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
    "crush": {
        "env": lambda key: {
            "OPENAI_API_KEY": key,
            "OPENAI_BASE_URL": f"{_ai_server_url()}/v1",
        },
        "cmd": ["crush"],
        "needs_key": True,
    },
    "claude": {
        "env": lambda key: {"NODE_OPTIONS": "--dns-result-order=ipv4first"},
        "cmd": ["claude"],
        "needs_key": False,
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


@router.post("/api/ai/tools/{tool_id}/install")
async def trigger_tool_install(tool_id: str):
    """Trigger installation of an AI tool. Returns when complete."""
    if tool_id not in TOOL_REGISTRY:
        return {"error": f"Unknown tool: {tool_id}", "status": "error"}
    if is_tool_installed(tool_id):
        return {"status": "already_installed", "tool": tool_id}
    lines: list[str] = []
    async def collect(line: str):
        lines.append(line)
    success = await install_tool(tool_id, progress_callback=collect)
    return {
        "status": "installed" if success else "error",
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

    if is_tool_installed(tool_id):
        async def _already():
            yield f"data: {json.dumps({'type': 'done', 'status': 'already_installed', 'tool': tool_id})}\n\n"
        return StreamingResponse(_already(), media_type="text/event-stream")

    async def _stream():
        queue: asyncio.Queue[str | None] = asyncio.Queue()

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

        # Emit tool info as the first event
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
        status = "installed" if result == "__SUCCESS__" else "error"
        yield f"data: {json.dumps({'type': 'done', 'status': status, 'tool': tool_id})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


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
        "OPENAI_BASE_URL": f"{_ai_server_url()}/v1",
    }
    nrp_key = _get_nrp_api_key()
    if nrp_key:
        tool_env["NRP_API_KEY"] = nrp_key

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
        if new_lookup[key].get("context_length") != old_lookup[key].get("context_length"):
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
        healthy = _check_model_health(fabric_server, fabric_key, mid)
        ctx_val = ctx_map.get(mid) or _FABRIC_CONTEXT_DEFAULTS.get(mid) or 131072
        profile = get_model_profile(mid, context_length=ctx_val)
        fabric_entries.append({
            "id": mid, "name": mid, "healthy": healthy,
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
        healthy = _check_model_health(nrp_server, nrp_key or "anonymous", mid)
        profile = get_model_profile(mid, context_length=ctx)
        nrp_entries.append({
            "id": mid, "name": mid, "healthy": healthy,
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
        if not cp_url:
            continue
        try:
            url = f"{cp_url.rstrip('/')}/v1/models"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {cp_key}"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
            cp_models = []
            for m in body.get("data", []):
                mid = m["id"]
                healthy = _check_model_health(cp_url.rstrip("/"), cp_key, mid)
                cp_models.append({"id": mid, "name": mid, "healthy": healthy,
                                  "context_length": m.get("context_length")})
                if healthy and not default:
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
    api_key = _get_ai_api_key()
    if not api_key:
        return {"default": "", "source": ""}

    server_url = _ai_server_url()
    model_ids = _model_ids(_fetch_models(api_key))

    # Check preferred models first
    for pref in _PREFERRED_MODELS:
        for m in model_ids:
            if pref in m.lower():
                if _check_model_health(server_url, api_key, m):
                    return {"default": m, "source": "fabric"}
                break  # This preferred model failed, try next preference

    # Check remaining FABRIC models
    for m in model_ids:
        if _check_model_health(server_url, api_key, m):
            return {"default": m, "source": "fabric"}

    # Try NRP
    nrp_key = _get_nrp_api_key()
    if nrp_key:
        nrp_ids = _model_ids(_fetch_nrp_models(nrp_key))
        for m in nrp_ids:
            if _check_model_health(_nrp_server_url(), nrp_key, m):
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
        settings.setdefault("ai", {})["discovered_models"] = {
            "fabric": fabric_list,
            "nrp": nrp_list,
        }
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
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
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


@router.websocket("/ws/terminal/ai/{tool}")
async def ai_terminal_ws(websocket: WebSocket, tool: str, model: str = "", cwd: str = ""):
    """WebSocket endpoint for interactive AI tool terminal."""
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
    proxy_proc = None

    try:
        master_fd, slave_fd = pty.openpty()

        # Build environment
        tool_env = {**os.environ, "TERM": "xterm-256color"}
        tool_env.update(config["env"](api_key))

        from app.settings_manager import get_storage_dir as _storage
        default_cwd = _storage() if os.path.isdir(_storage()) else os.path.expanduser("~")

        # Use requested cwd if valid and within storage root
        if cwd and os.path.isdir(cwd):
            real_cwd = os.path.realpath(cwd)
            real_root = os.path.realpath(default_cwd)
            if real_cwd.startswith(real_root):
                cwd = real_cwd
            else:
                cwd = default_cwd
        else:
            cwd = default_cwd

        # Add NRP key to environment if available (all tools can use it)
        nrp_key = _get_nrp_api_key()
        if nrp_key:
            tool_env["NRP_API_KEY"] = nrp_key

        # Tool-specific workspace setup
        if tool == "aider":
            _ensure_git_ready(cwd)
            _setup_aider_workspace(cwd)
        elif tool == "claude":
            _setup_claude_workspace(cwd)
        elif tool == "crush":
            _ensure_git_ready(cwd)
            _setup_crush_workspace(cwd, api_key, model_override=model)
        elif tool == "deepagents":
            _ensure_git_ready(cwd)
            _setup_deepagents_workspace(cwd, api_key, model_override=model)

        # Build opencode.json dynamically from available models on the AI server
        if tool == "opencode":
            _ensure_git_ready(cwd)
            oc_cfg = os.path.join(cwd, "opencode.json")
            try:
                ws_config = _setup_opencode_workspace(cwd)
                oc_config = _build_opencode_config(
                    api_key, model_override=model, workspace_config=ws_config,
                )
                # Write config without internal keys
                write_cfg = {k: v for k, v in oc_config.items() if not k.startswith("_")}
                with open(oc_cfg, "w") as f:
                    json.dump(write_cfg, f, indent=2)
                logger.info("Wrote opencode.json with model=%s", write_cfg.get("model"))

                # Start model proxy — rewrites unknown model names to our default
                proxy_proc = _start_model_proxy(
                    api_key,
                    oc_config["_default"],
                    oc_config["_allowed"],
                    tool_env,
                )
                if proxy_proc:
                    time.sleep(0.3)  # let the proxy bind
                    tool_env["OPENAI_BASE_URL"] = f"http://127.0.0.1:{_model_proxy_port()}/v1"
            except OSError:
                pass

        # --- Lazy install: if tool binary not found, install it first ---
        tool_registry_id = tool  # tool IDs match between TOOL_CONFIGS and TOOL_REGISTRY
        if not is_tool_installed(tool_registry_id):
            await websocket.send_text(
                f"\x1b[36m[ai] {tool} is not installed. Installing now...\x1b[0m\r\n"
            )
            async def ws_progress(line: str):
                try:
                    await websocket.send_text(line)
                except Exception:
                    pass
            success = await install_tool(tool_registry_id, progress_callback=ws_progress)
            if not success:
                await websocket.send_text(
                    "\x1b[31mInstallation failed. Please check your network connection and try again.\x1b[0m\r\n"
                )
                await websocket.close()
                return
            await websocket.send_text(
                f"\x1b[32mInstallation complete. Launching {tool}...\x1b[0m\r\n"
            )

        # Resolve binary path — prefer lazy-installed, fall back to system
        run_cmd = list(config["cmd"])
        installed_path = get_tool_binary_path(tool)
        if installed_path:
            run_cmd[0] = installed_path

        # Merge lazy-install env (PATH with venv/bin and npm/bin)
        tool_env.update({k: v for k, v in get_tool_env().items() if k == "PATH"})

        proc = subprocess.Popen(
            run_cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=cwd,
            preexec_fn=os.setsid,
            env=tool_env,
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
        if proxy_proc is not None:
            try:
                os.killpg(os.getpgid(proxy_proc.pid), signal.SIGTERM)
                proxy_proc.wait(timeout=2)
            except Exception:
                try:
                    proxy_proc.kill()
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


def seed_ai_tool_defaults() -> None:
    """Seed AI tool configs into their default locations at container startup.

    Places configuration files where each tool expects to find them by default:
    - Claude Code: ~/.claude/CLAUDE.md, ~/.claude/settings.json, <cwd>/.mcp.json
    - OpenCode:    ~/.opencode.json, <cwd>/.opencode/ (skills, agents, MCP)
    - Aider:       ~/.aider.conf.yml, ~/.aiderignore
    - Crush:       ~/.config/crush/crush.json, .crush/skills/, .crush/agents/
    - Deep Agents: .deepagents/AGENTS.md, config.json, skills/, agents/
    - All tools:   <cwd>/AGENTS.md (shared FABRIC context with tool-specific preamble)

    Provider configuration status (verified Phase 12):
    ┌──────────────┬─────────┬──────┬────────┬────────┬───────────┐
    │ Tool         │ FABRIC  │ NRP  │ Skills │ Agents │ AGENTS.md │
    ├──────────────┼─────────┼──────┼────────┼────────┼───────────┤
    │ LoomAI Asst  │ ✓       │ ✓    │ N/A    │ ✓      │ ✓         │
    │ OpenCode     │ ✓       │ ✓*   │ ✓      │ ✓      │ ✓         │
    │ Aider        │ ✓ proxy │ ✓**  │ —†     │ —†     │ ✓         │
    │ Claude Code  │ —‡      │ —‡   │ ✓      │ —†     │ ✓         │
    │ Crush        │ ✓       │ ✓    │ ✓      │ ✓      │ ✓         │
    │ Deep Agents  │ ✓       │ ✓    │ ✓      │ ✓      │ ✓         │
    └──────────────┴─────────┴──────┴────────┴────────┴───────────┘
    * OpenCode accesses NRP via documented curl/CLI in AGENTS.md
    ** Aider routes through model proxy which serves both providers
    † Tool has no skills/agents system — uses AGENTS.md via read: config
    ‡ Claude Code uses its own Anthropic API; FABRIC via CLI/curl per preamble
    """
    from app.settings_manager import get_storage_dir as _storage
    home = os.path.expanduser("~")
    cwd = _storage() if os.path.isdir(_storage()) else home

    # --- Shared FABRIC context (AGENTS.md in workspace) ---
    agents_dst = os.path.join(cwd, "AGENTS.md")
    if os.path.isfile(_FABRIC_AI_MD_PATH):
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
    if os.path.isfile(src_claude_md):
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
            with open(os.path.join(home, ".opencode.json"), "w") as f:
                json.dump(write_cfg, f, indent=2)
            with open(os.path.join(cwd, "opencode.json"), "w") as f:
                json.dump(write_cfg, f, indent=2)
        except Exception as e:
            logger.warning("Could not seed OpenCode config: %s", e)

    # --- Aider: ~/.aider.conf.yml ---
    src_aider_conf = os.path.join(_AIDER_DEFAULTS_DIR, ".aider.conf.yml")
    if os.path.isfile(src_aider_conf):
        shutil.copy2(src_aider_conf, os.path.join(home, ".aider.conf.yml"))

    src_aider_ignore = os.path.join(_AIDER_DEFAULTS_DIR, ".aiderignore")
    if os.path.isfile(src_aider_ignore):
        shutil.copy2(src_aider_ignore, os.path.join(home, ".aiderignore"))
        shutil.copy2(src_aider_ignore, os.path.join(cwd, ".aiderignore"))

    # --- Crush: ~/.config/crush/crush.json ---
    if api_key:
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

    # --- Git setup (needed by Aider, OpenCode, Crush, Deep Agents) ---
    _ensure_git_ready(cwd)

    logger.info("AI tool defaults seeded to home=%s, workspace=%s", home, cwd)


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

            with open(os.path.join(home, ".opencode.json"), "w") as f:
                json.dump(write_cfg, f, indent=2)
            with open(os.path.join(cwd, "opencode.json"), "w") as f:
                json.dump(write_cfg, f, indent=2)
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
            shutil.copy2(src_aider_conf, os.path.join(home, ".aider.conf.yml"))
        src_aider_ignore = os.path.join(_AIDER_DEFAULTS_DIR, ".aiderignore")
        if os.path.isfile(src_aider_ignore):
            shutil.copy2(src_aider_ignore, os.path.join(home, ".aiderignore"))
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
            os.makedirs(crush_global_dir, exist_ok=True)
            crush_workspace = os.path.join(cwd, ".crush.json")
            if os.path.isfile(crush_workspace):
                shutil.copy2(crush_workspace, os.path.join(crush_global_dir, "crush.json"))
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


@router.post("/api/ai/propagate-config")
async def propagate_config_endpoint():
    """Manually trigger AI config propagation to all tool workspaces.

    Re-generates workspace configuration files for all AI tools (OpenCode,
    Aider, Claude Code, Crush, Deep Agents, Jupyter AI) using the current
    settings.  Useful after changing API keys or server URLs.
    """
    results = propagate_ai_configs()
    return {"status": "ok", "tools": results}


def _read_master(fd: int) -> str:
    """Read available data from a PTY master fd."""
    try:
        data = os.read(fd, 4096)
        return data.decode("utf-8", errors="replace") if data else ""
    except OSError:
        return ""
