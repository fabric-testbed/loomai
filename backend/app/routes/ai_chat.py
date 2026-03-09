"""Streaming agentic AI chat — proxies to FABRIC LLMs with tool calling."""
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

from app.routes.config import _get_ai_api_key

logger = logging.getLogger(__name__)

router = APIRouter()

AI_SERVER_URL = "https://ai.fabric-testbed.net"
_MAX_TOOL_ROUNDS = 50  # generous limit; stops only truly runaway loops

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_AI_TOOLS_DIR = os.path.join(_APP_ROOT, "ai-tools")
_FABRIC_AI_MD_PATH = os.path.join(_AI_TOOLS_DIR, "shared", "FABRIC_AI.md")
_AGENTS_DIR = os.path.join(_AI_TOOLS_DIR, "opencode", "agents")

# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------
_system_prompt_cache: str | None = None
_agents_cache: dict[str, dict] | None = None


def _load_system_prompt() -> str:
    global _system_prompt_cache
    if _system_prompt_cache is None:
        try:
            with open(_FABRIC_AI_MD_PATH, "r") as f:
                _system_prompt_cache = f.read()
        except Exception:
            _system_prompt_cache = "You are a helpful FABRIC testbed assistant."
    return _system_prompt_cache


def _load_agents() -> dict[str, dict]:
    global _agents_cache
    if _agents_cache is not None:
        return _agents_cache

    agents: dict[str, dict] = {}
    if not os.path.isdir(_AGENTS_DIR):
        _agents_cache = agents
        return agents

    for fname in sorted(os.listdir(_AGENTS_DIR)):
        if not fname.endswith(".md"):
            continue
        agent_id = fname[:-3]
        if agent_id in ("ai-tools-evaluator",):
            continue
        fpath = os.path.join(_AGENTS_DIR, fname)
        try:
            with open(fpath, "r") as f:
                content = f.read()
            if content.startswith("name:"):
                parts = content.split("---", 1)
                header = parts[0]
                body = parts[1].strip() if len(parts) > 1 else ""
                name = desc = ""
                for line in header.strip().splitlines():
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip()
                    elif line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip()
                agents[agent_id] = {"name": name or agent_id, "description": desc, "prompt": body}
        except Exception:
            logger.warning("Failed to load agent %s", fname)

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
            "description": "List available slice templates that can be loaded as new slices.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_template",
            "description": "Load a slice template as a new draft slice.",
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
                    "path": {"type": "string", "description": "Relative path within user storage (e.g. 'my_artifacts/my_weave/deploy.sh')"},
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
            "description": "Execute a command on a VM node via SSH. The slice must be in StableOK state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {"type": "string", "description": "Name of the slice"},
                    "node_name": {"type": "string", "description": "Name of the node"},
                    "command": {"type": "string", "description": "Shell command to execute on the VM"},
                },
                "required": ["slice_name", "node_name", "command"],
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
]


# ---------------------------------------------------------------------------
# Tool execution — calls existing backend functions
# ---------------------------------------------------------------------------

def _run_sync(func, *args, **kwargs) -> Any:
    """Run a sync function and return its result (for use in async context)."""
    return func(*args, **kwargs)


