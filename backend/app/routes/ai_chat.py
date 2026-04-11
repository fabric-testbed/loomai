"""Streaming agentic AI assistant — proxies to FABRIC LLMs with tool calling."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import traceback
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.http_pool import ai_client
from app.settings_manager import get_fabric_api_key as _get_ai_api_key, get_nrp_api_key as _get_nrp_api_key

logger = logging.getLogger(__name__)

router = APIRouter()

AI_SERVER_URL = "https://ai.fabric-testbed.net"  # Fallback; prefer _ai_server_url()

def _ai_server_url() -> str:
    from app.settings_manager import get_ai_server_url
    return get_ai_server_url()

def _nrp_server_url() -> str:
    from app.settings_manager import get_nrp_server_url
    return get_nrp_server_url()
_MAX_TOOL_ROUNDS = 30  # raised from 20 to absorb larger multi-file project
                       # generation (e.g. a full weave with script+notebook+tuning+docs).
                       # Worst-case wall clock on qwen3-coder-30b at ~25s/round is ~12.5
                       # min; if users exceed this they see the Continue button and can
                       # extend the session.

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_AI_TOOLS_DIR = os.path.join(_APP_ROOT, "ai-tools")
_FABRIC_AI_MD_PATH = os.path.join(_AI_TOOLS_DIR, "shared", "FABRIC_AI.md")
_AGENTS_DIR = os.path.join(_AI_TOOLS_DIR, "shared", "agents")

# FABlib API ground truth — authoritative method reference that lists real
# methods and common hallucinations. Injected into the system prompt on
# weave/slice-mutation requests to prevent qwen3-coder from inventing
# non-existent FABlib methods (verified hallucination issue from live probes).
_FABLIB_REF_PATH = os.path.join(
    _AI_TOOLS_DIR, "fablib-examples", "experiments", "fablib_api_reference.py"
)
_fablib_ref_cache: str | None = None


def _load_fablib_ref() -> str:
    """Return the FABlib API reference file content (cached in memory)."""
    global _fablib_ref_cache
    if _fablib_ref_cache is None:
        try:
            with open(_FABLIB_REF_PATH) as f:
                _fablib_ref_cache = f.read()
        except OSError:
            _fablib_ref_cache = ""
    return _fablib_ref_cache

# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------
_system_prompt_cache: str | None = None
_agents_cache: dict[str, dict] | None = None


def invalidate_agents_cache() -> None:
    """Clear the agents cache so the next load picks up changes."""
    global _agents_cache
    _agents_cache = None


def _load_system_prompt() -> str:
    global _system_prompt_cache
    if _system_prompt_cache is None:
        try:
            with open(_FABRIC_AI_MD_PATH, "r") as f:
                _system_prompt_cache = f.read()
        except Exception:
            _system_prompt_cache = "You are a helpful FABRIC testbed assistant."
    return _system_prompt_cache


def _parse_agent_file(fpath: str) -> dict[str, str] | None:
    """Parse a single agent .md file into {name, description, prompt}."""
    try:
        with open(fpath, "r") as f:
            content = f.read()
        if not content.startswith("name:"):
            return None
        parts = content.split("---", 1)
        header = parts[0]
        body = parts[1].strip() if len(parts) > 1 else ""
        name = desc = ""
        for line in header.strip().splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("description:"):
                desc = line.split(":", 1)[1].strip()
        return {"name": name, "description": desc, "prompt": body}
    except Exception:
        return None


def _load_agents() -> dict[str, dict]:
    """Load agents from built-in dir, then overlay user-custom agents on top."""
    global _agents_cache
    if _agents_cache is not None:
        return _agents_cache

    agents: dict[str, dict] = {}

    # 1. Load built-in agents
    if os.path.isdir(_AGENTS_DIR):
        for fname in sorted(os.listdir(_AGENTS_DIR)):
            if not fname.endswith(".md"):
                continue
            agent_id = fname[:-3]
            if agent_id in ("ai-tools-evaluator",):
                continue
            parsed = _parse_agent_file(os.path.join(_AGENTS_DIR, fname))
            if parsed:
                agents[agent_id] = {"name": parsed["name"] or agent_id, "description": parsed["description"], "prompt": parsed["prompt"]}

    # 2. Overlay user-custom agents
    try:
        from app.settings_manager import get_storage_dir
        custom_dir = os.path.join(get_storage_dir(), ".loomai", "agents")
        if os.path.isdir(custom_dir):
            for fname in sorted(os.listdir(custom_dir)):
                if not fname.endswith(".md"):
                    continue
                agent_id = fname[:-3]
                if agent_id in ("ai-tools-evaluator",):
                    continue
                parsed = _parse_agent_file(os.path.join(custom_dir, fname))
                if parsed:
                    agents[agent_id] = {"name": parsed["name"] or agent_id, "description": parsed["description"], "prompt": parsed["prompt"]}
    except Exception:
        logger.warning("Failed to load custom agents", exc_info=True)

    _agents_cache = agents
    return agents


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_slices",
            "description": "List all FABRIC slices for the current user with their state, site, and node count.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_slice",
            "description": "Get detailed information about a specific slice including all nodes, networks, and interfaces.",
            "parameters": {
                "type": "object",
                "properties": {"slice_name": {"type": "string", "description": "Name of the slice"}},
                "required": ["slice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_sites",
            "description": "Query FABRIC sites and their available resources (cores, RAM, disk, GPUs). Returns live availability.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_site_hosts",
            "description": "Get detailed per-host resource availability for a specific site.",
            "parameters": {
                "type": "object",
                "properties": {"site_name": {"type": "string", "description": "FABRIC site name (e.g. RENC, UCSD)"}},
                "required": ["site_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_slice",
            "description": "Create a new empty draft slice.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Name for the new slice"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_node",
            "description": "Add a VM node to a draft slice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the draft slice"},
                    "node_name": {"type": "string", "description": "Name for the new node"},
                    "site": {"type": "string", "description": "FABRIC site name (e.g. RENC, UCSD)"},
                    "cores": {"type": "integer", "description": "Number of CPU cores (default 2)", "default": 2},
                    "ram": {"type": "integer", "description": "RAM in GB (default 8)", "default": 8},
                    "disk": {"type": "integer", "description": "Disk in GB (default 10)", "default": 10},
                    "image": {"type": "string", "description": "OS image (default: default_ubuntu_22)", "default": "default_ubuntu_22"},
                },
                "required": ["slice_name", "node_name", "site"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_component",
            "description": "Add a network component (NIC) to a node in a draft slice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the draft slice"},
                    "node_name": {"type": "string", "description": "Name of the node"},
                    "component_name": {"type": "string", "description": "Name for the component (e.g. nic1)"},
                    "model": {"type": "string", "description": "Component model: NIC_Basic, NIC_ConnectX_5, NIC_ConnectX_6, GPU_Tesla_T4, GPU_RTX6000, GPU_A30, GPU_A40, NVME_P4510, FPGA_Xilinx_U280"},
                },
                "required": ["slice_name", "node_name", "component_name", "model"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_fabnet",
            "description": (
                "Attach FABNetv4 or FABNetv6 to a single node in a draft slice. "
                "THIS IS THE CORRECT TOOL FOR MULTI-SITE FABNET CONNECTIVITY. "
                "Call once per node — FABRIC automatically creates a per-site "
                "network and routes between sites via its backbone. Handles "
                "NIC attachment, interface creation, and automatic IP assignment. "
                "Do NOT use add_network(type='FABNetv4') for multi-site — a single "
                "FABNetv4 network cannot span more than one site (FABRIC returns "
                "'Service cannot span N sites. Limit: 1.')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the draft slice"},
                    "node_name": {"type": "string", "description": "Name of the node to attach"},
                    "net_type": {
                        "type": "string",
                        "description": "Address family: IPv4 for FABNetv4, IPv6 for FABNetv6",
                        "enum": ["IPv4", "IPv6"],
                        "default": "IPv4",
                    },
                },
                "required": ["slice_name", "node_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_network",
            "description": "Add a network service to a draft slice and connect node interfaces to it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the draft slice"},
                    "network_name": {"type": "string", "description": "Name for the network"},
                    "type": {
                        "type": "string",
                        "description": "Network type",
                        "enum": ["L2Bridge", "L2PTP", "L2STS", "FABNetv4", "FABNetv6", "FABNetv4Ext", "FABNetv6Ext", "PortMirror"],
                    },
                    "interfaces": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of interface names to connect (format: nodeName-componentName-pN, e.g. node1-nic1-p1)",
                    },
                },
                "required": ["slice_name", "network_name", "type", "interfaces"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_slice",
            "description": "Submit a draft slice to FABRIC for provisioning.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice to submit"},
                    "wait": {"type": "boolean", "description": "Wait for provisioning to complete (True for <=3 nodes)", "default": False},
                },
                "required": ["slice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_slice",
            "description": "Delete a FABRIC slice.",
            "parameters": {
                "type": "object",
                "properties": {"slice_name": {"type": "string", "description": "Name of the slice to delete"}},
                "required": ["slice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "renew_slice",
            "description": "Extend a slice's expiration by a number of days.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice to renew"},
                    "days": {"type": "integer", "description": "Number of days to extend", "default": 7},
                },
                "required": ["slice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_templates",
            "description": "List available weaves that can be loaded as new slices.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_template",
            "description": "Load a weave as a new draft slice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "template_name": {"type": "string", "description": "Name (dir_name) of the template to load"},
                    "slice_name": {"type": "string", "description": "Name for the new slice created from the template"},
                },
                "required": ["template_name", "slice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_as_template",
            "description": "Save a slice as a reusable template.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice to save as template"},
                    "template_name": {"type": "string", "description": "Name for the template"},
                    "description": {"type": "string", "description": "Description of the template"},
                },
                "required": ["slice_name", "template_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_node",
            "description": "Remove a node from a draft slice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the draft slice"},
                    "node_name": {"type": "string", "description": "Name of the node to remove"},
                },
                "required": ["slice_name", "node_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_network",
            "description": "Remove a network from a draft slice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the draft slice"},
                    "network_name": {"type": "string", "description": "Name of the network to remove"},
                },
                "required": ["slice_name", "network_name"],
            },
        },
    },
    # --- File Operations (container filesystem) ---
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file on the container filesystem. Creates parent directories as needed. Use for creating artifacts, scripts, config files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within user storage (e.g. 'my_artifacts/my_weave/weave.sh')"},
                    "content": {"type": "string", "description": "File content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the content of a file on the container filesystem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within user storage"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories at a path on the container filesystem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within user storage (empty string for root)", "default": ""},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "Create a directory on the container filesystem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path for the new directory within user storage"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_path",
            "description": "Delete a file or directory on the container filesystem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within user storage to delete"},
                },
                "required": ["path"],
            },
        },
    },
    # --- Artifact Management ---
    {
        "type": "function",
        "function": {
            "name": "list_artifacts",
            "description": "List all local artifacts (weaves, VM templates, recipes, notebooks) in the user's artifact directory.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "publish_artifact",
            "description": "Publish a local artifact to the FABRIC Artifact Manager marketplace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_name": {"type": "string", "description": "Directory name of the local artifact to publish"},
                    "title": {"type": "string", "description": "Human-readable title for the artifact"},
                    "description": {"type": "string", "description": "Description of the artifact", "default": ""},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for discovery (e.g. ['networking', 'L2'])", "default": []},
                    "visibility": {"type": "string", "enum": ["author", "project", "public"], "description": "Who can see the artifact (default: author)", "default": "author"},
                },
                "required": ["dir_name", "title"],
            },
        },
    },
    # --- Slice Operations ---
    {
        "type": "function",
        "function": {
            "name": "refresh_slice",
            "description": "Refresh a slice's state from FABRIC. Updates node states, IPs, and other runtime info.",
            "parameters": {
                "type": "object",
                "properties": {"slice_name": {"type": "string", "description": "Name of the slice to refresh"}},
                "required": ["slice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_slice",
            "description": "Validate a slice topology for issues (errors, warnings) before submission.",
            "parameters": {
                "type": "object",
                "properties": {"slice_name": {"type": "string", "description": "Name of the slice to validate"}},
                "required": ["slice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_node",
            "description": "Update properties of a node in a draft slice (site, cores, RAM, disk, image).",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the draft slice"},
                    "node_name": {"type": "string", "description": "Name of the node to update"},
                    "site": {"type": "string", "description": "New site assignment"},
                    "cores": {"type": "integer", "description": "New CPU core count"},
                    "ram": {"type": "integer", "description": "New RAM in GB"},
                    "disk": {"type": "integer", "description": "New disk in GB"},
                    "image": {"type": "string", "description": "New OS image name"},
                },
                "required": ["slice_name", "node_name"],
            },
        },
    },
    # --- VM Operations (SSH) ---
    {
        "type": "function",
        "function": {
            "name": "ssh_execute",
            "description": (
                "Execute a command on a VM node via SSH. The slice must be in "
                "StableOK state. Default timeout is 600s (10 min) which covers "
                "apt update + apt install of ~20 packages. For very long "
                "operations (kernel upgrade, large package sets, docker pulls), "
                "set timeout up to 1800s (30 min)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice"},
                    "node_name": {"type": "string", "description": "Name of the node"},
                    "command": {"type": "string", "description": "Shell command to execute on the VM. For non-interactive apt use DEBIAN_FRONTEND=noninteractive and apt-get -y -qq."},
                    "timeout": {"type": "integer", "description": "Command timeout in seconds (default 600, max 1800)", "default": 600},
                },
                "required": ["slice_name", "node_name", "command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reboot_and_wait",
            "description": (
                "Reboot a VM node and wait for SSH to become reachable again. "
                "Use this in 'reboot if needed' workflows: first check "
                "`test -f /var/run/reboot-required` with ssh_execute; if "
                "present, call this tool, then continue with post-reboot steps. "
                "Returns status 'reachable' with elapsed seconds, or "
                "'unreachable' if the node doesn't come back within the "
                "timeout (default 300s, max 1500s). Safe to call per-node in "
                "multi-node workflows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice"},
                    "node_name": {"type": "string", "description": "Name of the node to reboot"},
                    "timeout": {
                        "type": "integer",
                        "description": "Max seconds to wait for SSH to return (default 300, max 1500)",
                        "default": 300,
                    },
                },
                "required": ["slice_name", "node_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_vm_file",
            "description": "Write content to a file on a VM node via SFTP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice"},
                    "node_name": {"type": "string", "description": "Name of the node"},
                    "path": {"type": "string", "description": "Absolute path on the VM (e.g. /home/ubuntu/script.sh)"},
                    "content": {"type": "string", "description": "File content to write"},
                },
                "required": ["slice_name", "node_name", "path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_vm_file",
            "description": "Read a file from a VM node via SFTP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice"},
                    "node_name": {"type": "string", "description": "Name of the node"},
                    "path": {"type": "string", "description": "Absolute path on the VM to read"},
                },
                "required": ["slice_name", "node_name", "path"],
            },
        },
    },
    # --- Recipe Operations ---
    {
        "type": "function",
        "function": {
            "name": "list_recipes",
            "description": "List available VM recipes that can be applied to running nodes.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    # --- JupyterLab ---
    {
        "type": "function",
        "function": {
            "name": "manage_jupyter",
            "description": "Start, stop, or check status of the JupyterLab environment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["start", "stop", "status"], "description": "Action to perform on JupyterLab"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the internet using DuckDuckGo. Returns titles, URLs, and snippets for each result. Use this to find documentation, tutorials, troubleshooting guides, or any information from the web.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query string"},
                    "max_results": {"type": "integer", "description": "Maximum number of results to return (default 5, max 10)", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": "Fetch and extract the main text content from a webpage URL. Use this after web_search to read the full content of a promising result. Returns plain text (HTML tags stripped).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch"},
                    "max_length": {"type": "integer", "description": "Maximum characters to return (default 4000)", "default": 4000},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_background_run",
            "description": "Start a weave script as a background run that survives browser disconnects. Returns a run_id for polling status and output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "weave_dir_name": {"type": "string", "description": "Directory name of the weave (e.g. 'My_Weave')"},
                    "script": {"type": "string", "description": "Script to run (default 'auto' resolves from weave.json)", "default": "auto"},
                    "slice_name": {"type": "string", "description": "Slice name to pass to the script (optional)", "default": ""},
                },
                "required": ["weave_dir_name", "script"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_background_runs",
            "description": "List all background runs (active and completed) with their status, timestamps, and weave info.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_background_run_output",
            "description": "Get output from a background run. Pass offset=0 for all output, or the last offset for incremental reads.",
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "string", "description": "The run ID returned by start_background_run"},
                    "offset": {"type": "integer", "description": "Byte offset to read from (0 for all output)", "default": 0},
                },
                "required": ["run_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_background_run",
            "description": "Stop a running background run.",
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "string", "description": "The run ID to stop"},
                },
                "required": ["run_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_weave",
            "description": "Create a new weave experiment. YOU MUST provide script_content with a complete Python script that uses FABlib to create, provision, and configure the slice. The script must have start(slice_name), stop(slice_name), and monitor(slice_name) functions. Include exactly as many VMs, networks, components (GPUs, SmartNICs, etc.), and software installs as the experiment requires. Use node.execute() to install software and run experiments after provisioning. If you omit script_content, a basic template is generated.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Weave name (used as directory name)"},
                    "description": {"type": "string", "description": "What this weave does (1-2 sentences)"},
                    "num_nodes": {"type": "integer", "description": "Number of VMs (fallback if no script_content)", "default": 2},
                    "site": {"type": "string", "description": "FABRIC site or 'auto' (fallback if no script_content)", "default": "auto"},
                    "network_type": {"type": "string", "description": "Network type (fallback if no script_content): 'L2Bridge' or 'FABNetv4'", "default": "L2Bridge"},
                    "script_content": {"type": "string", "description": "REQUIRED: Complete Python experiment script with start/stop/monitor functions using FABlib. Create the right number of nodes, networks, and components for the experiment. Install software via node.execute(). See FABRIC_AI.md for FABlib API examples."},
                    "include_notebooks": {"type": "boolean", "description": "Include Jupyter notebook (default: true)", "default": True},
                    "include_node_tools": {"type": "boolean", "description": "Include node setup scripts (default: false)", "default": False},
                    "include_data_folder": {"type": "boolean", "description": "Include data/ folder (default: false)", "default": False},
                    "node_tools_content": {"type": "string", "description": "Shell script content for node setup (e.g. 'sudo apt install iperf3')"},
                    "notebook_description": {"type": "string", "description": "What the notebook should cover"},
                    "weave_md": {"type": "string", "description": "Custom weave.md spec content (leave empty to auto-generate)"},
                },
                "required": ["name", "script_content"],
            },
        },
    },
    # --- Chameleon Cloud tools ---
    {
        "type": "function",
        "function": {
            "name": "list_chameleon_leases",
            "description": "List Chameleon Cloud leases (reservations) with status, site, and dates. Optionally filter by site.",
            "parameters": {
                "type": "object",
                "properties": {"site": {"type": "string", "description": "Chameleon site (e.g. CHI@TACC, CHI@UC). Omit to list all."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_chameleon_instances",
            "description": "List running Chameleon Cloud instances (servers) with status, IP, and site.",
            "parameters": {
                "type": "object",
                "properties": {"site": {"type": "string", "description": "Chameleon site to query. Omit for all sites."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_chameleon_sites",
            "description": "List Chameleon Cloud sites (CHI@TACC, CHI@UC, etc.) with configuration status and location.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "chameleon_site_images",
            "description": "List available OS images at a Chameleon site.",
            "parameters": {
                "type": "object",
                "properties": {"site": {"type": "string", "description": "Chameleon site (e.g. CHI@TACC)"}},
                "required": ["site"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_chameleon_lease",
            "description": "Create a new Chameleon lease (reservation) for bare-metal nodes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "site": {"type": "string", "description": "Chameleon site (e.g. CHI@TACC)"},
                    "name": {"type": "string", "description": "Lease name"},
                    "node_type": {"type": "string", "description": "Node type (e.g. compute_haswell, gpu_p100)"},
                    "node_count": {"type": "integer", "description": "Number of nodes", "default": 1},
                    "duration_hours": {"type": "integer", "description": "Duration in hours", "default": 4},
                },
                "required": ["site", "name", "node_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_chameleon_lease",
            "description": "Delete a Chameleon lease.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lease_id": {"type": "string", "description": "Lease ID to delete"},
                    "site": {"type": "string", "description": "Chameleon site"},
                },
                "required": ["lease_id", "site"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_chameleon_instance",
            "description": "Launch a Chameleon instance (server) on an existing lease.",
            "parameters": {
                "type": "object",
                "properties": {
                    "site": {"type": "string", "description": "Chameleon site"},
                    "name": {"type": "string", "description": "Instance name"},
                    "lease_id": {"type": "string", "description": "Lease ID to use"},
                    "reservation_id": {"type": "string", "description": "Reservation ID from the lease"},
                    "image_id": {"type": "string", "description": "OS image ID or name (e.g. CC-Ubuntu22.04)"},
                },
                "required": ["site", "name", "image_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_chameleon_instance",
            "description": "Terminate a Chameleon instance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instance_id": {"type": "string", "description": "Instance ID to terminate"},
                    "site": {"type": "string", "description": "Chameleon site"},
                },
                "required": ["instance_id", "site"],
            },
        },
    },
    # --- Chameleon Slice tools (LoomAI abstraction) ---
    {
        "type": "function",
        "function": {
            "name": "list_chameleon_slices",
            "description": "List Chameleon slices (LoomAI's grouping of Chameleon servers). Each slice groups bare-metal instances into a logical experiment unit.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deploy_chameleon_slice",
            "description": "Deploy a Chameleon slice draft — creates leases, launches instances, configures networking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string", "description": "Draft ID to deploy"},
                    "hours": {"type": "integer", "description": "Lease duration in hours", "default": 4},
                },
                "required": ["draft_id"],
            },
        },
    },
    # --- Composite slice tools (cross-testbed) ---
    {
        "type": "function",
        "function": {
            "name": "list_composite_slices",
            "description": "List composite slices — cross-testbed meta-slices that group FABRIC and Chameleon slices together.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_composite_slice",
            "description": "Get details of a composite slice including its FABRIC and Chameleon member slices.",
            "parameters": {
                "type": "object",
                "properties": {"slice_id": {"type": "string", "description": "Composite slice ID"}},
                "required": ["slice_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_composite_slice",
            "description": "Create a new composite slice (cross-testbed meta-slice) to group FABRIC and Chameleon slices together.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Name for the composite slice"}},
                "required": ["name"],
            },
        },
    },
    # --- FABlib examples RAG ---
    {
        "type": "function",
        "function": {
            "name": "search_examples",
            "description": "Search FABlib code examples by keyword. Returns matching examples with their full source code included. Do NOT call read_file on the results — the code is already in the response. Examples: 'fabnetv4', 'gpu', 'l2 network', 'weave lifecycle', 'iperf'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords (e.g. 'fabnetv4 cross-site', 'gpu rtx6000', 'l2 bridge network')"},
                },
                "required": ["query"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution — calls existing backend functions
# ---------------------------------------------------------------------------

def _run_sync(func, *args, **kwargs) -> Any:
    """Run a sync function and return its result (for use in async context)."""
    return func(*args, **kwargs)


# FABlib examples index (loaded once, cached)
_examples_index: list[dict] | None = None

def _load_examples_index() -> list[dict]:
    """Load the FABlib examples index from disk."""
    global _examples_index
    if _examples_index is not None:
        return _examples_index
    index_path = os.path.join(_APP_ROOT, "ai-tools", "fablib-examples", "INDEX.json")
    if not os.path.isfile(index_path):
        _examples_index = []
        return _examples_index
    with open(index_path) as f:
        _examples_index = json.load(f)
    return _examples_index


async def _search_examples(query: str) -> str:
    """Search FABlib examples by keyword matching on title, tags, and description."""
    index = _load_examples_index()
    if not index:
        return json.dumps({"results": [], "note": "No examples index found"})

    keywords = query.lower().split()
    scored: list[tuple[int, dict]] = []

    for entry in index:
        score = 0
        searchable = f"{entry.get('title', '')} {' '.join(entry.get('tags', []))} {entry.get('description', '')}".lower()
        for kw in keywords:
            if kw in searchable:
                score += 1
            # Bonus for tag match (more specific)
            if kw in [t.lower() for t in entry.get('tags', [])]:
                score += 1
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: -x[0])

    examples_dir = os.path.join(_APP_ROOT, "ai-tools", "fablib-examples")
    results = []
    total_content_chars = 0
    content_budget = 5000  # Total chars for all inline content

    for score, entry in scored:
        item = {
            "file": entry["file"],
            "title": entry["title"],
            "description": entry["description"],
            "tags": entry.get("tags", []),
        }
        # Include file content for top results that fit in the budget
        if total_content_chars < content_budget:
            fpath = os.path.join(examples_dir, entry["file"])
            if os.path.isfile(fpath):
                try:
                    with open(fpath) as ef:
                        content = ef.read()
                    remaining = content_budget - total_content_chars
                    if len(content) > remaining:
                        content = content[:remaining] + "\n# ... (truncated)"
                    item["content"] = content
                    total_content_chars += len(content)
                except Exception:
                    pass
        results.append(item)
        if len(results) >= 8:
            break

    total = len(scored)
    note = f"Found {total} examples, showing top {len(results)}"
    return json.dumps({"query": query, "results": results, "note": note})


async def _create_weave_tool(args: dict) -> str:
    """Create a complete weave directory with all required files."""
    from app.user_context import get_user_storage
    import re

    name = args["name"]
    description = args.get("description", "") or f"FABRIC experiment: {name}"
    script_content = args.get("script_content", "")
    num_nodes = args.get("num_nodes", 2)
    site = args.get("site", "auto")
    network_type = args.get("network_type", "L2Bridge")

    # Sanitize name for directory
    dir_name = re.sub(r'[^\w\-]', '_', name).strip('_')
    if not dir_name:
        return json.dumps({"error": "Invalid weave name"})

    base = get_user_storage()
    weave_dir = os.path.join(base, "my_artifacts", dir_name)
    if os.path.exists(weave_dir):
        return json.dumps({"error": f"Weave '{dir_name}' already exists"})

    os.makedirs(weave_dir, exist_ok=True)
    created_files = []

    # weave.json
    py_name = re.sub(r'[^\w]', '_', name.lower()).strip('_')
    weave_config = {
        "run_script": "weave.sh",
        "log_file": "weave.log",
        "name": name,
        "description": description,
        "category": "weave",
        "args": [
            {"name": "SLICE_NAME", "label": "Slice Name", "type": "string",
             "required": True, "default": dir_name.lower().replace('_', '-'),
             "description": "Name for the FABRIC slice"},
        ],
    }
    with open(os.path.join(weave_dir, "weave.json"), "w") as f:
        json.dump(weave_config, f, indent=2)
    created_files.append("weave.json")

    # weave.sh — standard orchestrator
    weave_sh = f'''#!/bin/bash
set -e

SLICE_NAME="${{SLICE_NAME:-{dir_name.lower().replace('_', '-')}}}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cleanup() {{
    echo "### PROGRESS: Stopping experiment..."
    python3 "$SCRIPT_DIR/{py_name}.py" stop "$SLICE_NAME"
    echo "### PROGRESS: Cleanup complete"
    exit 0
}}
trap cleanup SIGTERM SIGINT

echo "### PROGRESS: Starting experiment '$SLICE_NAME'..."
python3 "$SCRIPT_DIR/{py_name}.py" start "$SLICE_NAME"

echo "### PROGRESS: Experiment running. Monitoring..."
while true; do
    python3 "$SCRIPT_DIR/{py_name}.py" monitor "$SLICE_NAME"
    if [ $? -ne 0 ]; then
        echo "### PROGRESS: Monitor detected an issue, stopping..."
        cleanup
    fi
    sleep 30 &
    wait $!
done
'''
    with open(os.path.join(weave_dir, "weave.sh"), "w") as f:
        f.write(weave_sh)
    os.chmod(os.path.join(weave_dir, "weave.sh"), 0o755)
    created_files.append("weave.sh")

    # Python experiment script — uses num_nodes, site, and network_type
    if not script_content:
        slice_default = dir_name.lower().replace('_', '-')
        site_arg = f'"{site}"' if site and site != "auto" else "None"

        # Build node creation code
        node_lines = []
        nic_lines = []
        for i in range(1, num_nodes + 1):
            node_lines.append(
                f'    node{i} = slice_obj.add_node(name="node{i}", site={site_arg}, cores=2, ram=8, disk=10, image="default_ubuntu_22")'
            )
            if num_nodes >= 2 and network_type:
                nic_lines.append(f'    iface{i} = node{i}.add_component(model="NIC_Basic", name="nic1").get_interfaces()[0]')

        nodes_code = "\n".join(node_lines)
        nics_code = "\n".join(nic_lines) if nic_lines else ""

        # Build network code
        net_code = ""
        if num_nodes >= 2 and network_type:
            iface_list = ", ".join(f"iface{i}" for i in range(1, num_nodes + 1))
            if network_type in ("FABNetv4", "IPv4"):
                net_code = f'    slice_obj.add_l3network(name="net1", interfaces=[{iface_list}], type="IPv4")'
            else:
                net_code = f'    slice_obj.add_l2network(name="net1", interfaces=[{iface_list}], type="{network_type}")'

        total_steps = 3 if num_nodes == 1 else 4
        step = 1

        script_content = f'''#!/usr/bin/env python3
"""
{name} — FABRIC Experiment Lifecycle Script

