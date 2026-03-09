"""VM Recipe management and execution API routes.

Recipes are on-demand script packages applied to running VMs.
A recipe is detected by having recipe.json in the artifact dir.

Storage: FABRIC_STORAGE_DIR/my_artifacts/{name}/
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.slice_registry import resolve_slice_name
from app.user_context import get_user_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/recipes", tags=["recipes"])


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------

def _recipes_dir() -> str:
    from app.user_context import get_artifacts_dir
    return get_artifacts_dir()


def _builtin_recipes_dir() -> str:
    """Return the path to the builtin VM recipes shipped with the repo."""
    base = os.path.dirname(__file__)
    for levels in [("..", ".."), ("..", "..", "..")]:
        candidate = os.path.realpath(os.path.join(base, *levels, "slice-libraries", "vm_recipes"))
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(base, "..", "..", "slice-libraries", "vm_recipes")


def _sanitize_name(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.strip())
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid recipe name")
    return safe


def _validate_path(base: str, name: str) -> str:
    path = os.path.realpath(os.path.join(base, name))
    if not path.startswith(os.path.realpath(base)):
        raise HTTPException(status_code=400, detail="Invalid recipe name")
    return path


# ---------------------------------------------------------------------------
# Builtin recipe helpers
# ---------------------------------------------------------------------------

def _builtin_hash(builtin_dir: str) -> str:
    """Compute a hash of a builtin recipe directory for change detection."""
    hashable: dict[str, Any] = {}
    recipe_path = os.path.join(builtin_dir, "recipe.json")
    if os.path.isfile(recipe_path):
        with open(recipe_path) as f:
            hashable["recipe"] = json.load(f)
    scripts_dir = os.path.join(builtin_dir, "scripts")
    if os.path.isdir(scripts_dir):
        scripts = []
        for fn in sorted(os.listdir(scripts_dir)):
            fp = os.path.join(scripts_dir, fn)
            if os.path.isfile(fp):
                with open(fp) as f:
                    scripts.append({"filename": fn, "content": f.read()})
        hashable["_scripts"] = scripts
    else:
        hashable["_scripts"] = []
    return hashlib.sha256(json.dumps(hashable, sort_keys=True).encode()).hexdigest()[:16]


def _list_builtin_recipes() -> list[dict[str, Any]]:
    """Scan the builtin VM recipes directory and return info for each."""
    bdir = os.path.realpath(_builtin_recipes_dir())
    if not os.path.isdir(bdir):
        return []
    results = []
    for entry in sorted(os.listdir(bdir)):
        entry_dir = os.path.join(bdir, entry)
        recipe_path = os.path.join(entry_dir, "recipe.json")
        if os.path.isfile(recipe_path):
            with open(recipe_path) as f:
                data = json.load(f)
            data["_dir"] = entry_dir
            data["_entry"] = entry
            results.append(data)
    return results


def _seed_if_needed() -> None:
    """Ensure the recipes storage directory exists.

    Built-in recipe seeding is disabled — users create or download
    artifacts via the marketplace.
    """
    rdir = _recipes_dir()
    os.makedirs(rdir, exist_ok=True)


def _match_image(image: str, patterns: dict[str, str]) -> str | None:
    """Match a VM image string against recipe image_patterns.

    Returns the script filename if matched, None otherwise.
    Supports '*' wildcard for match-all.
    """
    image_lower = image.lower()
    for key, script in patterns.items():
        if key == "*":
            return script
        if key.lower() in image_lower:
            return script
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def list_recipes() -> list[dict[str, Any]]:
    """List recipe artifacts (dirs containing recipe.json)."""
    _seed_if_needed()
    rdir = _recipes_dir()
    if not os.path.isdir(rdir):
        return []
    results = []
    for entry in sorted(os.listdir(rdir)):
        entry_dir = os.path.join(rdir, entry)
        if not os.path.isdir(entry_dir):
            continue
        recipe_path = os.path.join(entry_dir, "recipe.json")
        if not os.path.isfile(recipe_path):
            continue  # Not a recipe artifact

        try:
            with open(recipe_path) as f:
                data = json.load(f)
            # Auto-populate required fields
            changed = False
            if "name" not in data:
                data["name"] = entry
                changed = True
            if changed:
                with open(recipe_path, "w") as f:
                    json.dump(data, f, indent=2)
            results.append({
                "name": data.get("name", entry),
                "version": data.get("version", ""),
                "description": data.get("description", ""),
                "image_patterns": data.get("image_patterns", {}),
                "starred": data.get("starred", True),
                "dir_name": entry,
            })
        except Exception:
            pass
    return results


@router.get("/{name}")
def get_recipe(name: str) -> dict[str, Any]:
    """Get full recipe detail including steps."""
    _seed_if_needed()
    safe = _sanitize_name(name)
    rdir = _recipes_dir()
    recipe_dir = _validate_path(rdir, safe)
    recipe_path = os.path.join(recipe_dir, "recipe.json")
    if not os.path.isfile(recipe_path):
        raise HTTPException(status_code=404, detail=f"Recipe '{name}' not found")
    with open(recipe_path) as f:
        data = json.load(f)
    data["dir_name"] = safe
    return data


@router.patch("/{name}")
def update_recipe(name: str, body: dict[str, Any]) -> dict[str, Any]:
    """Update mutable recipe fields (currently only 'starred')."""
    _seed_if_needed()
    safe = _sanitize_name(name)
    rdir = _recipes_dir()
    recipe_dir = _validate_path(rdir, safe)
    recipe_path = os.path.join(recipe_dir, "recipe.json")
    if not os.path.isfile(recipe_path):
        raise HTTPException(status_code=404, detail=f"Recipe '{name}' not found")
    with open(recipe_path) as f:
        data = json.load(f)
    if "starred" in body:
        data["starred"] = bool(body["starred"])
    with open(recipe_path, "w") as f:
        json.dump(data, f, indent=2)
    data["dir_name"] = safe
    return data


@router.post("/{name}/execute/{slice_name}/{node_name}")
async def execute_recipe(name: str, slice_name: str, node_name: str):
    """Upload scripts and execute a recipe on a VM node, streaming SSE progress."""
    slice_name = resolve_slice_name(slice_name)
    _seed_if_needed()
    safe = _sanitize_name(name)
    rdir = _recipes_dir()
    recipe_dir = _validate_path(rdir, safe)
    recipe_path = os.path.join(recipe_dir, "recipe.json")
    if not os.path.isfile(recipe_path):
        raise HTTPException(status_code=404, detail=f"Recipe '{name}' not found")

    with open(recipe_path) as f:
        recipe = json.load(f)

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _emit(event_type: str, data: dict):
        """Put an SSE-formatted message onto the queue."""
        line = json.dumps({"event": event_type, **data})
        queue.put_nowait(f"data: {line}\n\n")

    def _do():
        from app.routes.files import _get_node
        from app.fablib_manager import get_fablib

        def _get_node_fresh(sn: str, nn: str):
            """Get a fresh node object (new SSH connection after reboot)."""
            fablib = get_fablib()
            from app.slice_registry import get_slice_uuid
            uuid = get_slice_uuid(sn)
            if uuid:
                try:
                    sl = fablib.get_slice(slice_id=uuid)
                    return sl.get_node(nn)
                except Exception:
                    pass
            sl = fablib.get_slice(sn)
            return sl.get_node(nn)

        node_obj = _get_node(slice_name, node_name)

        _emit("step", {"message": f"Connecting to {node_name}...", "status": "ok"})

        # Determine image and match script
        image = ""
        try:
            image = node_obj.get_image() or ""
        except Exception:
            pass
        if not image:
            try:
                from app.fablib_manager import get_fablib
                from app.slice_registry import get_slice_uuid
                fablib = get_fablib()
                uuid = get_slice_uuid(slice_name)
                if uuid:
                    sl = fablib.get_slice(slice_id=uuid)
                    n = sl.get_node(node_name)
                    image = n.get_image() or ""
            except Exception:
                pass

        _emit("step", {"message": f"Detected image: {image}", "status": "ok"})

        patterns = recipe.get("image_patterns", {})
        script = _match_image(image, patterns)
        if not script:
            _emit("error", {"message": f"No compatible script for image '{image}'. Supported: {', '.join(patterns.keys())}"})
            _emit("done", {"status": "error"})
            queue.put_nowait(None)
            return

        _emit("step", {"message": f"Matched script: {script}", "status": "ok"})

        results = []
        recipe_name_safe = safe
        remote_dir = f"~/.fabric/recipes/{recipe_name_safe}"

        # Resolve ~ to absolute path for SFTP uploads
        home_stdout, _ = node_obj.execute("echo $HOME", quiet=True)
        home_dir = (home_stdout or "").strip() or "/root"
        remote_dir_abs = remote_dir.replace("~", home_dir)

        for step in recipe.get("steps", []):
            step_type = step.get("type", "")

            if step_type == "upload_scripts":
                _emit("step", {"message": "Uploading scripts...", "status": "running"})
                try:
                    node_obj.execute(f"mkdir -p {remote_dir_abs}", quiet=True)
                    local_scripts = os.path.join(recipe_dir, "scripts")
                    if os.path.isdir(local_scripts):
                        for fn in os.listdir(local_scripts):
                            local_file = os.path.join(local_scripts, fn)
                            if os.path.isfile(local_file):
                                node_obj.upload_file(local_file, f"{remote_dir_abs}/{fn}")
                                _emit("step", {"message": f"  Uploaded {fn}", "status": "ok"})
                    results.append({"type": "upload_scripts", "status": "ok"})
                    _emit("step", {"message": "Scripts uploaded successfully", "status": "ok"})
                except Exception as e:
                    results.append({"type": "upload_scripts", "status": "error", "detail": str(e)})
                    _emit("error", {"message": f"Upload failed: {e}"})

            elif step_type == "execute":
                cmd = step.get("command", "")
                cmd = cmd.replace("{script}", script)
                _emit("step", {"message": f"Running: {cmd}", "status": "running"})
                try:
                    stdout, stderr = node_obj.execute(cmd, quiet=True)
                    output = (stdout or "") + (stderr or "")
                    if output.strip():
                        # Send output in chunks to avoid huge SSE messages
                        for line in output.strip().split("\n"):
                            _emit("output", {"message": line})
                    results.append({"type": "execute", "status": "ok", "detail": output.strip()})
                    _emit("step", {"message": "Command completed", "status": "ok"})
                except Exception as e:
                    results.append({"type": "execute", "status": "error", "detail": str(e)})
                    _emit("error", {"message": f"Command failed: {e}"})

            elif step_type == "reboot_and_wait":
                timeout_secs = step.get("timeout", 300)
                _emit("step", {"message": "Rebooting VM...", "status": "running"})
                try:
                    node_obj.execute("sudo reboot", quiet=True)
                except Exception:
                    pass  # connection drops on reboot — expected
                _emit("step", {"message": f"Waiting for VM to come back (up to {timeout_secs}s)...", "status": "running"})
                # Wait for the VM to come back online
                start = time.time()
                reconnected = False
                while time.time() - start < timeout_secs:
                    time.sleep(10)
                    elapsed = int(time.time() - start)
                    try:
                        # Re-acquire the node object (fresh SSH connection)
                        node_obj = _get_node_fresh(slice_name, node_name)
                        stdout, _ = node_obj.execute("uptime", quiet=True)
                        _emit("step", {"message": f"VM is back online after {elapsed}s: {(stdout or '').strip()}", "status": "ok"})
                        # Re-resolve home dir in case it changed
                        home_stdout, _ = node_obj.execute("echo $HOME", quiet=True)
                        home_dir = (home_stdout or "").strip() or "/root"
                        remote_dir_abs = remote_dir.replace("~", home_dir)
                        reconnected = True
                        break
                    except Exception:
                        _emit("output", {"message": f"  ...waiting ({elapsed}s elapsed)"})
                if reconnected:
                    results.append({"type": "reboot_and_wait", "status": "ok"})
                else:
                    results.append({"type": "reboot_and_wait", "status": "error", "detail": f"VM did not come back within {timeout_secs}s"})
                    _emit("error", {"message": f"VM did not come back within {timeout_secs}s"})

            elif step_type == "execute_boot_config":
                _emit("step", {"message": "Re-running boot config...", "status": "running"})
                try:
                    from app.routes.files import _load_boot_config, _storage_dir, _safe_path
                    bc = _load_boot_config(slice_name, node_name)
                    base = _storage_dir()
                    # Process uploads
                    for upload in bc.get("uploads", []):
                        local_path = _safe_path(base, upload["source"])
                        dest = upload["dest"].replace("~", home_dir)
                        parent = os.path.dirname(dest)
                        if parent:
                            node_obj.execute(f"mkdir -p {parent}", quiet=True)
                        if os.path.isdir(local_path):
                            node_obj.upload_directory(local_path, dest)
                        elif os.path.isfile(local_path):
                            node_obj.upload_file(local_path, dest)
                    # Process network config
                    for net in sorted(bc.get("network", []), key=lambda n: n.get("order", 0)):
                        iface = net["iface"]
                        mode = net.get("mode", "auto")
                        if mode == "auto":
                            cmd = f"sudo dhclient {iface}"
                        else:
                            ip_addr = net.get("ip", "")
                            subnet = net.get("subnet", "24")
                            cmd = f"sudo ip addr add {ip_addr}/{subnet} dev {iface} && sudo ip link set {iface} up"
                            gw = net.get("gateway")
                            if gw:
                                cmd += f" && sudo ip route add default via {gw} dev {iface}"
                        stdout, stderr = node_obj.execute(cmd, quiet=True)
                        _emit("output", {"message": f"  Network {iface}: {(stdout or '').strip()}"})
                    # Process commands
                    for cmd_entry in sorted(bc.get("commands", []), key=lambda c: c.get("order", 0)):
                        stdout, stderr = node_obj.execute(cmd_entry["command"], quiet=True)
                        output = (stdout or "").strip()
                        if output:
                            _emit("output", {"message": output})
                    results.append({"type": "execute_boot_config", "status": "ok"})
                    _emit("step", {"message": "Boot config re-applied", "status": "ok"})
                except Exception as e:
                    results.append({"type": "execute_boot_config", "status": "error", "detail": str(e)})
                    _emit("error", {"message": f"Boot config failed: {e}"})

        # Handle post_actions
        for action in recipe.get("post_actions", []):
            if action == "reboot":
                _emit("step", {"message": "Rebooting VM...", "status": "running"})
                try:
                    node_obj.execute("sudo reboot", quiet=True)
                    results.append({"type": "reboot", "status": "ok", "detail": "Reboot initiated"})
                except Exception:
                    results.append({"type": "reboot", "status": "ok", "detail": "Reboot initiated (connection closed)"})
                _emit("step", {"message": "Reboot initiated", "status": "ok"})

        has_error = any(r["status"] == "error" for r in results)
        has_ok = any(r["status"] == "ok" for r in results)
        if has_error and has_ok:
            status = "partial"
        elif has_error:
            status = "error"
        else:
            status = "ok"

        _emit("done", {"status": status, "results": results})
        queue.put_nowait(None)

    async def _stream():
        task = asyncio.get_event_loop().run_in_executor(None, _do)
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                # Send SSE keepalive comment to prevent proxy read-timeout
                yield ": keepalive\n\n"
                continue
            if msg is None:
                break
            yield msg
        await task  # propagate exceptions

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
