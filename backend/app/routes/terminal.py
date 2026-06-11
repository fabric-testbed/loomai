"""WebSocket SSH terminal endpoint using paramiko through FABRIC bastion."""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import shlex
import struct
import subprocess
import termios
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from pydantic import BaseModel
from app.tool_installer import AI_TOOLS_DIR, get_tool_env
import paramiko

from app import auth as _auth
from app import terminal_auth
from app import terminal_sessions as ts

from app.slice_registry import resolve_slice_name
from app.fablib_manager import (
    DEFAULT_CONFIG_DIR,
    get_fablib,
    get_default_slice_key_path,
    get_slice_key_path,
)
from app.settings_manager import (
    get_bastion_username as _settings_bastion_username,
    get_host as _settings_host,
)
from app.user_context import get_user_storage

router = APIRouter()


# ---------------------------------------------------------------------------
# In-process terminal sessions (JupyterLab/terminado-style) — control + attach
# ---------------------------------------------------------------------------

# Plain (non-login) interactive bash: a login shell (-l) re-initializes PATH from
# /etc/profile and drops the lazy-installed AI-tools dir, so `claude`/`codex`
# wouldn't be found. The PTY makes it interactive; the env (incl. the tools PATH)
# is inherited.
_LOCAL_COMMAND = ["/bin/bash"]


class CreateTerminalBody(BaseModel):
    type: str = "local"
    cwd: Optional[str] = None
    label: Optional[str] = None
    # For type == "ssh":
    sliceName: Optional[str] = None
    nodeName: Optional[str] = None
    managementIp: Optional[str] = None
    # For type == "chameleon":
    chameleonInstanceId: Optional[str] = None
    chameleonSite: Optional[str] = None


def _default_terminal_cwd() -> str:
    # Open in the canonical workspace root (/home/fabric/work), where the active
    # user's fabric_config/my_artifacts/my_slices/notebooks are exposed via
    # symlinks — not the internal per-user .loomai/users/<uuid> directory.
    d = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
    if d and os.path.isdir(d):
        return d
    return os.path.expanduser("~")


def _lookup_node_ssh(slice_name: str, node_name: str) -> tuple[str, str]:
    """Resolve (management_ip, username) for a FABRIC node via FABlib (blocking)."""
    fablib = get_fablib()
    from app.slice_registry import get_slice_uuid
    uuid = get_slice_uuid(slice_name)
    slice_obj = None
    if uuid:
        try:
            slice_obj = fablib.get_slice(slice_id=uuid)
        except Exception:
            slice_obj = None
    if slice_obj is None:
        slice_obj = fablib.get_slice(slice_name)
    node = slice_obj.get_node(node_name)
    return str(node.get_management_ip()), node.get_username()


def _build_node_ssh_argv(slice_name: str, management_ip: str, username: str) -> list[str]:
    """Build an `ssh` argv that reaches a FABRIC node through the bastion.

    Run inside a server-held PTY, this is what gives JupyterLab-style remote
    persistence: the `ssh` process (and the remote shell/program it's running)
    stays alive in the PTY across browser reloads, so reattaching lands back in
    the *same* remote session — not a fresh one.
    """
    cfg = _get_ssh_config(slice_name=slice_name)
    # `-W [%h]:%p` (bracketed) so IPv6 management IPs forward correctly — a bare
    # `%h:%p` makes ssh mis-parse the IPv6 colons ("Bad stdio forwarding spec").
    proxy = (
        f"ssh -i {shlex.quote(cfg['bastion_key'])} "
        "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "
        f"-W [%h]:%p {shlex.quote(cfg['bastion_username'])}@{shlex.quote(cfg['bastion_host'])}"
    )
    return [
        "ssh", "-tt",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
        "-o", "IdentitiesOnly=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-i", cfg["slice_key"],
        "-o", f"ProxyCommand={proxy}",
        f"{username}@{management_ip}",
    ]