{num_nodes}-node FABRIC slice managed with the FABlib Python API.
Edit this file to customize the topology, add nodes, networks, and software.

Usage:
  python3 {py_name}.py start <slice-name>   # Create and provision
  python3 {py_name}.py stop  <slice-name>   # Tear down
  python3 {py_name}.py monitor <slice-name> # Health check

FABlib docs: https://fabric-testbed.github.io/fabrictestbed-extensions/
"""

import sys


def start(slice_name: str):
    """Create and provision a {num_nodes}-node FABRIC slice."""
    from fabrictestbed_extensions.fablib.fablib import FablibManager
    fablib = FablibManager()

    print(f"### PROGRESS: Step {step}/{total_steps} — Creating slice '{{slice_name}}'...")
    slice_obj = fablib.new_slice(name=slice_name)

    # Add {num_nodes} node{"s" if num_nodes > 1 else ""}
{nodes_code}
'''
        if nics_code:
            step2 = step + 1
            script_content += f'''
    # Add NICs and network
    print("### PROGRESS: Step {step2}/{total_steps} — Adding network...")
{nics_code}
{net_code}
'''

        submit_step = total_steps - 1
        ssh_step = total_steps
        script_content += f'''
    # Submit and wait
    print("### PROGRESS: Step {submit_step}/{total_steps} — Submitting slice (3-5 minutes)...")
    slice_obj.submit()
    print("### PROGRESS: Step {ssh_step}/{total_steps} — Waiting for SSH access...")
    slice_obj.wait_ssh(progress=True)

    # Re-fetch slice — node objects from add_node() go stale after submit
    slice_obj = fablib.get_slice(name=slice_name)

    # Configure networking
    slice_obj.post_boot_config()

    print()
    print(f"### PROGRESS: READY! Slice '{{slice_name}}' is provisioned.")
    for n in slice_obj.get_nodes():
        print(f"  {{n.get_name()}}: {{n.get_management_ip()}} ({{n.get_site()}})")
    print()
    print("  SSH: ssh -F /home/fabric/work/fabric_config/ssh_config <management_ip>")


def stop(slice_name: str):
    """Delete the slice and free all FABRIC resources."""
    from fabrictestbed_extensions.fablib.fablib import FablibManager
    fablib = FablibManager()
    print(f"### PROGRESS: Deleting slice '{{slice_name}}'...")
    try:
        slice_obj = fablib.get_slice(name=slice_name)
        slice_obj.delete()
        print("### PROGRESS: Slice deleted.")
    except Exception as e:
        print(f"### PROGRESS: Could not delete (may already be gone): {{e}}")


def monitor(slice_name: str):
    """Check slice health. Exit 1 on failure (triggers cleanup in weave.sh)."""
    from fabrictestbed_extensions.fablib.fablib import FablibManager
    fablib = FablibManager()
    try:
        slice_obj = fablib.get_slice(name=slice_name)
        state = str(slice_obj.get_state())
        if "StableOK" not in state:
            print(f"WARNING: Slice state is {{state}}")
            sys.exit(1)
        for node in slice_obj.get_nodes():
            stdout, _ = node.execute("echo ok", quiet=True)
            if "ok" not in stdout:
                raise Exception(f"Node {{node.get_name()}} not responding")
        print(f"### PROGRESS: Healthy — {{state}}")
    except Exception as e:
        print(f"ERROR: {{e}}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {py_name}.py {{start|stop|monitor}} SLICE_NAME")
        sys.exit(1)
    action, name = sys.argv[1], sys.argv[2]
    {{"start": start, "stop": stop, "monitor": monitor}}[action](name)
'''
    with open(os.path.join(weave_dir, f"{py_name}.py"), "w") as f:
        f.write(script_content)
    created_files.append(f"{py_name}.py")

    # .weaveignore
    with open(os.path.join(weave_dir, ".weaveignore"), "w") as f:
        f.write("# Files excluded from publishing\ndata/\nresults/\n*.csv\n*.key\nsecrets/\n.ipynb_checkpoints/\nweave.log\n")
    created_files.append(".weaveignore")

    # weave.log — empty log file (populated when the weave runs)
    with open(os.path.join(weave_dir, "weave.log"), "w") as f:
        f.write("")
    created_files.append("weave.log")

    # weave.md — human-readable specification and description of the weave.
    # Users can edit this file and ask LoomAI to update the weave accordingly.
    # LoomAI reads this file as the baseline specification when modifying the weave.
    weave_md_content = args.get("weave_md", "")
    if not weave_md_content:
        weave_md_content = f"""# {name}