async def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool and return the result as a JSON string."""
    try:
        if name == "list_slices":
            from app.routes.slices import list_slices
            result = await list_slices()
            # Trim to essential fields
            return json.dumps([{
                "name": s.get("name"), "state": s.get("state"),
                "nodes": len(s.get("nodes", [])),
                "lease_end": s.get("lease_end"),
            } for s in result], default=str)

        elif name == "get_slice":
            from app.routes.slices import get_slice
            result = await get_slice(arguments["slice_name"])
            return json.dumps(result, default=str)

        elif name == "query_sites":
            from app.routes.resources import list_sites
            sites = await list_sites()
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
                "nodes": t.get("node_count", 0),
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
            body = VmExecBody(command=arguments["command"])
            result = await execute_on_vm(arguments["slice_name"], arguments["node_name"], body)
            # Truncate long output
            stdout = result.get("stdout", "")[:8000]
            stderr = result.get("stderr", "")[:2000]
            return json.dumps({"stdout": stdout, "stderr": stderr}, default=str)

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

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as e:
        logger.warning("Tool %s failed: %s", name, e)
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Streaming agentic chat
# ---------------------------------------------------------------------------

# Track active streaming requests for cancellation
_active_clients: dict[str, httpx.AsyncClient] = {}


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
    api_key = _get_ai_api_key()
    if not api_key:
        return StreamingResponse(
            iter([b'data: {"error": "AI API key not configured"}\n\n']),
            media_type="text/event-stream",
        )

    body = await request.json()
    messages = body.get("messages", [])
    model = body.get("model", "qwen3-coder-30b")
    agent_id = body.get("agent")
    slice_context = body.get("slice_context")
    request_id = body.get("request_id", "")

    # Build system prompt
    system_parts = [_load_system_prompt()]

    # Tool-use instructions
    system_parts.append(
        "\n\n## Tool Use\n\n"
        "You have access to FABRIC tools that let you:\n"
        "- Query sites and manage slices (create, submit, refresh, validate, delete, renew)\n"
        "- Build topologies (add/remove/update nodes, components, networks)\n"
        "- Work with templates (list, load, save as template)\n"
        "- Read/write files on the container filesystem (create artifacts, scripts, configs)\n"
        "- Manage artifacts (list local, publish to FABRIC marketplace)\n"
        "- Execute commands on VMs via SSH and read/write files on VMs via SFTP\n"
        "- List and manage recipes for VM configuration\n"
        "- Control JupyterLab (start, stop, status)\n\n"
        "Use tools when the user asks to perform operations. After using tools, summarize what you did clearly.\n"
        "For creating artifacts, write files under 'my_artifacts/<artifact_name>/' in the container filesystem."
    )

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

    async def generate():
        client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0))
        if request_id:
            _active_clients[request_id] = client

        try:
            conversation = [system_message] + messages
            tool_round = 0

            while tool_round < _MAX_TOOL_ROUNDS:
                if await request.is_disconnected():
                    break

                # Make LLM call (non-streaming for tool rounds, streaming for final)
                llm_body: dict[str, Any] = {
                    "model": model,
                    "messages": conversation,
                    "tools": TOOL_SCHEMAS,
                    "temperature": 0.7,
                    "max_tokens": 4096,
                }

                # Try non-streaming first to detect tool calls
                resp = await client.post(
                    f"{AI_SERVER_URL}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={**llm_body, "stream": False},
                    timeout=120.0,
                )

                if resp.status_code != 200:
                    yield f"data: {json.dumps({'error': f'LLM error {resp.status_code}: {resp.text[:200]}'})}\n\n"
                    return

                result = resp.json()
                choice = result.get("choices", [{}])[0]
                msg = choice.get("message", {})
                finish = choice.get("finish_reason", "")

                # Check for tool calls
                tool_calls = msg.get("tool_calls")
                if tool_calls and finish == "tool_calls":
                    # Append assistant message with tool calls to conversation
                    conversation.append(msg)

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

                        # Execute the tool
                        tool_result = await execute_tool(tc_name, tc_args)

                        # Notify frontend about tool result
                        yield f"data: {json.dumps({'tool_result': {'name': tc_name, 'result': tool_result[:2000]}})}\n\n"

                        # Add tool result to conversation
                        conversation.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": tool_result,
                        })

                    tool_round += 1
                    continue

                # No tool calls — stream the final text response
                # Re-do the call with streaming for smooth output
                async with client.stream(
                    "POST",
                    f"{AI_SERVER_URL}/v1/chat/completions",
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
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})

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

                yield "data: [DONE]\n\n"
                return

            # Exhausted tool rounds
            limit_msg = json.dumps({"content": "\n\n*[Reached maximum tool call limit]*"})
            yield f"data: {limit_msg}\n\n"
            yield "data: [DONE]\n\n"

        except httpx.ReadError:
            pass
        except Exception as e:
            logger.exception("Chat stream error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            if request_id and request_id in _active_clients:
                del _active_clients[request_id]
            await client.aclose()

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/api/ai/chat/stop")
async def chat_stop(request: Request):
    body = await request.json()
    request_id = body.get("request_id", "")
    if request_id in _active_clients:
        try:
            await _active_clients[request_id].aclose()
        except Exception:
            pass
        if request_id in _active_clients:
            del _active_clients[request_id]
        return {"status": "stopped"}
    return {"status": "not_found"}