def _lookup_chameleon_record_key_name(site: str, instance_id: str) -> str:
    try:
        from app.routes.chameleon import _chameleon_slices, _chameleon_slices_lock
        with _chameleon_slices_lock:
            records = list(_chameleon_slices.values())
    except Exception:
        return ""

    def _site_matches(record: dict) -> bool:
        record_site = str(record.get("site") or "")
        sites = record.get("sites")
        return not record_site or record_site == site or (isinstance(sites, list) and site in sites)

    def _key_from(item: dict) -> str:
        return str(item.get("key_name") or item.get("keypair") or item.get("keypair_name") or "").strip()

    for record in records:
        if not isinstance(record, dict) or not _site_matches(record):
            continue
        for node in record.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            node_instance_id = str(node.get("instance_id") or node.get("provider_id") or "")
            if node_instance_id == instance_id:
                key_name = _key_from(node)
                if key_name:
                    return key_name
        for resource in record.get("resources") or []:
            if not isinstance(resource, dict):
                continue
            resource_ids = {
                str(resource.get("instance_id") or ""),
                str(resource.get("provider_id") or ""),
                str(resource.get("id") or ""),
            }
            if instance_id in resource_ids:
                key_name = _key_from(resource)
                if key_name:
                    return key_name
    return ""


def _lookup_chameleon_ip(site: str, instance_id: str) -> tuple[str, str, str]:
    """Resolve (floating_ip, name, key_name) for a Chameleon instance."""
    from app.chameleon_manager import get_session
    session = get_session(site)
    result = session.api_get("compute", f"/servers/{instance_id}")
    srv = result.get("server", result)
    ip = None
    for _net, addrs in srv.get("addresses", {}).items():
        for addr in addrs:
            if addr.get("OS-EXT-IPS:type") == "floating":
                ip = addr["addr"]
                break
        if ip:
            break
    key_name = str(srv.get("key_name") or srv.get("OS-EXT-SRV-ATTR:key_name") or "").strip()
    if not key_name:
        key_name = _lookup_chameleon_record_key_name(site, instance_id)
    return ip or "", srv.get("name", "instance"), key_name


def _missing_chameleon_key_argv(site: str, ip: str, key_name: str) -> list[str]:
    if key_name:
        message = (
            f"[terminal] Chameleon instance was created with Nova keypair '{key_name}', "
            "but LoomAI does not have a matching private key.\n"
            f"[terminal] Add the matching private key as fabric_config/chameleon_key_{key_name} "
            "or set Chameleon SSH Key to that private key path, then open SSH again.\n"
        )
    else:
        message = (
            "[terminal] Chameleon instance does not report a Nova keypair.\n"
            "[terminal] If it was launched without key_name, public-key SSH cannot work; "
            "recreate it after selecting a Chameleon default SSH key.\n"
        )
    return ["/bin/bash", "-lc", f"printf %s {shlex.quote(message)}; exit 255"]


def _build_chameleon_ssh_argv(site: str, ip: str, key_name: str = "") -> list[str]:
    """ssh argv to a Chameleon instance (user `cc`). Held in a server-side PTY,
    so the remote shell persists across reloads — same as FABRIC nodes."""
    from app.routes.chameleon import get_chameleon_key_path
    key_name = str(key_name or "").strip()
    if not key_name:
        return _missing_chameleon_key_argv(site, ip, key_name)
    key_path = get_chameleon_key_path(site, key_name)
    if not key_path:
        return _missing_chameleon_key_argv(site, ip, key_name)
    argv = [
        "ssh", "-tt",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
        "-o", "IdentitiesOnly=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-i", key_path,
        f"cc@{ip}",
    ]
    return argv