{description}

## Overview

A single-node FABRIC slice. Edit this file to customize, then ask LoomAI
to "update the weave called {dir_name} based on weave.md".

## Files

| File | Description |
|------|-------------|
| `{py_name}.py` | Python lifecycle script (start/stop/monitor) using FABlib |
| `{py_name}.ipynb` | Jupyter notebook for interacting with the slice |
| `weave.sh` | Shell orchestrator — runs the Python script, handles Stop button |
| `weave.json` | Metadata, run config, and argument definitions |
| `weave.md` | This file — weave specification (edit to update the weave) |

## Specification

Edit this section to describe what you want. Then ask LoomAI to update.

### Nodes
- 1 node: 2 cores, 8GB RAM, 10GB disk, site=auto (FABRIC picks)
- Image: default_ubuntu_22

### Network
- (none — add networks here if needed, e.g. "L2Bridge between 2 nodes" or "FABNetv4 for cross-site")

### Software
- (none — add packages here, e.g. "install iperf3 and htop on all nodes")

### Lifecycle
- **start**: Create slice with 1 node, submit, wait for SSH
- **stop**: Delete slice
- **monitor**: Check slice state is StableOK, verify SSH
"""
    with open(os.path.join(weave_dir, "weave.md"), "w") as f:
        f.write(weave_md_content)
    created_files.append("weave.md")

    # --- Optional extras ---

    # data/ folder for results collection
    if args.get("include_data_folder"):
        data_dir = os.path.join(weave_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, ".gitkeep"), "w") as f:
            f.write("")
        with open(os.path.join(data_dir, "README.md"), "w") as f:
            f.write(f"# Data\n\nExperiment results for {name}.\n\nThis folder is excluded from publishing via `.weaveignore`.\n")
        created_files.append("data/README.md")

    # node_tools/ folder for scripts copied to VMs
    if args.get("include_node_tools"):
        tools_dir = os.path.join(weave_dir, "node_tools")
        os.makedirs(tools_dir, exist_ok=True)
        setup_content = args.get("node_tools_content", "")
        if not setup_content:
            setup_content = f"""#!/bin/bash
