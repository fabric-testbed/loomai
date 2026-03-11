"""WebSocket SSH terminal endpoint using paramiko through FABRIC bastion."""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import struct
import subprocess
import termios
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.tool_installer import AI_TOOLS_DIR
import paramiko

from app.slice_registry import resolve_slice_name
from app.fablib_manager import (
    DEFAULT_CONFIG_DIR,
    get_fablib,
    get_default_slice_key_path,
    get_slice_key_path,
)
from app.user_context import get_user_storage

router = APIRouter()


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

    # Get bastion username from fablib
    try:
        bastion_username = fablib.get_bastion_username()
    except Exception:
        bastion_username = os.environ.get("FABRIC_BASTION_USERNAME", "")

    bastion_host = os.environ.get(
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


@router.websocket("/ws/terminal/{slice_name}/{node_name}")
async def terminal_ws(websocket: WebSocket, slice_name: str, node_name: str):
    """WebSocket endpoint for interactive SSH terminal."""
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
    """WebSocket endpoint for an interactive shell on the container itself."""
    await websocket.accept()

    loop = asyncio.get_event_loop()
    master_fd = None
    proc = None

    try:
        # Create a pseudo-terminal
        master_fd, slave_fd = pty.openpty()

        # Start bash in the container, defaulting to storage dir
        from app.settings_manager import get_storage_dir as _storage
        cwd = _storage() if os.path.isdir(_storage()) else os.path.expanduser("~")
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