@router.post("/api/terminals")
async def create_terminal(body: CreateTerminalBody):
    """Create a server-held terminal session and return its id + attach ticket.

    type="local": a shell in the container. type="ssh": a shell running `ssh`
    to a FABRIC node (held server-side, so the remote session persists across
    reloads).
    """
    if body.type == "local":
        cwd = body.cwd if (body.cwd and os.path.isdir(body.cwd)) else _default_terminal_cwd()
        # Put the lazy-installed AI tools (claude, codex, aider, …) on PATH so
        # they're runnable from the local shell, like the old container terminal.
        local_env = {"PATH": get_tool_env().get("PATH", os.environ.get("PATH", ""))}
        session = ts.create(type="local", command=_LOCAL_COMMAND,
                            label=body.label or "Local", cwd=cwd, env=local_env)
    elif body.type == "ssh":
        if not body.sliceName or not body.nodeName:
            raise HTTPException(status_code=400, detail="sliceName and nodeName are required for ssh terminals")
        loop = asyncio.get_event_loop()
        try:
            management_ip, username = await loop.run_in_executor(
                None, _lookup_node_ssh, body.sliceName, body.nodeName,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Could not resolve node {body.nodeName}: {e}")
        if not management_ip or not username:
            raise HTTPException(status_code=502, detail=f"Node {body.nodeName} has no management IP / username yet")
        argv = _build_node_ssh_argv(body.sliceName, management_ip, username)
        session = ts.create(type="ssh", command=argv, label=body.label or body.nodeName)
    elif body.type == "chameleon":
        if not body.chameleonInstanceId or not body.chameleonSite:
            raise HTTPException(status_code=400, detail="chameleonInstanceId and chameleonSite are required")
        from app.chameleon_executor import run_in_chi_pool
        try:
            ip, name, key_name = await run_in_chi_pool(
                _lookup_chameleon_ip, body.chameleonSite, body.chameleonInstanceId,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Could not resolve Chameleon instance: {e}")
        if not ip:
            raise HTTPException(status_code=502, detail="Instance has no floating IP; associate a floating IP first")
        argv = _build_chameleon_ssh_argv(body.chameleonSite, ip, key_name)
        session = ts.create(type="chameleon", command=argv, label=body.label or name)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported terminal type: {body.type!r}")
    m = ts.meta(session)
    m["ticket"] = terminal_auth.mint_ticket(session.id)
    return m


@router.get("/api/terminals")
def list_terminals():
    """List live terminal sessions (for reattach from any client)."""
    return ts.list_sessions()


@router.post("/api/terminals/{session_id}/ticket")
def terminal_ticket(session_id: str):
    """Mint a fresh single-use attach ticket for an existing session."""
    if not ts.exists(session_id):
        raise HTTPException(status_code=404, detail="No such terminal session")
    return {"id": session_id, "ticket": terminal_auth.mint_ticket(session_id)}


@router.delete("/api/terminals/{session_id}")
def delete_terminal(session_id: str):
    """Kill a terminal session (closes the shell for all attached clients)."""
    if not ts.kill(session_id):
        raise HTTPException(status_code=404, detail="No such terminal session")
    return {"ok": True}


def _ws_authorized(websocket: WebSocket, session_id: str = "", ticket: str = "") -> bool:
    """Authorize a terminal attach before accept(): valid ticket OR session cookie."""
    return terminal_auth.ws_authorized(websocket, session_id, ticket)


@router.websocket("/ws/terminal/attach/{session_id}")
async def attach_terminal_ws(websocket: WebSocket, session_id: str, ticket: str = Query(default="")):
    """Attach to a server-held terminal session: replay its scrollback, then
    stream live. Disconnect detaches (the shell keeps running) — never kills.
    Multiple clients attaching to one session share a single view."""
    if not _ws_authorized(websocket, session_id, ticket):
        await websocket.close(code=1008)  # policy violation
        return
    session = ts.get(session_id)
    if session is None:
        await websocket.close(code=4004)  # no such session
        return

    await websocket.accept()
    queue = session.attach()
    try:
        # Replay recent output so the (re)attaching client redraws its screen.
        snap = session.snapshot()
        if snap:
            await websocket.send_text(snap)

        async def pump_out():
            while True:
                chunk = await queue.get()
                if chunk is None:      # session ended (shell exited)
                    break
                await websocket.send_text(chunk)

        out_task = asyncio.create_task(pump_out())

        while True:
            try:
                msg = await websocket.receive_text()
                parsed = json.loads(msg)
                if parsed.get("type") == "input":
                    session.write(parsed["data"])
                elif parsed.get("type") == "resize":
                    session.resize(int(parsed.get("cols", 80)), int(parsed.get("rows", 24)))
            except WebSocketDisconnect:
                break
            except Exception:
                break

        out_task.cancel()
    finally:
        session.detach(queue)


def _load_private_key(path: str) -> paramiko.PKey:
    """Load a private key file, trying all supported key types."""
    key_classes = [
        paramiko.Ed25519Key,
        paramiko.ECDSAKey,
        paramiko.RSAKey,
    ]
    last_err = None
    for cls in key_classes:
        try:
            return cls.from_private_key_file(path)
        except Exception as e:
            last_err = e
    raise paramiko.SSHException(f"Cannot load key {path}: {last_err}")
logger = logging.getLogger(__name__)


def _get_ssh_config(slice_name: Optional[str] = None):
    """Get SSH connection parameters from FABlib config.

    If *slice_name* is provided, check for a per-slice key assignment first.
    """
    fablib = get_fablib()
    config_dir = os.environ.get("FABRIC_CONFIG_DIR", DEFAULT_CONFIG_DIR)
    bastion_key = os.environ.get(
        "FABRIC_BASTION_KEY_LOCATION",
        os.path.join(config_dir, "fabric_bastion_key"),
    )

    # Determine slice key: per-slice assignment > default key set > env var
    slice_key = None
    if slice_name:
        storage_dir = get_user_storage()
        assignment_path = os.path.join(storage_dir, ".slice-keys", f"{slice_name}.json")
        if os.path.isfile(assignment_path):
            try:
                with open(assignment_path) as f:
                    assignment = json.load(f)
                key_id = assignment.get("slice_key_id", "")
                if key_id:
                    priv, _pub = get_slice_key_path(config_dir, key_id)
                    if os.path.isfile(priv):
                        slice_key = priv
            except Exception:
                pass

    if not slice_key:
        priv, _pub = get_default_slice_key_path(config_dir)
        if os.path.isfile(priv):
            slice_key = priv
        else:
            slice_key = os.environ.get(
                "FABRIC_SLICE_PRIVATE_KEY_FILE",
                os.path.join(config_dir, "slice_key"),
            )

    # Get bastion credentials from settings_manager (authoritative source)
    try:
        bastion_username = _settings_bastion_username()
    except Exception:
        bastion_username = os.environ.get("FABRIC_BASTION_USERNAME", "")

    bastion_host = _settings_host("bastion") or os.environ.get(
        "FABRIC_BASTION_HOST", "bastion.fabric-testbed.net"
    )

    return {
        "bastion_host": bastion_host,
        "bastion_username": bastion_username,
        "bastion_key": bastion_key,
        "slice_key": slice_key,
    }


def _connect_bastion(ssh_config: dict) -> paramiko.SSHClient:
    """Connect to the FABRIC bastion host."""
    pkey = _load_private_key(ssh_config["bastion_key"])
    bastion = paramiko.SSHClient()
    bastion.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    bastion.connect(
        hostname=ssh_config["bastion_host"],
        username=ssh_config["bastion_username"],
        pkey=pkey,
        timeout=15,
    )
    return bastion


def _open_tunnel(bastion: paramiko.SSHClient, management_ip: str):
    """Open a direct-tcpip channel through the bastion to the target."""
    bastion_transport = bastion.get_transport()
    dest_addr = (management_ip, 22)
    local_addr = ("127.0.0.1", 0)
    return bastion_transport.open_channel("direct-tcpip", dest_addr, local_addr)


def _connect_target(
    management_ip: str, username: str, ssh_config: dict, channel
) -> tuple:
    """Connect to the target node through an existing tunnel channel."""
    pkey = _load_private_key(ssh_config["slice_key"])
    target = paramiko.SSHClient()
    target.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    target.connect(
        hostname=management_ip,
        username=username,
        pkey=pkey,
        sock=channel,
        timeout=15,
    )
    shell = target.invoke_shell(term="xterm-256color")
    shell.setblocking(0)
    return target, shell


# ---------------------------------------------------------------------------
# Chameleon instance SSH terminal
# NOTE: Must be registered BEFORE /ws/terminal/{slice_name}/{node_name}
# to prevent FastAPI from matching "chameleon" as a slice_name.
# ---------------------------------------------------------------------------

@router.websocket("/ws/terminal/chameleon/{instance_id}")
async def chameleon_terminal_ws(websocket: WebSocket, instance_id: str):
    """WebSocket SSH terminal to a Chameleon Cloud instance.

    Query param: site (default CHI@TACC)
    Connects directly to the floating IP (no bastion needed).
    """
    if not _ws_authorized(websocket, "", ""):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    loop = asyncio.get_event_loop()
    target = None
    shell = None
    site = websocket.query_params.get("site", "CHI@TACC")

    try:
        await websocket.send_text(f"[terminal] Looking up Chameleon instance {instance_id} on {site}...\r\n")

        from app.chameleon_manager import get_session
        from app.chameleon_executor import run_in_chi_pool

        def _get_instance_info():
            session = get_session(site)
            result = session.api_get("compute", f"/servers/{instance_id}")
            srv = result.get("server", result)
            ip = None
            for net_name, addrs in srv.get("addresses", {}).items():
                for addr in addrs:
                    if addr.get("OS-EXT-IPS:type") == "floating":
                        ip = addr["addr"]
                        break
                if ip:
                    break
            if not ip:
                for net_name, addrs in srv.get("addresses", {}).items():
                    for addr in addrs:
                        ip = addr["addr"]
                        break
                    if ip:
                        break
            image_id = srv.get("image", {}).get("id", "") if isinstance(srv.get("image"), dict) else ""
            key_name = str(srv.get("key_name") or srv.get("OS-EXT-SRV-ATTR:key_name") or "").strip()
            if not key_name:
                key_name = _lookup_chameleon_record_key_name(site, instance_id)
            return ip, srv.get("name", "instance"), image_id, key_name

        ip, inst_name, image_id, key_name = await run_in_chi_pool(_get_instance_info)

        if not ip:
            await websocket.send_text("\x1b[31m[terminal] Error: Instance has no IP address. Associate a floating IP first.\x1b[0m\r\n")
            await websocket.close()
            return

        await websocket.send_text(f"[terminal] Instance: {inst_name} ({ip})\r\n")

        # Chameleon images all use 'cc' as the default SSH username
        username = "cc"

        # Find the Chameleon SSH key that matches Nova's keypair for this server.
        import os as _os
        from app.routes.chameleon import get_chameleon_key_path
        key_path = get_chameleon_key_path(site, key_name) if key_name else ""
        key_exists = bool(key_name and key_path and _os.path.isfile(key_path))
        await websocket.send_text(f"[terminal] Keypair: {key_name or '(none reported)'}\r\n")
        await websocket.send_text(f"[terminal] Key: {key_path or '(none)'} (exists={key_exists})\r\n")
        if not key_exists:
            if key_name:
                await websocket.send_text(
                    "\x1b[31m[terminal] No matching private key is available for this Chameleon keypair. "
                    "Add the private key to fabric_config/chameleon_key_<keypair> or set Chameleon SSH Key to that path.\x1b[0m\r\n"
                )
            else:
                await websocket.send_text(
                    "\x1b[31m[terminal] This instance does not report a Nova keypair. "
                    "If it was launched without key_name, SSH public-key auth cannot work; recreate it with a Chameleon default key.\x1b[0m\r\n"
                )
            await websocket.close()
            return

        # Check if we need to go through a bastion (private IP, no floating IP)
        bastion_ip = None
        slice_id = websocket.query_params.get("slice_id", "")
        if slice_id:
            from app.routes.chameleon import _chameleon_slices
            slice_obj = _chameleon_slices.get(slice_id, {})
            bastion = slice_obj.get("bastion", {})
            if bastion.get("floating_ip") and bastion.get("site") == site:
                # Check if the target IP is private (not the bastion itself)
                if ip != bastion["floating_ip"]:
                    bastion_ip = bastion["floating_ip"]

        if bastion_ip:
            await websocket.send_text(f"[terminal] Using bastion: {bastion_ip}\r\n")
            await websocket.send_text(f"[terminal] Connecting: bastion → {username}@{ip}...\r\n")
        else:
            await websocket.send_text(f"[terminal] Connecting as {username}@{ip}...\r\n")

        def _load_pkey():
            if not key_path:
                return None
            try:
                return paramiko.RSAKey.from_private_key_file(key_path)
            except Exception:
                try:
                    return paramiko.Ed25519Key.from_private_key_file(key_path)
                except Exception:
                    return paramiko.ECDSAKey.from_private_key_file(key_path)

        def _connect():
            pkey = _load_pkey()
            connect_kwargs: dict = {
                "username": username,
                "timeout": 15,
                "allow_agent": False,
                "look_for_keys": False,
            }
            if pkey:
                connect_kwargs["pkey"] = pkey

            if bastion_ip:
                # Two-hop: bastion → target (same pattern as FABRIC)
                bastion_client = paramiko.SSHClient()
                bastion_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                bastion_client.connect(hostname=bastion_ip, port=22, **connect_kwargs)
                # Open tunnel through bastion to target
                transport = bastion_client.get_transport()
                channel = transport.open_channel("direct-tcpip", (ip, 22), ("127.0.0.1", 0))
                # Connect to target through the tunnel
                target_client = paramiko.SSHClient()
                target_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                target_client.connect(hostname=ip, port=22, sock=channel, **connect_kwargs)
                chan = target_client.invoke_shell(term="xterm-256color", width=120, height=30)
                return target_client, chan
            else:
                # Direct connection
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(hostname=ip, port=22, **connect_kwargs)
                chan = client.invoke_shell(term="xterm-256color", width=120, height=30)
                return client, chan

        target, shell = await loop.run_in_executor(None, _connect)
        await websocket.send_text("\x1b[32m[terminal] Connected.\x1b[0m\r\n\r\n")
    except Exception as e:
        logger.exception("Chameleon SSH connection failed for %s@%s (key=%s)", username, ip if 'ip' in dir() else '?', key_path if 'key_path' in dir() else '?')
        err_type = type(e).__name__
        await websocket.send_text(f"\r\n\x1b[31m[terminal] SSH connection failed: {err_type}: {e}\x1b[0m\r\n")
        if "Authentication" in str(e):
            await websocket.send_text("\x1b[33m[terminal] The SSH key doesn't match. The instance may have been created with a different keypair.\r\n")
            await websocket.send_text("[terminal] Try: delete this instance, then create a new one (the deploy flow will inject the current loomai-key).\x1b[0m\r\n")
        await websocket.close()
        return

    try:
        async def read_ssh():
            while True:
                try:
                    data = await loop.run_in_executor(None, _read_shell, shell)
                    if data:
                        await websocket.send_text(data)
                    else:
                        await asyncio.sleep(0.05)
                except Exception:
                    break

        read_task = asyncio.create_task(read_ssh())

        while True:
            try:
                msg = await websocket.receive_text()
                parsed = json.loads(msg)
                if parsed.get("type") == "input":
                    shell.send(parsed["data"])
                elif parsed.get("type") == "resize":
                    shell.resize_pty(width=parsed.get("cols", 80), height=parsed.get("rows", 24))
            except WebSocketDisconnect:
                break
            except Exception:
                break

        read_task.cancel()

    finally:
        try:
            shell.close()
        except Exception:
            pass
        try:
            target.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# FABRIC VM SSH terminal
# ---------------------------------------------------------------------------

@router.websocket("/ws/terminal/{slice_name}/{node_name}")
async def terminal_ws(websocket: WebSocket, slice_name: str, node_name: str):
    """WebSocket endpoint for interactive SSH terminal."""
    if not _ws_authorized(websocket, "", ""):
        await websocket.close(code=1008)
        return
    slice_name = resolve_slice_name(slice_name)
    await websocket.accept()

    loop = asyncio.get_event_loop()
    bastion = None
    target = None
    shell = None

    try:
        # Step 1: Look up the node
        await websocket.send_text(f"[terminal] Looking up node '{node_name}' in slice '{slice_name}'...\r\n")
        fablib = get_fablib()
        from app.slice_registry import get_slice_uuid
        uuid = get_slice_uuid(slice_name)
        if uuid:
            try:
                slice_obj = await loop.run_in_executor(None, lambda: fablib.get_slice(slice_id=uuid))
            except Exception:
                slice_obj = await loop.run_in_executor(None, fablib.get_slice, slice_name)
        else:
            slice_obj = await loop.run_in_executor(None, fablib.get_slice, slice_name)
        node_obj = await loop.run_in_executor(None, slice_obj.get_node, node_name)
        management_ip = str(node_obj.get_management_ip())
        username = node_obj.get_username()

        if not management_ip:
            await websocket.send_text("\x1b[31m[terminal] Error: Node has no management IP.\x1b[0m\r\n")
            await websocket.close()
            return

        await websocket.send_text(f"[terminal] Node found: {username}@{management_ip}\r\n")

        # Step 2: Load SSH config
        await websocket.send_text("[terminal] Loading SSH keys and configuration...\r\n")
        ssh_config = _get_ssh_config(slice_name=slice_name)

        # Step 3: Connect to bastion
        await websocket.send_text(f"[terminal] Connecting to bastion {ssh_config['bastion_host']}...\r\n")
        bastion = await loop.run_in_executor(None, _connect_bastion, ssh_config)
        await websocket.send_text("[terminal] Bastion connected.\r\n")

        # Step 4: Open tunnel
        await websocket.send_text(f"[terminal] Opening tunnel to {management_ip}:22...\r\n")
        channel = await loop.run_in_executor(None, _open_tunnel, bastion, management_ip)
        await websocket.send_text("[terminal] Tunnel established.\r\n")

        # Step 5: Connect to target
        await websocket.send_text(f"[terminal] Authenticating as {username}@{management_ip}...\r\n")
        target, shell = await loop.run_in_executor(
            None, _connect_target, management_ip, username, ssh_config, channel
        )
        await websocket.send_text("\x1b[32m[terminal] Connected.\x1b[0m\r\n\r\n")
    except Exception as e:
        logger.exception("SSH connection failed")
        await websocket.send_text(f"\r\n\x1b[31m[terminal] SSH connection failed: {e}\x1b[0m\r\n")
        await websocket.close()
        if bastion:
            try:
                bastion.close()
            except Exception:
                pass
        return

    try:
        # Read from SSH shell and send to WebSocket
        async def read_ssh():
            loop = asyncio.get_event_loop()
            while True:
                try:
                    data = await loop.run_in_executor(None, _read_shell, shell)
                    if data:
                        await websocket.send_text(data)
                    else:
                        await asyncio.sleep(0.05)
                except Exception:
                    break

        read_task = asyncio.create_task(read_ssh())

        # Read from WebSocket and send to SSH shell
        while True:
            try:
                msg = await websocket.receive_text()
                parsed = json.loads(msg)
                if parsed.get("type") == "input":
                    shell.send(parsed["data"])
                elif parsed.get("type") == "resize":
                    cols = parsed.get("cols", 80)
                    rows = parsed.get("rows", 24)
                    shell.resize_pty(width=cols, height=rows)
            except WebSocketDisconnect:
                break
            except Exception:
                break

        read_task.cancel()

    finally:
        try:
            shell.close()
        except Exception:
            pass
        try:
            target.close()
        except Exception:
            pass
        try:
            bastion.close()
        except Exception:
            pass


def _read_shell(shell) -> str:
    """Read available data from paramiko shell channel."""
    try:
        if shell.recv_ready():
            return shell.recv(4096).decode("utf-8", errors="replace")
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Container terminal WebSocket (local PTY)
# ---------------------------------------------------------------------------

@router.websocket("/ws/terminal/container")
async def container_terminal_ws(websocket: WebSocket):
    """WebSocket endpoint for an interactive shell on the container itself.

    Legacy: the UI now uses the persistent `/ws/terminal/attach/{id}` path.
    Retained for compatibility but authenticated like every other socket.
    """
    if not _ws_authorized(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()

    loop = asyncio.get_event_loop()
    master_fd = None
    proc = None

    try:
        # Create a pseudo-terminal
        master_fd, slave_fd = pty.openpty()

        # Start bash in the container, defaulting to fabric user home
        cwd = os.path.expanduser("~")
        # Always include AI tool paths so tools installed mid-session are accessible
        shell_env = {**os.environ, "TERM": "xterm-256color"}
        venv_bin = os.path.join(AI_TOOLS_DIR, "venv", "bin")
        npm_bin = os.path.join(AI_TOOLS_DIR, "npm", "bin")
        shell_env["PATH"] = f"{venv_bin}:{npm_bin}:{os.environ.get('PATH', '')}"

        proc = subprocess.Popen(
            ["/bin/bash"],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=cwd,
            preexec_fn=os.setsid,
            env=shell_env,
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


def _read_master(fd: int) -> str:
    """Read available data from a PTY master fd."""
    try:
        data = os.read(fd, 4096)
        return data.decode("utf-8", errors="replace") if data else ""
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Log file streaming WebSocket
# ---------------------------------------------------------------------------

@router.websocket("/ws/logs")
async def logs_ws(websocket: WebSocket):
    """Stream the FABlib log file to the client, tail -f style."""
    if not _ws_authorized(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()

    from app.settings_manager import get_log_file
    log_file = get_log_file()

    try:
        # Send initial tail of existing log (last 200 lines)
        if os.path.isfile(log_file):
            with open(log_file, "r", errors="replace") as f:
                lines = f.readlines()
                tail = lines[-200:] if len(lines) > 200 else lines
                for ln in tail:
                    await websocket.send_text(ln)
            file_pos = os.path.getsize(log_file)
        else:
            await websocket.send_text(f"[log] Waiting for log file: {log_file}\n")
            file_pos = 0

        # Tail loop
        while True:
            await asyncio.sleep(0.5)
            if not os.path.isfile(log_file):
                continue
            size = os.path.getsize(log_file)
            if size < file_pos:
                # File was truncated/rotated
                file_pos = 0
            if size > file_pos:
                with open(log_file, "r", errors="replace") as f:
                    f.seek(file_pos)
                    new_data = f.read()
                    file_pos = f.tell()
                if new_data:
                    await websocket.send_text(new_data)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