# Setup script for {name} — copied to each VM and executed
set -e

echo "Updating packages..."
sudo apt-get update -qq

echo "Installing tools..."
# Add your package installations here:
# sudo apt-get install -y -qq iperf3 htop

echo "Setup complete."
"""
        with open(os.path.join(tools_dir, "setup.sh"), "w") as f:
            f.write(setup_content)
        os.chmod(os.path.join(tools_dir, "setup.sh"), 0o755)
        created_files.append("node_tools/setup.sh")

    # Jupyter notebook — simple single-node FABlib starter at weave root
    if args.get("include_notebooks", True):  # Always include notebook by default
        nb_desc = args.get("notebook_description", f"Interact with the {name} slice")
        slice_default = dir_name.lower().replace('_', '-')
        notebook = {
            "cells": [
                {"cell_type": "markdown", "metadata": {}, "source": [
                    f"# {name}\n",
                    f"\n",
                    f"{nb_desc}\n",
                    f"\n",
                    f"Run the weave first (`weave.sh`) to provision the slice, then use this notebook.\n",
                ]},
                {"cell_type": "markdown", "metadata": {}, "source": [
                    "## 1. Load the Slice\n",
                ]},
                {"cell_type": "code", "metadata": {}, "source": [
                    "from fabrictestbed_extensions.fablib.fablib import FablibManager\n",
                    "\n",
                    "fablib = FablibManager()\n",
                    f"SLICE_NAME = '{slice_default}'\n",
                    "\n",
                    "slice_obj = fablib.get_slice(name=SLICE_NAME)\n",
                    "print(f'Slice: {slice_obj.get_name()} — {slice_obj.get_state()}')\n",
                ], "outputs": [], "execution_count": None},
                {"cell_type": "markdown", "metadata": {}, "source": [
                    "## 2. Node Details\n",
                ]},
                {"cell_type": "code", "metadata": {}, "source": [
                    "for node in slice_obj.get_nodes():\n",
                    "    print(f'{node.get_name()}: {node.get_management_ip()} ({node.get_site()})')\n",
                    "    print(f'  SSH: {node.get_ssh_command()}')\n",
                ], "outputs": [], "execution_count": None},
                {"cell_type": "markdown", "metadata": {}, "source": [
                    "## 3. Run a Command\n",
                ]},
                {"cell_type": "code", "metadata": {}, "source": [
                    "node = slice_obj.get_nodes()[0]\n",
                    "stdout, stderr = node.execute('hostname && uname -a')\n",
                    "print(stdout)\n",
                ], "outputs": [], "execution_count": None},
                {"cell_type": "markdown", "metadata": {}, "source": [
                    "## 4. Clean Up\n",
                ]},
                {"cell_type": "code", "metadata": {}, "source": [
                    "# Uncomment to delete the slice:\n",
                    "# slice_obj.delete()\n",
                    "# print('Slice deleted.')\n",
                ], "outputs": [], "execution_count": None},
            ],
            "metadata": {
                "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                "language_info": {"name": "python", "version": "3.11.0"},
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        nb_filename = f"{py_name}.ipynb"
        with open(os.path.join(weave_dir, nb_filename), "w") as f:
            json.dump(notebook, f, indent=1)
        created_files.append(nb_filename)

    return json.dumps({
        "status": "created",
        "dir_name": dir_name,
        "path": f"my_artifacts/{dir_name}/",
        "files": created_files,
    })


def _tool_summary(name: str, args: dict, result: str) -> str:
    """Generate a concise one-line summary of a tool execution result."""
    try:
        data = json.loads(result) if result else None
    except (json.JSONDecodeError, TypeError):
        data = None

    if name == "list_slices" and isinstance(data, list):
        from collections import Counter
        states = Counter(s.get("state", "?") for s in data)
        parts = [f"{v} {k}" for k, v in states.most_common()]
        return f"Found {len(data)} slice{'s' if len(data) != 1 else ''}" + (f" ({', '.join(parts)})" if parts else "")

    if name == "query_sites" and isinstance(data, list):
        available = [s for s in data if s.get("cores_available", 0) > 0]
        return f"{len(data)} sites ({len(available)} with available cores)"

    if name == "create_slice" and isinstance(data, dict):
        return f"Created draft '{data.get('name', '?')}'"

    if name == "submit_slice":
        sname = args.get("slice_name", "?")
        return f"Submitted '{sname}' for provisioning"

    if name == "delete_slice":
        sname = args.get("slice_name", "?")
        return f"Deleted '{sname}'"

    if name == "renew_slice":
        sname = args.get("slice_name", "?")
        return f"Renewed '{sname}'"

    if name == "add_node" and isinstance(data, dict):
        return f"Added node '{data.get('name', '?')}' at {args.get('site', '?')}"

    if name == "add_network":
        return f"Added network '{args.get('network_name', '?')}'"

    if name == "ssh_execute":
        node = args.get("node_name", "?")
        if isinstance(data, dict):
            exit_code = data.get("exit_code", "?")
            return f"Ran on {node} (exit {exit_code})"
        return f"Ran on {node}"

    if name == "get_slice" and isinstance(data, dict):
        state = data.get("state", "?")
        nodes = len(data.get("nodes", []))
        return f"'{data.get('name', '?')}' — {state}, {nodes} node{'s' if nodes != 1 else ''}"

    if name == "load_template":
        tname = args.get("template_name", "?")
        return f"Loaded template '{tname}'"

    # Chameleon tools
    if name == "list_chameleon_leases" and isinstance(data, list):
        active = sum(1 for l in data if l.get("status") == "ACTIVE")
        return f"Found {len(data)} leases ({active} active)"

    if name == "list_chameleon_instances" and isinstance(data, list):
        return f"Found {len(data)} instances"

    if name == "list_chameleon_sites" and isinstance(data, list):
        configured = sum(1 for s in data if s.get("configured"))
        return f"{len(data)} sites ({configured} configured)"

    if name == "chameleon_site_images" and isinstance(data, list):
        return f"{len(data)} images available"

    if name == "create_chameleon_lease" and isinstance(data, dict):
        return f"Created lease '{data.get('name', '?')}'"

    if name == "create_chameleon_instance" and isinstance(data, dict):
        return f"Launched instance '{data.get('name', '?')}'"

    if name in ("delete_chameleon_lease", "delete_chameleon_instance"):
        return "Deleted"

    if name == "list_chameleon_slices" and isinstance(data, list):
        active = sum(1 for s in data if s.get("state") in ("Active", "Deployed"))
        return f"Found {len(data)} Chameleon slices ({active} active)"

    if name == "deploy_chameleon_slice" and isinstance(data, dict):
        leases = len(data.get("leases", []))
        return f"Deployed draft — {leases} lease{'s' if leases != 1 else ''} created"

    if name == "list_composite_slices" and isinstance(data, list):
        return f"Found {len(data)} composite slices"

    if name == "get_composite_slice" and isinstance(data, dict):
        name_val = data.get("name", "?")
        fab = len(data.get("fabric_slices", []))
        chi = len(data.get("chameleon_slices", []))
        return f"'{name_val}' — {fab} FABRIC + {chi} Chameleon members"

    if name == "create_composite_slice" and isinstance(data, dict):
        return f"Created composite '{data.get('name', '?')}'"

    if name == "search_examples" and isinstance(data, dict):
        results = data.get("results", [])
        return data.get("note", f"Found {len(results)} examples")

    # Default: truncate result
    if result:
        clean = result.strip()[:80]
        if len(result) > 80:
            clean += "..."
        return clean
    return "Done"


async def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool and return the result as a JSON string."""
    try:
        if name == "list_slices":
            from app.routes.slices import list_slices
            result = await list_slices(max_age=0)
            # Trim to essential fields
            return json.dumps([{
                "name": s.get("name"), "state": s.get("state"),
                "nodes": len(s.get("nodes", [])),
                "lease_end": s.get("lease_end"),
            } for s in result], default=str)

        elif name == "get_slice":
            from app.routes.slices import get_slice
            result = await get_slice(arguments["slice_name"], max_age=0)
            # Return a COMPACT summary so the result fits in standard tier's
            # tool_result_max (2000 chars). Full topology JSON for a 3-node
            # multi-network slice is 3-6KB and gets truncated mid-node, which
            # caused the LLM to miss later nodes and forget them in multi-node
            # workflows. If the caller needs low-level interface details
            # (MACs, VLAN IDs), they can query specific nodes via ssh_execute.
            nodes_summary = []
            for n in result.get("nodes", []) or []:
                if not isinstance(n, dict):
                    continue
                # Keep only fields a workflow would need: identity, placement,
                # image, IPs, and the network names it's attached to.
                net_names = []
                for iface in (n.get("interfaces") or []):
                    if isinstance(iface, dict):
                        nn = iface.get("network_name")
                        if nn and nn not in net_names:
                            net_names.append(nn)
                comp_models = []
                for c in (n.get("components") or []):
                    if isinstance(c, dict):
                        m = c.get("model")
                        if m:
                            comp_models.append(m)
                nodes_summary.append({
                    "name": n.get("name"),
                    "site": n.get("site"),
                    "host": n.get("host"),
                    "cores": n.get("cores"),
                    "ram": n.get("ram"),
                    "disk": n.get("disk"),
                    "image": n.get("image"),
                    "management_ip": n.get("management_ip"),
                    "username": n.get("username", "ubuntu"),
                    "reservation_state": n.get("reservation_state"),
                    "error_message": n.get("error_message") or "",
                    "components": comp_models,
                    "networks": net_names,
                })
            networks_summary = []
            for net in result.get("networks", []) or []:
                if not isinstance(net, dict):
                    continue
                networks_summary.append({
                    "name": net.get("name"),
                    "type": net.get("type"),
                    "site": net.get("site"),
                })
            compact = {
                "name": result.get("name"),
                "id": result.get("id"),
                "state": result.get("state"),
                "lease_end": result.get("lease_end"),
                "error_messages": result.get("error_messages") or [],
                "node_count": len(nodes_summary),
                "nodes": nodes_summary,
                "network_count": len(networks_summary),
                "networks": networks_summary,
            }
            return json.dumps(compact, default=str)

        elif name == "query_sites":
            from app.routes.resources import list_sites
            sites = await list_sites(max_age=0)
            # Return compact summary
            summary = []
            for s in sites:
                summary.append({
                    "name": s.get("name"),
                    "cores_available": s.get("cores_available"),
                    "ram_available": s.get("ram_available"),
                    "disk_available": s.get("disk_available"),
                    "state": s.get("state"),
                    "gpus": s.get("gpu_available", 0),
                })
            return json.dumps(summary, default=str)

        elif name == "get_site_hosts":
            from app.routes.resources import list_site_hosts
            hosts = await list_site_hosts(arguments["site_name"])
            return json.dumps(hosts, default=str)

        elif name == "create_slice":
            from app.routes.slices import create_slice
            result = await create_slice(arguments["name"])
            return json.dumps({"status": "created", "name": arguments["name"], "state": result.get("state", "Draft")}, default=str)

        elif name == "add_node":
            from app.routes.slices import add_node, CreateNodeRequest
            req = CreateNodeRequest(
                name=arguments["node_name"],
                site=arguments.get("site", ""),
                cores=arguments.get("cores", 2),
                ram=arguments.get("ram", 8),
                disk=arguments.get("disk", 10),
                image=arguments.get("image", "default_ubuntu_22"),
            )
            result = await asyncio.to_thread(_run_sync, add_node, arguments["slice_name"], req)
            return json.dumps({"status": "added", "node": arguments["node_name"]}, default=str)

        elif name == "add_component":
            from app.routes.slices import add_component, CreateComponentRequest
            req = CreateComponentRequest(
                name=arguments["component_name"],
                model=arguments["model"],
            )
            result = await asyncio.to_thread(_run_sync, add_component, arguments["slice_name"], arguments["node_name"], req)
            return json.dumps({"status": "added", "component": arguments["component_name"], "model": arguments["model"]}, default=str)

        elif name == "add_fabnet":
            from app.routes.slices import add_fabnet_to_node, AddFabnetRequest
            net_type = arguments.get("net_type", "IPv4")
            req = AddFabnetRequest(net_type=net_type)
            await asyncio.to_thread(
                _run_sync, add_fabnet_to_node,
                arguments["slice_name"], arguments["node_name"], req,
            )
            return json.dumps({
                "status": "attached",
                "node": arguments["node_name"],
                "net_type": net_type,
                "note": f"Per-site FABNet{net_type[-2:].lower()} created; FABRIC backbone routes between sites.",
            }, default=str)

        elif name == "add_network":
            from app.routes.slices import add_network as add_network_fn, CreateNetworkRequest
            req = CreateNetworkRequest(
                name=arguments["network_name"],
                type=arguments["type"],
                interfaces=arguments.get("interfaces", []),
            )
            result = await asyncio.to_thread(_run_sync, add_network_fn, arguments["slice_name"], req)
            return json.dumps({"status": "added", "network": arguments["network_name"], "type": arguments["type"]}, default=str)

        elif name == "submit_slice":
            from app.routes.slices import submit_slice
            result = await submit_slice(arguments["slice_name"])
            return json.dumps({"status": "submitted", "state": result.get("state", "unknown")}, default=str)

        elif name == "delete_slice":
            from app.routes.slices import delete_slice
            result = await delete_slice(arguments["slice_name"])
            return json.dumps(result, default=str)

        elif name == "renew_slice":
            from app.routes.slices import renew_slice, RenewRequest
            req = RenewRequest(days=arguments.get("days", 7))
            result = await renew_slice(arguments["slice_name"], req)
            return json.dumps(result, default=str)

        elif name == "list_templates":
            from app.routes.templates import list_templates
            result = await asyncio.to_thread(_run_sync, list_templates)
            return json.dumps([{
                "name": t.get("name"), "dir_name": t.get("dir_name"),
                "description": t.get("description", ""),
            } for t in result], default=str)

        elif name == "load_template":
            from app.routes.templates import load_template, LoadTemplateRequest
            req = LoadTemplateRequest(slice_name=arguments["slice_name"])
            result = await asyncio.to_thread(_run_sync, load_template, arguments["template_name"], req)
            return json.dumps({"status": "loaded", "slice_name": arguments["slice_name"]}, default=str)

        elif name == "save_as_template":
            from app.routes.templates import save_template, SaveTemplateRequest
            req = SaveTemplateRequest(
                slice_name=arguments["slice_name"],
                template_name=arguments["template_name"],
                description=arguments.get("description", ""),
            )
            result = await asyncio.to_thread(_run_sync, save_template, req)
            return json.dumps({"status": "saved", "template_name": arguments["template_name"]}, default=str)

        elif name == "remove_node":
            from app.routes.slices import remove_node
            result = await asyncio.to_thread(_run_sync, remove_node, arguments["slice_name"], arguments["node_name"])
            return json.dumps({"status": "removed", "node": arguments["node_name"]}, default=str)

        elif name == "remove_network":
            from app.routes.slices import remove_network
            result = await asyncio.to_thread(_run_sync, remove_network, arguments["slice_name"], arguments["network_name"])
            return json.dumps({"status": "removed", "network": arguments["network_name"]}, default=str)

        # --- File Operations (container filesystem) ---
        elif name == "write_file":
            from app.user_context import get_user_storage
            base = get_user_storage()
            rel = arguments["path"].lstrip("/")
            full = os.path.realpath(os.path.join(base, rel))
            if not full.startswith(os.path.realpath(base) + os.sep):
                return json.dumps({"error": "Path outside user storage"})
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(arguments["content"])
            return json.dumps({"status": "written", "path": rel, "size": len(arguments["content"])})

        elif name == "read_file":
            from app.user_context import get_user_storage
            base = get_user_storage()
            rel = arguments["path"].lstrip("/")
            full = os.path.realpath(os.path.join(base, rel))
            if not full.startswith(os.path.realpath(base) + os.sep):
                return json.dumps({"error": "Path outside user storage"})
            if not os.path.isfile(full):
                return json.dumps({"error": f"File not found: {rel}"})
            with open(full, "r") as f:
                content = f.read(100_000)  # limit to 100KB
            return json.dumps({"path": rel, "content": content})

        elif name == "list_directory":
            from app.user_context import get_user_storage
            base = get_user_storage()
            rel = (arguments.get("path") or "").lstrip("/")
            full = os.path.realpath(os.path.join(base, rel)) if rel else os.path.realpath(base)
            if not (full.startswith(os.path.realpath(base) + os.sep) or full == os.path.realpath(base)):
                return json.dumps({"error": "Path outside user storage"})
            if not os.path.isdir(full):
                return json.dumps({"error": f"Directory not found: {rel}"})
            entries = []
            for item in sorted(os.listdir(full)):
                if item.startswith("."):
                    continue
                item_path = os.path.join(full, item)
                entries.append({
                    "name": item,
                    "type": "dir" if os.path.isdir(item_path) else "file",
                    "size": os.path.getsize(item_path) if os.path.isfile(item_path) else 0,
                })
            return json.dumps({"path": rel or "/", "entries": entries})

        elif name == "create_directory":
            from app.user_context import get_user_storage
            base = get_user_storage()
            rel = arguments["path"].lstrip("/")
            full = os.path.realpath(os.path.join(base, rel))
            if not full.startswith(os.path.realpath(base) + os.sep):
                return json.dumps({"error": "Path outside user storage"})
            os.makedirs(full, exist_ok=True)
            return json.dumps({"status": "created", "path": rel})

        elif name == "delete_path":
            import shutil
            from app.user_context import get_user_storage
            base = get_user_storage()
            rel = arguments["path"].lstrip("/")
            full = os.path.realpath(os.path.join(base, rel))
            if not full.startswith(os.path.realpath(base) + os.sep):
                return json.dumps({"error": "Path outside user storage"})
            if not os.path.exists(full):
                return json.dumps({"error": f"Not found: {rel}"})
            if os.path.isdir(full):
                shutil.rmtree(full)
            else:
                os.remove(full)
            return json.dumps({"status": "deleted", "path": rel})

        # --- Artifact Management ---
        elif name == "list_artifacts":
            from app.routes.artifacts import list_local_artifacts
            result = await asyncio.to_thread(_run_sync, list_local_artifacts)
            artifacts = result.get("artifacts", [])
            return json.dumps([{
                "name": a.get("name"), "category": a.get("category"),
                "description": a.get("description", ""),
                "published": a.get("published", False),
            } for a in artifacts], default=str)

        elif name == "publish_artifact":
            from app.routes.artifacts import publish_artifact as publish_fn, PublishRequest
            req = PublishRequest(
                dir_name=arguments["dir_name"],
                title=arguments["title"],
                category=arguments.get("category", ""),
                description=arguments.get("description", ""),
                tags=arguments.get("tags", []),
                visibility=arguments.get("visibility", "author"),
                project_uuid=arguments.get("project_uuid", ""),
            )
            result = await publish_fn(req)
            return json.dumps(result, default=str)

        # --- Slice Operations ---
        elif name == "refresh_slice":
            from app.routes.slices import refresh_slice as refresh_fn
            result = await refresh_fn(arguments["slice_name"])
            # Return summary instead of full slice data
            return json.dumps({
                "status": "refreshed", "name": result.get("name"),
                "state": result.get("state"),
                "nodes": len(result.get("nodes", [])),
            }, default=str)

        elif name == "validate_slice":
            from app.routes.slices import validate_slice as validate_fn
            result = await asyncio.to_thread(_run_sync, validate_fn, arguments["slice_name"])
            return json.dumps(result, default=str)

        elif name == "update_node":
            from app.routes.slices import update_node as update_node_fn, UpdateNodeRequest
            req = UpdateNodeRequest(
                site=arguments.get("site"),
                cores=arguments.get("cores"),
                ram=arguments.get("ram"),
                disk=arguments.get("disk"),
                image=arguments.get("image"),
            )
            result = await asyncio.to_thread(
                _run_sync, update_node_fn, arguments["slice_name"], arguments["node_name"], req
            )
            return json.dumps({"status": "updated", "node": arguments["node_name"]}, default=str)

        # --- VM Operations (SSH) ---
        elif name == "ssh_execute":
            from app.routes.files import execute_on_vm, VmExecBody
            body = VmExecBody(
                command=arguments["command"],
                timeout=arguments.get("timeout"),
            )
            result = await execute_on_vm(arguments["slice_name"], arguments["node_name"], body)
            # Truncate long output
            stdout = result.get("stdout", "")[:8000]
            stderr = result.get("stderr", "")[:2000]
            return json.dumps({"stdout": stdout, "stderr": stderr}, default=str)

        elif name == "reboot_and_wait":
            from app.routes.files import reboot_and_wait as reboot_fn, VmRebootBody
            body = VmRebootBody(timeout=int(arguments.get("timeout", 300) or 300))
            result = await reboot_fn(arguments["slice_name"], arguments["node_name"], body)
            return json.dumps(result, default=str)

        elif name == "write_vm_file":
            from app.routes.files import write_vm_file_content, VmWriteFileRequest
            body = VmWriteFileRequest(path=arguments["path"], content=arguments["content"])
            result = await write_vm_file_content(arguments["slice_name"], arguments["node_name"], body)
            return json.dumps({"status": "written", "path": arguments["path"]}, default=str)

        elif name == "read_vm_file":
            from app.routes.files import read_vm_file_content, VmReadFileRequest
            body = VmReadFileRequest(path=arguments["path"])
            result = await read_vm_file_content(arguments["slice_name"], arguments["node_name"], body)
            content = result.get("content", "")[:50000]
            return json.dumps({"path": arguments["path"], "content": content}, default=str)

        # --- Recipe Operations ---
        elif name == "list_recipes":
            from app.routes.recipes import list_recipes as list_recipes_fn
            result = await asyncio.to_thread(_run_sync, list_recipes_fn)
            return json.dumps([{
                "name": r.get("name"), "description": r.get("description", ""),
                "dir_name": r.get("dir_name"),
            } for r in result], default=str)

        # --- JupyterLab ---
        elif name == "manage_jupyter":
            action = arguments["action"]
            if action == "start":
                from app.routes.jupyter import start_jupyter
                result = await start_jupyter()
                return json.dumps(result, default=str)
            elif action == "stop":
                from app.routes.jupyter import stop_jupyter
                result = await stop_jupyter()
                return json.dumps(result, default=str)
            elif action == "status":
                from app.routes.jupyter import jupyter_status
                result = await jupyter_status()
                return json.dumps(result, default=str)
            else:
                return json.dumps({"error": f"Unknown jupyter action: {action}"})

        # --- Background Runs ---
        elif name == "start_background_run":
            from app.routes.templates import start_background_run, StartRunRequest, _sanitize_name, _templates_dir, _validate_path
            result = start_background_run(
                arguments["weave_dir_name"],
                arguments["script"],
                StartRunRequest(slice_name=arguments.get("slice_name", "")),
            )
            return json.dumps(result, default=str)

        elif name == "list_background_runs":
            from app.routes.templates import list_background_runs
            result = list_background_runs()
            return json.dumps(result, default=str)

        elif name == "get_background_run_output":
            from app.routes.templates import get_background_run_output
            result = get_background_run_output(
                arguments["run_id"],
                arguments.get("offset", 0),
            )
            return json.dumps(result, default=str)

        elif name == "stop_background_run":
            from app.routes.templates import stop_background_run
            result = stop_background_run(arguments["run_id"])
            return json.dumps(result, default=str)

        elif name == "create_weave":
            return await _create_weave_tool(arguments)

        # --- Web Search & Fetch ---
        elif name == "web_search":
            result = await _execute_web_search(
                arguments["query"],
                arguments.get("max_results", 5),
            )
            return result

        elif name == "fetch_webpage":
            result = await _execute_fetch_webpage(
                arguments["url"],
                arguments.get("max_length", 4000),
            )
            return result

        # --- Chameleon Cloud tools ---

        elif name == "list_chameleon_leases":
            from app.routes.chameleon import list_leases
            site = arguments.get("site")
            result = await list_leases(site)
            return json.dumps([{
                "name": l.get("name"), "status": l.get("status"),
                "site": l.get("_site"), "id": l.get("id"),
                "start": l.get("start_date", "")[:16],
                "end": l.get("end_date", "")[:16],
            } for l in result], default=str)

        elif name == "list_chameleon_instances":
            from app.routes.chameleon import list_instances
            site = arguments.get("site")
            result = await list_instances(site)
            return json.dumps(result, default=str)

        elif name == "list_chameleon_sites":
            from app.routes.chameleon import list_chameleon_sites
            result = await list_chameleon_sites()
            return json.dumps(result, default=str)

        elif name == "chameleon_site_images":
            from app.routes.chameleon import site_images
            result = await site_images(arguments["site"])
            return json.dumps(result[:20], default=str)  # Limit to 20

        elif name == "create_chameleon_lease":
            from app.routes.chameleon import create_lease
            from starlette.requests import Request as _Req
            from starlette.datastructures import Headers
            # Build a mock request with the arguments as JSON body
            scope = {"type": "http", "method": "POST", "headers": []}
            mock_req = _Req(scope)
            mock_req._body = json.dumps(arguments).encode()
            result = await create_lease(mock_req)
            return json.dumps(result, default=str)

        elif name == "delete_chameleon_lease":
            from app.routes.chameleon import delete_lease
            result = await delete_lease(arguments["lease_id"], arguments.get("site", "CHI@TACC"))
            return json.dumps(result, default=str)

        elif name == "create_chameleon_instance":
            from app.routes.chameleon import create_instance
            from starlette.requests import Request as _Req
            scope = {"type": "http", "method": "POST", "headers": []}
            mock_req = _Req(scope)
            mock_req._body = json.dumps(arguments).encode()
            result = await create_instance(mock_req)
            return json.dumps(result, default=str)

        elif name == "delete_chameleon_instance":
            from app.routes.chameleon import delete_instance
            result = await delete_instance(arguments["instance_id"], arguments.get("site", "CHI@TACC"))
            return json.dumps(result, default=str)

        elif name == "list_chameleon_slices":
            from app.routes.chameleon import list_chameleon_slices
            result = await list_chameleon_slices()
            return json.dumps(result, default=str)

        elif name == "deploy_chameleon_slice":
            from app.routes.chameleon import deploy_draft
            body = {"duration_hours": arguments.get("hours", 4)}
            result = await deploy_draft(arguments["draft_id"], body)
            return json.dumps(result, default=str)

        elif name == "list_composite_slices":
            from app.routes.composite import list_composite_slices
            result = await list_composite_slices()
            return json.dumps(result, default=str)

        elif name == "get_composite_slice":
            from app.routes.composite import get_composite_slice
            result = await get_composite_slice(arguments["slice_id"])
            return json.dumps(result, default=str)

        elif name == "create_composite_slice":
            from app.routes.composite import create_composite_slice
            body = {"name": arguments["name"]}
            result = await create_composite_slice(body)
            return json.dumps(result, default=str)

        elif name == "search_examples":
            # LLMs sometimes send "name" instead of "query"
            q = arguments.get("query") or arguments.get("name") or arguments.get("search") or ""
            return await _search_examples(q)

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as e:
        logger.warning("Tool %s failed: %s", name, e)
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Web search & fetch helpers
# ---------------------------------------------------------------------------

