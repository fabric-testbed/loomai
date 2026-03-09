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

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.routes.config import _get_ai_api_key, _get_nrp_api_key

logger = logging.getLogger(__name__)

router = APIRouter()

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


def _fetch_models(api_key: str) -> list[str]:
    """Query the FABRIC AI server for available model IDs."""
    url = f"{AI_SERVER_URL}/v1/models"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key}",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
        return [m["id"] for m in body.get("data", [])]
    except Exception as e:
        logger.warning("Could not fetch models from %s: %s", url, e)
        return []


def _fetch_nrp_models(api_key: str) -> list[str]:
    """Query the NRP LLM server for available model IDs."""
    url = f"{NRP_SERVER_URL}/v1/models"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key}",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
        return [m["id"] for m in body.get("data", [])]
    except Exception as e:
        logger.warning("Could not fetch models from %s: %s", url, e)
        return []


def _pick_model(models: list[str], preferences: list[str], fallback: str) -> str:
    """Pick the best model from available list using preference order."""
    for pref in preferences:
        for m in models:
            if pref in m.lower():
                return m
    return models[0] if models else fallback


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
        logger.info("Available models from %s: %s", AI_SERVER_URL, models)
        default = _pick_model(models, _PREFERRED_MODELS, "qwen3-coder-30b")

    small = _pick_model(models, _PREFERRED_SMALL, default) if models else default

    # Build models dict — each available model gets an entry
    models_dict = {}
    for m in (models if models else [default]):
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
                "baseURL": f"{AI_SERVER_URL}/v1",
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
            nrp_models_dict = {m: {"name": m} for m in nrp_models}
            providers["nrp"] = {
                "npm": "@ai-sdk/openai-compatible",
                "name": "NRP",
                "options": {
                    "baseURL": f"{NRP_SERVER_URL}/v1",
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
        "_allowed": models if models else [default],
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
_MODEL_PROXY_PORT = 9199

# Paths to AI tool assets (inside the container)
_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_AI_TOOLS_DIR = os.path.join(_APP_ROOT, "ai-tools")
_FABRIC_AI_MD_PATH = os.path.join(_AI_TOOLS_DIR, "shared", "FABRIC_AI.md")
_OPENCODE_DEFAULTS_DIR = os.path.join(_AI_TOOLS_DIR, "opencode")
_AIDER_DEFAULTS_DIR = os.path.join(_AI_TOOLS_DIR, "aider")
_CLAUDE_DEFAULTS_DIR = os.path.join(_AI_TOOLS_DIR, "claude-code")
_CRUSH_DEFAULTS_DIR = os.path.join(_AI_TOOLS_DIR, "crush")

# Skills to skip (conflict with OpenCode builtins)
_SKIP_SKILLS = {"compact", "help"}


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
    agents_md = os.path.join(cwd, "AGENTS.md")
    if os.path.isfile(_FABRIC_AI_MD_PATH):
        shutil.copy2(_FABRIC_AI_MD_PATH, agents_md)
        logger.info("Wrote AGENTS.md from FABRIC_AI.md")

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
    """
    # Shared FABRIC context
    agents_md = os.path.join(cwd, "AGENTS.md")
    if os.path.isfile(_FABRIC_AI_MD_PATH) and not os.path.isfile(agents_md):
        shutil.copy2(_FABRIC_AI_MD_PATH, agents_md)
        logger.info("Wrote AGENTS.md for Aider from FABRIC_AI.md")

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
    """
    # Shared FABRIC context
    agents_md = os.path.join(cwd, "AGENTS.md")
    if os.path.isfile(_FABRIC_AI_MD_PATH) and not os.path.isfile(agents_md):
        shutil.copy2(_FABRIC_AI_MD_PATH, agents_md)
        logger.info("Wrote AGENTS.md for Claude Code from FABRIC_AI.md")

    # Claude Code project instructions
    src_claude = os.path.join(_CLAUDE_DEFAULTS_DIR, "CLAUDE.md")
    if os.path.isfile(src_claude):
        dst_claude = os.path.join(cwd, "CLAUDE.md")
        shutil.copy2(src_claude, dst_claude)
        logger.info("Wrote CLAUDE.md for Claude Code CLI")


def _setup_crush_workspace(cwd: str, api_key: str) -> None:
    """Seed Crush configuration and FABRIC context into the workspace.

    Creates:
    - AGENTS.md (shared FABRIC context)
    - .crush.json with FABRIC and NRP LLM providers configured
    """
    # Shared FABRIC context
    agents_md = os.path.join(cwd, "AGENTS.md")
    if os.path.isfile(_FABRIC_AI_MD_PATH) and not os.path.isfile(agents_md):
        shutil.copy2(_FABRIC_AI_MD_PATH, agents_md)
        logger.info("Wrote AGENTS.md for Crush from FABRIC_AI.md")

    # Build .crush.json with FABRIC and NRP providers
    models = _fetch_models(api_key) if api_key else []
    default_model = _pick_model(models, _PREFERRED_MODELS, "qwen3-coder-30b") if models else "qwen3-coder-30b"

    fabric_models = [{"id": m, "name": m} for m in (models if models else [default_model])]

    providers: dict = {
        "fabric": {
            "id": "fabric",
            "base_url": f"{AI_SERVER_URL}/v1",
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
                "base_url": f"{NRP_SERVER_URL}/v1",
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


def _start_model_proxy(
    api_key: str, default_model: str, allowed_models: list[str], env: dict,
) -> subprocess.Popen | None:
    """Start the model-rewriting proxy as a background subprocess."""
    if not os.path.exists(_MODEL_PROXY_SCRIPT):
        logger.warning("Model proxy script not found: %s", _MODEL_PROXY_SCRIPT)
        return None

    allowed_csv = ",".join(allowed_models) if allowed_models else default_model
    cmd = [
        "python3", _MODEL_PROXY_SCRIPT,
        str(_MODEL_PROXY_PORT),
        f"{AI_SERVER_URL}/v1",
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
            proc.pid, _MODEL_PROXY_PORT, AI_SERVER_URL, default_model, allowed_csv,
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
            "OPENAI_API_BASE": "https://ai.fabric-testbed.net/v1",
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
            "OPENAI_BASE_URL": "https://ai.fabric-testbed.net/v1",
        },
        "cmd": ["opencode"],
        "needs_key": True,
    },
    "crush": {
        "env": lambda key: {
            "OPENAI_API_KEY": key,
            "OPENAI_BASE_URL": f"{AI_SERVER_URL}/v1",
        },
        "cmd": ["crush"],
        "needs_key": True,
    },
    "claude": {
        "env": lambda key: {},
        "cmd": ["claude"],
        "needs_key": False,
    },
}


_OPENCODE_WEB_PORT = 9198
_opencode_web_proc: subprocess.Popen | None = None
_opencode_web_proxy: subprocess.Popen | None = None


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

    cwd = "/home/fabric/work" if os.path.isdir("/home/fabric/work") else os.path.expanduser("~")
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
        "OPENAI_BASE_URL": f"{AI_SERVER_URL}/v1",
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
        tool_env["OPENAI_BASE_URL"] = f"http://127.0.0.1:{_MODEL_PROXY_PORT}/v1"

    cmd = [
        "opencode", "web",
        "--port", str(_OPENCODE_WEB_PORT),
        "--hostname", "0.0.0.0",
    ]
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

    cwd = "/home/fabric/work" if os.path.isdir("/home/fabric/work") else os.path.expanduser("~")
    _ensure_git_ready(cwd)
    _setup_aider_workspace(cwd)

    if not model:
        models = _fetch_models(api_key)
        model = _pick_model(models, _PREFERRED_MODELS, "qwen3-coder-30b")

    tool_env = {
        **os.environ,
        "OPENAI_API_KEY": api_key,
        "OPENAI_API_BASE": f"{AI_SERVER_URL}/v1",
    }

    cmd = [
        "aider", "--gui",
        "--model", f"openai/{model}",
        "--no-auto-lint",
        "--no-auto-test",
        "--no-git-commit-verify",
    ]
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


@router.get("/api/ai/models")
async def list_ai_models():
    """Return available models from the FABRIC AI server and NRP."""
    api_key = _get_ai_api_key()
    if not api_key:
        return {"models": [], "default": "", "error": "AI API key not configured"}
    models = _fetch_models(api_key)
    default = _pick_model(models, _PREFERRED_MODELS, "qwen3-coder-30b") if models else "qwen3-coder-30b"

    # Include NRP models if key is available
    nrp_models: list[str] = []
    nrp_key = _get_nrp_api_key()
    if nrp_key:
        nrp_models = _fetch_nrp_models(nrp_key)

    return {"models": models, "default": default, "nrp_models": nrp_models}


@router.websocket("/ws/terminal/ai/{tool}")
async def ai_terminal_ws(websocket: WebSocket, tool: str, model: str = ""):
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

        cwd = "/home/fabric/work" if os.path.isdir("/home/fabric/work") else os.path.expanduser("~")

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
            _setup_crush_workspace(cwd, api_key)

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
                    tool_env["OPENAI_BASE_URL"] = f"http://127.0.0.1:{_MODEL_PROXY_PORT}/v1"
            except OSError:
                pass

        proc = subprocess.Popen(
            config["cmd"],
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


def seed_ai_tool_defaults() -> None:
    """Seed AI tool configs into their default locations at container startup.

    Places configuration files where each tool expects to find them by default:
    - Claude Code: ~/.claude/CLAUDE.md, ~/.claude/settings.json, <cwd>/.mcp.json
    - OpenCode:    ~/.opencode.json, <cwd>/.opencode/ (skills, agents)
    - Aider:       ~/.aider.conf.yml, ~/.aiderignore
    - Crush:       ~/.config/crush/crush.json
    - All tools:   <cwd>/AGENTS.md (shared FABRIC context)
    """
    home = os.path.expanduser("~")
    cwd = "/home/fabric/work" if os.path.isdir("/home/fabric/work") else home

    # --- Shared FABRIC context (AGENTS.md in workspace) ---
    agents_dst = os.path.join(cwd, "AGENTS.md")
    if os.path.isfile(_FABRIC_AI_MD_PATH):
        shutil.copy2(_FABRIC_AI_MD_PATH, agents_dst)

    # --- Claude Code: ~/.claude/CLAUDE.md + ~/.claude/settings.json + .mcp.json ---
    claude_dir = os.path.join(home, ".claude")
    os.makedirs(claude_dir, exist_ok=True)

    src_claude_md = os.path.join(_CLAUDE_DEFAULTS_DIR, "CLAUDE.md")
    if os.path.isfile(src_claude_md):
        shutil.copy2(src_claude_md, os.path.join(claude_dir, "CLAUDE.md"))

    # settings.json — empty if not present
    settings_path = os.path.join(claude_dir, "settings.json")
    if not os.path.isfile(settings_path):
        with open(settings_path, "w") as f:
            json.dump({}, f)

    # .mcp.json in workspace — MCP servers for FABRIC API
    from app.user_context import get_token_path as _gtp
    token_file = _gtp()
    # .mcp.json in workspace — only fabric-reports MCP. fabric-api MCP is
    # intentionally excluded: in-container tools should use FABlib directly.
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

    # Also write CLAUDE.md to the workspace for project-level instructions
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

    # --- Git setup (needed by Aider, OpenCode, Crush) ---
    _ensure_git_ready(cwd)

    logger.info("AI tool defaults seeded to home=%s, workspace=%s", home, cwd)


def _read_master(fd: int) -> str:
    """Read available data from a PTY master fd."""
    try:
        data = os.read(fd, 4096)
        return data.decode("utf-8", errors="replace") if data else ""
    except OSError:
        return ""