async def _execute_web_search(query: str, max_results: int = 5) -> str:
    """Search the web using DuckDuckGo and return results as JSON."""
    max_results = min(max(1, max_results), 10)
    try:
        from duckduckgo_search import DDGS

        def _search():
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
                for r in results
            ]

        results = await asyncio.to_thread(_search)
        return json.dumps({"query": query, "results": results}, default=str)
    except Exception as e:
        logger.warning("Web search failed: %s", e)
        return json.dumps({"error": f"Search failed: {e}"})


async def _execute_fetch_webpage(url: str, max_length: int = 4000) -> str:
    """Fetch a webpage and return its text content (HTML stripped)."""
    max_length = min(max(500, max_length), 8000)
    try:
        resp = await ai_client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            text = _extract_text_from_html(resp.text)
        else:
            text = resp.text
        if len(text) > max_length:
            text = text[:max_length] + "\n\n[... truncated]"
        return json.dumps({"url": url, "content": text}, default=str)
    except Exception as e:
        logger.warning("Fetch webpage failed: %s", e)
        return json.dumps({"error": f"Fetch failed: {e}"})


def _extract_text_from_html(html: str) -> str:
    """Extract readable text from HTML, stripping tags, scripts, and styles."""
    import re
    # Remove script and style blocks
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Decode common HTML entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Re-add paragraph breaks at likely boundaries
    text = re.sub(r' {2,}', '\n\n', text)
    return text


# ---------------------------------------------------------------------------
# Streaming agentic chat
# ---------------------------------------------------------------------------

# Track cancelled streaming requests
_cancelled_requests: set[str] = set()


@router.get("/api/ai/chat/agents")
async def list_agents_endpoint():
    agents = _load_agents()
    return [{"id": aid, "name": info["name"], "description": info["description"]} for aid, info in agents.items()]


@router.post("/api/ai/chat/stream")
async def chat_stream(request: Request):
    """Agentic streaming chat with tool calling.

    The LLM can call tools (query sites, create slices, etc). When it does,
    we execute the tools, send results back, and let the LLM continue.
    All streamed as SSE events to the frontend.
    """
    if not _get_ai_api_key():
        return StreamingResponse(
            iter([b'data: {"error": "AI API key not configured"}\n\n']),
            media_type="text/event-stream",
        )

    body = await request.json()
    messages = body.get("messages", [])
    model = body.get("model") or ""
    if not model:
        from app.settings_manager import get_default_model
        model = get_default_model() or "qwen3-coder-30b"
    agent_id = body.get("agent")
    slice_context = body.get("slice_context")
    request_id = body.get("request_id", "")

    # Route to NRP server if model has "nrp:" prefix
    use_nrp = model.startswith("nrp:")
    if use_nrp:
        model = model[4:]  # strip prefix
        server_url = _nrp_server_url()
        api_key = _get_nrp_api_key()
        if not api_key:
            return StreamingResponse(
                iter([b'data: {"error": "NRP API key not configured"}\n\n']),
                media_type="text/event-stream",
            )
    else:
        server_url = _ai_server_url()
        api_key = _get_ai_api_key()

    # Build system prompt with model-aware context management
    from app.chat_context import (
        get_model_profile, get_system_prompt, trim_conversation,
        filter_tool_schemas, estimate_tokens, estimate_conversation_tokens,
    )
    from app.chat_intent import detect_intent, detect_multi_step, is_destructive, record_intent_result
    from app.chat_prompt import LOOMAI_MODE_PROMPT, LOOMAI_MODE_EXTENDED

    # Look up actual context_length from discovered models
    from app.settings_manager import load_settings
    _ctx_length = None
    _ctx_source = "default"
    try:
        _discovered = load_settings().get("ai", {}).get("discovered_models", {})
        _model_bare = model.split(":")[-1] if ":" in model else model  # strip provider prefix
        for _provider_models in _discovered.values():
            if isinstance(_provider_models, list):
                for _m in _provider_models:
                    if isinstance(_m, dict) and _m.get("id") == _model_bare:
                        _ctx_length = _m.get("context_length")
                        if _ctx_length:
                            _ctx_source = "discovered"
                        break
            if _ctx_length:
                break
    except Exception:
        pass

    # Fallback to hardcoded defaults if discovery hasn't persisted yet
    # (first-turn bootstrap before the startup task writes discovered_models)
    if not _ctx_length:
        from app.routes.ai_terminal import _FABRIC_CONTEXT_DEFAULTS, _NRP_CONTEXT_DEFAULTS
        _model_bare = model.split(":")[-1] if ":" in model else model
        _ctx_length = _FABRIC_CONTEXT_DEFAULTS.get(_model_bare) or _NRP_CONTEXT_DEFAULTS.get(_model_bare)
        if _ctx_length:
            _ctx_source = "hardcoded-default"

    profile = get_model_profile(model, context_length=_ctx_length)
    logger.info("Chat model=%s tier=%s context=%d (source=%s)", model, profile["tier"], profile["context_window"], _ctx_source)

    # --- LoomAI-side intent detection (pre-processing) ---
    # Extract the user's last message for intent matching
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content") or ""
            break

    intent_tool, intent_args, intent_confidence = detect_intent(user_message)
    template = detect_multi_step(user_message)

    # --- Destructive-action authorization check ---
    # If the LLM decides to call submit_slice / delete_slice on its own but the
    # user's message doesn't explicitly authorize it, we synthesize a
    # "blocked" tool result instead of executing. The intent-detection path
    # already has its own confirm_needed gate; this handles the case where
    # the model picks a destructive tool via native function calling.
    _user_msg_lower = (user_message or "").lower()
    _DESTRUCTIVE_VERBS = (
        "submit", "deploy", "provision", "launch the slice", "start the slice",
        "go live", "bring up", "build the slice",
        "delete", "destroy", "tear down", "teardown", "release",
        "remove slice", "drop slice", "kill slice", "terminate slice",
    )
    _user_authorized_destructive = any(v in _user_msg_lower for v in _DESTRUCTIVE_VERBS)
    if _user_authorized_destructive:
        logger.info("User message authorizes destructive actions")
    else:
        logger.debug("User message does NOT authorize destructive actions — LLM submit/delete calls will be blocked")

    # Pre-fetch data for high-confidence intents
    prefetched_data = ""
    prefetched_tools: list[tuple[str, str]] = []  # (tool_name, result)

    confirm_needed = False  # C2: dry run for destructive ops

    if intent_confidence in ("high", "medium") and intent_tool:
        if is_destructive(intent_tool):
            # C2: Don't execute destructive ops — ask LLM to confirm with user
            confirm_needed = True
            logger.info("Destructive intent %s — will ask for confirmation", intent_tool)
        else:
            try:
                result = await execute_tool(intent_tool, intent_args)
                prefetched_data = result
                prefetched_tools.append((intent_tool, result[:profile["tool_result_max"]]))
                logger.info("Pre-fetched %s (%s confidence)", intent_tool, intent_confidence)
                # Record intent success for learning (persists to disk)
                try:
                    record_intent_result(model, intent_tool, True)
                except Exception:
                    pass
            except Exception as e:
                logger.warning("Pre-fetch failed for %s: %s", intent_tool, e)
                try:
                    record_intent_result(model, intent_tool, False)
                except Exception:
                    pass

    elif template and not template.get("confirm"):
        # Non-destructive template — execute first step
        if template["steps"]:
            step_tool, step_args = template["steps"][0]
            try:
                result = await execute_tool(step_tool, step_args)
                prefetched_data = result
                prefetched_tools.append((step_tool, result[:profile["tool_result_max"]]))
            except Exception:
                pass

    # Always pre-fetch slice summary (lightweight, ~200 tokens)
    if not any(t == "list_slices" for t, _ in prefetched_tools):
        try:
            slice_summary = await execute_tool("list_slices", {})
            prefetched_tools.append(("list_slices", slice_summary[:300]))
        except Exception:
            pass

    # Pre-fetch FABlib examples when weave/experiment creation detected
    _weave_keywords = ["weave", "experiment", "topology", "iperf", "benchmark", "deploy"]
    _slice_mutation_keywords = [
        "add node", "add a node", "attach", "add component",
        "add network", "change image", "update node", "remove node",
        "remove network", "modify slice", "add gpu", "add nic",
        "add smartnic", "add fpga", "add nvme",
    ]
    # Any mention of FABlib specifics, network types, or "slice" in a
    # code-generation context should inject the ground truth. This catches
    # questions like "write a FABlib function to create a 2-node L2Bridge
    # slice" which otherwise slip past the weave/mutation keyword filters.
    _fablib_code_keywords = [
        "fablib", "fabric_lib", "fabrictestbed",
        "l2bridge", "l2sts", "l2ptp", "fabnetv4", "fabnetv6", "fabnet",
        "new_slice", "add_node", "add_l2network", "add_l3network",
        "slice.submit", "slice.add",
    ]
    _msg_lower = user_message.lower()
    _is_weave_request = any(kw in _msg_lower for kw in _weave_keywords)
    _is_slice_mutation = any(kw in _msg_lower for kw in _slice_mutation_keywords)
    _is_fablib_code = any(kw in _msg_lower for kw in _fablib_code_keywords)
    # Also treat "slice" + any code-generation verb as a FABlib code request.
    _has_slice_word = "slice" in _msg_lower
    _code_gen_verbs = ("write", "create", "code", "function", "python", "script", "generate")
    _is_slice_code = _has_slice_word and any(v in _msg_lower for v in _code_gen_verbs)
    _needs_fablib_ref = (
        _is_weave_request or _is_slice_mutation or _is_fablib_code or _is_slice_code
    )
    if _is_weave_request and not any(t == "search_examples" for t, _ in prefetched_tools):
        try:
            examples = await execute_tool("search_examples", {"query": user_message[:100]})
            prefetched_tools.append(("search_examples", examples[:6000]))
        except Exception:
            pass

    # --- RAG retrieval: hybrid semantic+BM25 search over the knowledge corpus ---
    # Runs for every non-trivial chat turn. Retrieved chunks are injected as
    # a "Retrieved Context" block in the system prompt.
    rag_context_block = ""
    try:
        from app.rag import refresh_index_if_stale, retrieve_for_chat, format_hits_as_context
        # Cheap incremental refresh (rescans corpus, re-embeds changed files only)
        await refresh_index_if_stale(max_age=30.0)
        # Don't waste retrieval on trivial greetings
        if len(user_message) >= 8:
            # Weave-biased retrieval when the user is clearly talking about weaves
            hits = retrieve_for_chat(
                user_message,
                k=5,
                min_score=0.30,
                weave_bias=_is_weave_request,
            )
            if hits:
                # Size budget scales with tier: compact models get less, large models more
                max_rag_chars = {
                    "compact": 1500,
                    "standard": 4000,
                    "large": 6000,
                }.get(profile["tier"], 3000)
                rag_context_block = format_hits_as_context(hits, max_chars=max_rag_chars)
                logger.info(
                    "RAG: retrieved %d chunks for chat (top source=%s, top score=%.2f)",
                    len(hits), hits[0].chunk.source_type, hits[0].score,
                )
    except Exception as e:
        logger.debug("RAG retrieval skipped: %s", e)

    # --- Build system prompt ---
    # For low-confidence / complex requests: use the full system prompt with tool-calling
    # so the LLM can call write_file, create_slice, etc. directly.
    # For high-confidence: use compact LoomAI-mode prompt (LoomAI already executed the tool).
    use_full_llm_mode = (intent_confidence == "low")

    if use_full_llm_mode:
        # Full mode — LLM needs tool descriptions and the ability to call tools
        # But for compact models, use compact prompt even in full mode to avoid overflow
        if profile["tier"] == "compact":
            system_parts = [LOOMAI_MODE_PROMPT]
        else:
            system_parts = [get_system_prompt(profile["system_prompt"])]
        # Add tool-use instructions
        system_parts.append(
            "\n\n## Tool Use\n"
            "You have tools to: create/manage slices and nodes, write/read files, "
            "SSH to VMs, list sites/templates/artifacts, run weave scripts.\n"
            "Use tools proactively. Summarize after each tool call.\n\n"
            "**Creating weaves**: Use `create_weave` with ALL options in ONE call.\n"
            "**Writing FABlib code**: ALWAYS call `search_examples(query)` first to find\n"
            "proven code patterns, then `read_file` to load the example. Adapt it.\n"
            "Never write FABlib code from scratch — use the example library.\n"
            "When updating a weave, read `weave.md` first — it is the authoritative spec.\n"
            "**JSON output**: Never wrap JSON in markdown ```json``` code fences. "
            "Emit raw JSON only when the user asks for JSON.\n\n"
            "## Critical Rules — Read Carefully\n"
            "**Create slice ≠ submit slice.** When the user says 'create a slice', "
            "build a DRAFT topology only (`create_slice`, `add_node`, `add_fabnet`, "
            "`add_network`, `add_component`). Do NOT call `submit_slice` unless the "
            "user's message explicitly contains 'submit', 'deploy', 'provision', or "
            "similar. When the draft is ready, describe what you built and ask the "
            "user to confirm before submitting. If you call submit_slice without "
            "authorization you will receive DESTRUCTIVE_ACTION_BLOCKED — do not "
            "retry, summarize instead.\n\n"
            "**Create slice ≠ create weave.** A SLICE is a live FABRIC topology "
            "(nodes + networks, provisioned as VMs). A WEAVE is a project directory "
            "in `my_artifacts/` containing scripts, notebooks, and metadata. If the "
            "user asks for a slice, use `create_slice` only — do NOT also call "
            "`create_weave` unless they explicitly ask for one.\n\n"
            "**Multi-site FABNetv4/FABNetv6.** To connect N nodes at different sites "
            "over FABnet, call `add_fabnet(slice_name, node_name, net_type='IPv4')` "
            "ONCE PER NODE. FABRIC automatically creates a per-site FABnet network "
            "for each site and routes between them via its backbone. Do NOT use "
            "`add_network(type='FABNetv4', interfaces=[...])` for multi-site — a "
            "single FABNetv4 service cannot span more than one site and the FABRIC "
            "orchestrator will reject it with 'Service cannot span N sites. Limit: 1.'\n\n"
            "**Don't retry blocked actions.** If a tool returns "
            "`DESTRUCTIVE_ACTION_BLOCKED`, STOP. Summarize progress and ask the "
            "user to confirm the destructive action in plain text. Retrying the "
            "same blocked tool will be blocked again.\n\n"
            "**Multi-node operations must touch EVERY node.** When the user says "
            "'all nodes', 'every node', 'the nodes', or any phrase implying all "
            "nodes in a slice, you MUST issue at least one `ssh_execute`, "
            "`write_vm_file`, `read_vm_file`, or `reboot_and_wait` call against "
            "every node returned by `get_slice`. Before emitting your final "
            "summary, verify you touched every node. Your summary MUST list each "
            "node by name with its per-node status (success/partial/skipped/error). "
            "Do NOT say 'both nodes' if there are three.\n\n"
            "**Container filesystem ≠ VM filesystem.** `write_file`, `read_file`, "
            "`list_directory`, `create_directory`, `delete_path` operate on the "
            "LoomAI container's user storage (rooted at `my_artifacts/`, "
            "`my_slices/`, `notebooks/`). Files written with these tools are NOT "
            "visible inside provisioned VMs. To put a file on a VM, use "
            "`write_vm_file(slice_name, node_name, path, content)`. To run a "
            "command on a VM, use `ssh_execute(...)`. Never `ssh_execute "
            "python3 /home/fabric/script.py` unless you first `write_vm_file` to "
            "that path on the VM.\n\n"
            "**Reboot handling.** To reboot a VM as part of a workflow, use "
            "`reboot_and_wait(slice_name, node_name)`. It reboots via SSH and "
            "polls until the VM is reachable again (default 5 min). For "
            "'reboot if needed' workflows, first check "
            "`test -f /var/run/reboot-required` with ssh_execute; if present, "
            "call reboot_and_wait, then continue with post-reboot steps.\n\n"
            "**Be honest in your summary.** Before writing your final summary, "
            "count the nodes and operations you actually performed. Mention any "
            "node that was skipped or any operation that returned an error or "
            "timed out. Do not claim success when a tool returned an error. "
            "Be specific: 'node1 fully configured; node2 apt lock — 5/10 "
            "packages installed; node3 not reached.'\n"
        )
        # Inject create-weave skill when the user is building weaves/experiments
        if _is_weave_request:
            _skill_path = os.path.join(_AI_TOOLS_DIR, "shared", "skills", "create-weave.md")
            try:
                with open(_skill_path) as _sf:
                    _skill = _sf.read()
                # Strip frontmatter
                if _skill.startswith("---"):
                    _end = _skill.find("---", 3)
                    if _end > 0:
                        _skill = _skill[_end + 3:].strip()
                system_parts.append(f"\n\n## Weave Creation Guide\n\n{_skill}\n")
            except Exception:
                pass
        # Inject FABlib ground-truth method reference on any weave or slice
        # mutation request. Prevents hallucinated method names like
        # fablib.get_fab(), node.write_file(), network.add_interface() —
        # all verified to occur in live probes at every temperature.
        if _needs_fablib_ref:
            _ref = _load_fablib_ref()
            if _ref:
                # Cap at 4500 chars (~1100 tokens) — fits the standard-tier
                # budget comfortably and covers the FablibManager/Slice/Node
                # method lists plus the "common hallucinations" preamble.
                _ref_snippet = _ref[:4500]
                system_parts.append(
                    "\n\n## FABlib Ground Truth — Real Method Names\n\n"
                    "The following is the authoritative list of real FABlib methods. "
                    "If a method is NOT in this reference, it does NOT exist — do not "
                    "invent method names. This file is extracted directly from the "
                    "installed fabrictestbed-extensions package.\n\n"
                    f"```python\n{_ref_snippet}\n```\n"
                )
    elif profile["tier"] == "compact":
        system_parts = [LOOMAI_MODE_PROMPT]
    else:
        system_parts = [LOOMAI_MODE_EXTENDED]

    # Inject pre-fetched data
    if prefetched_tools:
        data_section = "\n\n## Current Data\n\n"
        for tool_name, result in prefetched_tools:
            data_section += f"**{tool_name}**:\n```json\n{result}\n```\n\n"
        system_parts.append(data_section)

    # Inject retrieved RAG context (from semantic search over the corpus)
    if rag_context_block:
        system_parts.append("\n\n" + rag_context_block)

    # C2: If destructive action detected, tell LLM to confirm
    if confirm_needed:
        system_parts.append(
            f"\n\n## Action Requires Confirmation\n"
            f"The user wants to execute: **{intent_tool}**({json.dumps(intent_args)})\n"
            f"This is a destructive operation. Ask the user to confirm before proceeding.\n"
            f"If they confirm, tell them to say 'yes, {intent_tool}' to execute."
        )

    # If template matched and needs confirmation, tell the LLM
    if template and template.get("confirm"):
        steps_desc = ", ".join(f"{s[0]}({s[1]})" for s in template["steps"][:5])
        system_parts.append(
            f"\n\n## Planned Action\n"
            f"The user wants to: {template['description']}\n"
            f"Steps: {steps_desc}\n"
            f"Ask the user to confirm before executing."
        )

    # Auto-activate agents based on intent when no agent is explicitly selected
    if not agent_id and use_full_llm_mode:
        import re as _re
        msg_lower = user_message.lower()
        if (_re.search(r"write|create|update|modify|build|edit.*\.py|fablib|weave|script|code|slice.*node", msg_lower)
                and intent_tool in ("create_weave", "read_file", "")):
            agent_id = "fablib-coder"

    if agent_id:
        agents = _load_agents()
        if agent_id in agents:
            system_parts.append(f"\n\n## Active Agent: {agents[agent_id]['name']}\n\n" + agents[agent_id]["prompt"])

    if slice_context:
        # Truncate very large contexts
        ctx = slice_context[:8000] if len(slice_context) > 8000 else slice_context
        system_parts.append(
            "\n\n## Current Slice Context\n\n"
            "The user is viewing this slice topology:\n\n"
            f"```json\n{ctx}\n```"
        )

    system_message = {"role": "system", "content": "\n".join(system_parts)}

    # Filter tools based on model capacity (full set for low-confidence/complex requests)
    max_tools = len(TOOL_SCHEMAS) if use_full_llm_mode else profile["max_tools"]
    tools_for_model = filter_tool_schemas(TOOL_SCHEMAS, max_tools)
    system_token_estimate = estimate_tokens(system_message["content"])

    tools_disabled = False  # Set True if model can't do tool calling

    async def generate():
        nonlocal tools_disabled, model
        import time as _time
        _start_time = _time.time()
        _tool_call_count = len(prefetched_tools)

        try:
            # Emit pre-fetched tool results to frontend
            for tool_name, result in prefetched_tools:
                if tool_name != "list_slices":  # Don't show background pre-fetch
                    yield f"data: {json.dumps({'tool_call': {'name': tool_name, 'arguments': intent_args}})}\n\n"
                    yield f"data: {json.dumps({'tool_result': {'name': tool_name, 'result': result[:2000]}})}\n\n"
                    yield f"data: {json.dumps({'execution_progress': f'Executed {tool_name}'})}\n\n"

            conversation = [system_message] + messages
            tool_round = 0

            while tool_round < _MAX_TOOL_ROUNDS:
                if await request.is_disconnected():
                    break
                if request_id and request_id in _cancelled_requests:
                    break

                # Trim conversation to fit model's context window
                trim_result = trim_conversation(conversation, system_token_estimate, profile)
                conversation = trim_result.messages

                # Warn user if context is nearly full (but not on the first message)
                if trim_result.near_full and tool_round > 0:
                    yield f"data: {json.dumps({'warning': 'Context window is nearly full. The conversation will be automatically compacted to continue.'})}\n\n"
                    # If context is full AND we've been trimming, stop tool calls
                    if trim_result.was_trimmed and tool_round >= 3:
                        ctx_full_msg = "\n\n[Context window full after repeated tool calls. Generating a summary.]\n"
                        yield f"data: {json.dumps({'content': ctx_full_msg})}\n\n"
                        break

                # Make LLM call (non-streaming for tool rounds, streaming for final)
                llm_body: dict[str, Any] = {
                    "model": model,
                    "messages": conversation,
                    "temperature": profile["temperature"],
                    "max_tokens": profile["max_output"],
                }
                # Only include tools if model supports them and they haven't been disabled
                if not tools_disabled and profile.get("supports_tools", True):
                    llm_body["tools"] = tools_for_model

                # Try non-streaming first to detect tool calls
                resp = await ai_client.post(
                    f"{server_url}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={**llm_body, "stream": False},
                    timeout=300.0,
                )

                # On server error or model-not-found, try fallbacks
                if resp.status_code >= 400 and resp.status_code != 200:
                    # On 404 (model not found), retry with default model
                    if resp.status_code == 404 and not use_nrp:
                        from app.settings_manager import get_default_model as _settings_default
                        fallback_model = _settings_default()
                        if fallback_model and fallback_model != model:
                            logger.info("Model %s returned 404, retrying with default %s", model, fallback_model)
                            yield f"data: {json.dumps({'content': f'[Model {model} unavailable, switching to {fallback_model}...] '})}\n\n"
                            llm_body["model"] = fallback_model
                            model = fallback_model
                            resp = await ai_client.post(
                                f"{server_url}/v1/chat/completions",
                                headers={
                                    "Authorization": f"Bearer {api_key}",
                                    "Content-Type": "application/json",
                                },
                                json={**llm_body, "stream": False},
                                timeout=300.0,
                            )

                    # On 5xx, fallback to NRP
                    if resp.status_code >= 500 and not use_nrp:
                        nrp_key = _get_nrp_api_key()
                        if nrp_key:
                            logger.info("Primary AI server returned %s, falling back to NRP", resp.status_code)
                            yield f"data: {json.dumps({'content': '[Falling back to NRP server...] '})}\n\n"
                            resp = await ai_client.post(
                                f"{_nrp_server_url()}/v1/chat/completions",
                                headers={
                                    "Authorization": f"Bearer {nrp_key}",
                                    "Content-Type": "application/json",
                                },
                                json={**llm_body, "stream": False},
                                timeout=300.0,
                            )

                if resp.status_code != 200:
                    error_text = resp.text[:300]
                    # Check if error is due to tools not being supported
                    if "tool" in error_text.lower() and not tools_disabled and "tools" in llm_body:
                        logger.info("Model %s may not support tools, retrying without", model)
                        tools_disabled = True
                        del llm_body["tools"]
                        no_tools_msg = '[This model does not support tool calling. I will suggest loomai CLI commands instead.]\n\n'
                        yield f"data: {json.dumps({'content': no_tools_msg})}\n\n"
                        continue  # Retry without tools
                    yield f"data: {json.dumps({'error': f'LLM error {resp.status_code}: {error_text}'})}\n\n"
                    return

                result = resp.json()
                choices = result.get("choices") or [{}]
                if not choices:
                    choices = [{}]
                choice = choices[0]
                msg = choice.get("message", {})
                finish = choice.get("finish_reason", "")

                # Check for tool calls (handle both finish_reason="tool_calls" and "length")
                tool_calls = msg.get("tool_calls")
                if tool_calls and finish in ("tool_calls", "length", "stop"):
                    # Append assistant message with tool calls to conversation.
                    # Strip reasoning_content / reasoning fields (NVIDIA Nemotron-style
                    # reasoning models return these as a separate channel — we never
                    # want them re-sent on subsequent turns because: (a) the server
                    # usually rejects unknown fields; (b) they inflate conversation
                    # tokens without contributing visible content; (c) the estimator
                    # wouldn't count them anyway, making budget math wrong.
                    clean_msg = {
                        k: v for k, v in msg.items()
                        if k in ("role", "content", "tool_calls", "tool_call_id", "name")
                    }
                    conversation.append(clean_msg)

                    consecutive_errors = 0
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        tc_name = fn.get("name", "")
                        tc_id = tc.get("id", "")
                        try:
                            tc_args = json.loads(fn.get("arguments", "{}"))
                        except json.JSONDecodeError:
                            tc_args = {}

                        # Notify frontend about tool call
                        yield f"data: {json.dumps({'tool_call': {'name': tc_name, 'arguments': tc_args}})}\n\n"

                        # Destructive-action safety gate — the LLM can decide
                        # on its own to call submit_slice/delete_slice. If the
                        # user's original message didn't authorize it, block
                        # the call and force the model to summarize and ask.
                        if is_destructive(tc_name) and not _user_authorized_destructive:
                            logger.info(
                                "BLOCKED destructive LLM-initiated tool call: %s (user did not authorize)",
                                tc_name,
                            )
                            tool_result = json.dumps({
                                "error": "DESTRUCTIVE_ACTION_BLOCKED",
                                "tool": tc_name,
                                "message": (
                                    f"{tc_name} is a destructive action and "
                                    f"the user's original message did not "
                                    f"explicitly authorize it. DO NOT RETRY "
                                    f"this tool. Instead, summarize what you "
                                    f"have built so far and ask the user to "
                                    f"explicitly confirm with keywords like "
                                    f"'submit', 'deploy', or 'delete' in "
                                    f"their next message."
                                ),
                            })
                        else:
                            # Per-tool outer timeout. SSH operations on cold VMs
                            # can easily exceed the old 5-min default (apt install,
                            # docker pull, kernel upgrade). For ssh_execute / vm
                            # file ops we honor the caller-specified timeout + 60s
                            # grace to cover transport overhead; for everything
                            # else we keep a conservative 5-min default.
                            if tc_name in ("ssh_execute", "write_vm_file", "read_vm_file", "reboot_and_wait"):
                                _requested = tc_args.get("timeout") if isinstance(tc_args, dict) else None
                                if isinstance(_requested, (int, float)) and _requested > 0:
                                    _outer_timeout = min(1860, int(_requested) + 60)
                                else:
                                    _outer_timeout = 660  # 600s default + 60s grace
                            else:
                                _outer_timeout = 300
                            try:
                                tool_result = await asyncio.wait_for(
                                    execute_tool(tc_name, tc_args), timeout=_outer_timeout
                                )
                            except asyncio.TimeoutError:
                                tool_result = json.dumps({
                                    "error": f"Tool {tc_name} timed out after {_outer_timeout}s",
                                    "hint": (
                                        "For long-running VM operations, set a larger "
                                        "'timeout' argument (max 1800s). For apt "
                                        "operations, include DEBIAN_FRONTEND=noninteractive "
                                        "and use apt-get -y -qq to avoid interactive prompts."
                                    ) if tc_name in ("ssh_execute", "write_vm_file") else None,
                                })
                                logger.warning("Tool %s timed out after %ds", tc_name, _outer_timeout)

                        summary = _tool_summary(tc_name, tc_args, tool_result)

                        # Track consecutive errors to break infinite retry loops
                        if tool_result and '"error"' in tool_result:
                            consecutive_errors += 1
                        else:
                            consecutive_errors = 0

                        # Notify frontend about tool result with summary
                        yield f"data: {json.dumps({'tool_result': {'name': tc_name, 'result': tool_result[:2000], 'summary': summary}})}\n\n"

                        # Add tool result to conversation (truncated per model profile)
                        # search_examples returns inline code — give it more space
                        tool_max = profile["tool_result_max"]
                        if tc_name == "search_examples":
                            tool_max = max(tool_max, 6000)  # examples need room for code
                        tool_result = tool_result or ""
                        trimmed_result = tool_result[:tool_max] if len(tool_result) > tool_max else tool_result
                        conversation.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": trimmed_result,
                        })

                    tool_round += 1
                    _tool_call_count += len(tool_calls)

                    # Break out if too many consecutive errors (model is stuck)
                    if consecutive_errors >= 3:
                        err_break_msg = "\n\n[Multiple tool calls failed. Please try a different approach.]\n"
                        yield f"data: {json.dumps({'content': err_break_msg})}\n\n"
                        break

                    continue

                # No tool calls — stream the final text response
                # Re-do the call with streaming for smooth output
                async with ai_client.stream(
                    "POST",
                    f"{server_url}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={**llm_body, "stream": True},
                ) as stream_resp:
                    if stream_resp.status_code != 200:
                        error_body = ""
                        async for chunk in stream_resp.aiter_text():
                            error_body += chunk
                        yield f"data: {json.dumps({'error': f'LLM error {stream_resp.status_code}: {error_body[:200]}'})}\n\n"
                        return

                    async for line in stream_resp.aiter_lines():
                        if await request.is_disconnected():
                            break
                        if request_id and request_id in _cancelled_requests:
                            break
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            chunk_choices = chunk.get("choices") or [{}]
                            delta = (chunk_choices[0] if chunk_choices else {}).get("delta", {})

                            # Check for tool calls in streaming response too
                            if delta.get("tool_calls"):
                                # Fall back to non-streaming for tool handling
                                # This shouldn't normally happen since we already
                                # checked non-streaming, but handle gracefully
                                break

                            content = delta.get("content")
                            if content:
                                yield f"data: {json.dumps({'content': content})}\n\n"
                        except json.JSONDecodeError:
                            continue

                # C5: Emit usage stats
                elapsed_ms = int((_time.time() - _start_time) * 1000)
                conv_tokens = estimate_conversation_tokens(conversation)
                usage_data = {"tokens": conv_tokens, "tool_calls": _tool_call_count, "duration_ms": elapsed_ms}
                yield f"data: {json.dumps({'usage': usage_data})}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Exhausted tool rounds — ask LLM to summarize progress for continuity
            # Append a system nudge so the LLM wraps up gracefully
            conversation.append({
                "role": "user",
                "content": (
                    "[System: Tool call limit reached. Please summarize what you've accomplished so far "
                    "and what steps remain. The user can click 'Continue' to resume.]"
                ),
            })
            # Make one final LLM call (without tools) to get a summary
            try:
                summary_body = {
                    "model": model,
                    "messages": conversation,
                    "temperature": profile["temperature"],
                    "max_tokens": min(profile["max_output"], 1024),
                    "stream": True,
                }
                async with ai_client.stream(
                    "POST",
                    f"{server_url}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=summary_body,
                ) as summary_resp:
                    if summary_resp.status_code == 200:
                        async for line in summary_resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                                content = delta.get("content")
                                if content:
                                    yield f"data: {json.dumps({'content': content})}\n\n"
                            except json.JSONDecodeError:
                                continue
            except Exception:
                pass

            # Emit tool_limit_reached so frontend can show Continue button
            yield f"data: {json.dumps({'tool_limit_reached': True, 'tool_rounds_used': tool_round})}\n\n"
            yield "data: [DONE]\n\n"

        except httpx.ReadError:
            pass
        except Exception as e:
            logger.exception("Chat stream error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            if request_id:
                _cancelled_requests.discard(request_id)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/api/ai/chat/stop")
async def chat_stop(request: Request):
    body = await request.json()
    request_id = body.get("request_id", "")
    if request_id:
        _cancelled_requests.add(request_id)
        return {"status": "stopped"}
    return {"status": "not_found"}
