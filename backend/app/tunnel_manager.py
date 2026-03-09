"""SSH tunnel manager for transparent port forwarding to FABRIC VMs.

Opens two-hop SSH tunnels (backend → bastion → VM) and runs a lightweight
HTTP reverse proxy on a local port in the 9100–9199 range.  The proxy
strips iframe-blocking headers (X-Frame-Options, CSP) so the browser can
embed the service in an iframe.  No URL rewriting — the app runs at root /.
"""
from __future__ import annotations

import http.client
import http.server
import logging
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

import paramiko

from app.fablib_manager import get_fablib
from app.routes.terminal import _get_ssh_config, _connect_bastion, _load_private_key

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PORT_RANGE_START = 9100
PORT_RANGE_END = 9199  # inclusive
IDLE_TTL = 600  # seconds before idle tunnel is closed

# Headers to strip from proxied responses (lowercase)
_STRIP_HEADERS = frozenset({
    "x-frame-options",
    "content-security-policy",
    "content-security-policy-report-only",
})

# Hop-by-hop headers to not forward
_HOP_HEADERS = frozenset({
    "transfer-encoding", "connection", "keep-alive",
    "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "upgrade",
})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TunnelInfo:
    id: str
    slice_name: str
    node_name: str
    remote_port: int
    local_port: int
    created_at: float
    last_connection_at: float
    status: str  # "connecting", "active", "closed", "error"
    error: Optional[str] = None
    # Internal — not serialised
    _bastion: Optional[paramiko.SSHClient] = field(default=None, repr=False)
    _vm_ssh: Optional[paramiko.SSHClient] = field(default=None, repr=False)
    _http_server: Optional[http.server.HTTPServer] = field(default=None, repr=False)
    _listener_thread: Optional[threading.Thread] = field(default=None, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "slice_name": self.slice_name,
            "node_name": self.node_name,
            "remote_port": self.remote_port,
            "local_port": self.local_port,
            "created_at": self.created_at,
            "last_connection_at": self.last_connection_at,
            "status": self.status,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Channel-as-socket wrapper (reused from http_proxy.py pattern)
# ---------------------------------------------------------------------------

class _ChannelSocket:
    """Wrap a paramiko Channel so it looks like a socket for http.client."""

    def __init__(self, channel: paramiko.Channel):
        self._chan = channel

    def makefile(self, mode="r", buffering=-1):
        return self._chan.makefile(mode, buffering)

    def sendall(self, data: bytes):
        self._chan.sendall(data)

    def close(self):
        self._chan.close()

    def settimeout(self, timeout):
        self._chan.settimeout(timeout)


# ---------------------------------------------------------------------------
# Singleton manager
# ---------------------------------------------------------------------------

class TunnelManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._tunnels: Dict[str, TunnelInfo] = {}
        self._used_ports: set[int] = set()

    # -- Port allocation ----------------------------------------------------

    def _alloc_port(self) -> int:
        """Allocate a port that is both untracked *and* actually bindable."""
        for p in range(PORT_RANGE_START, PORT_RANGE_END + 1):
            if p in self._used_ports:
                continue
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(("0.0.0.0", p))
                probe.close()
            except OSError:
                probe.close()
                continue
            self._used_ports.add(p)
            return p
        raise RuntimeError("No free tunnel ports available")

    def _free_port(self, port: int):
        self._used_ports.discard(port)

    # -- Public API ---------------------------------------------------------

    def create_tunnel(self, slice_name: str, node_name: str, remote_port: int) -> TunnelInfo:
        """Create and start a new SSH tunnel."""
        with self._lock:
            # Clean out dead tunnels to the same target
            dead = [
                tid for tid, t in self._tunnels.items()
                if (t.slice_name == slice_name and t.node_name == node_name
                    and t.remote_port == remote_port and t.status in ("error", "closed"))
            ]
            for tid in dead:
                old = self._tunnels.pop(tid, None)
                if old:
                    self._free_port(old.local_port)

            # Reuse existing active/connecting tunnel
            for t in self._tunnels.values():
                if (t.slice_name == slice_name and t.node_name == node_name
                        and t.remote_port == remote_port and t.status in ("connecting", "active")):
                    return t
            local_port = self._alloc_port()

        tunnel_id = uuid.uuid4().hex[:12]
        now = time.time()
        info = TunnelInfo(
            id=tunnel_id,
            slice_name=slice_name,
            node_name=node_name,
            remote_port=remote_port,
            local_port=local_port,
            created_at=now,
            last_connection_at=now,
            status="connecting",
        )

        with self._lock:
            self._tunnels[tunnel_id] = info

        thread = threading.Thread(
            target=self._run_tunnel,
            args=(info,),
            daemon=True,
            name=f"tunnel-{tunnel_id}",
        )
        info._listener_thread = thread
        thread.start()
        return info

    def close_tunnel(self, tunnel_id: str) -> bool:
        with self._lock:
            info = self._tunnels.get(tunnel_id)
            if not info:
                return False
        self._shutdown_tunnel(info)
        return True

    def list_tunnels(self) -> list[dict]:
        with self._lock:
            return [t.to_dict() for t in self._tunnels.values()]

    def cleanup_idle(self):
        """Close tunnels that have been idle longer than IDLE_TTL."""
        now = time.time()
        to_close: list[TunnelInfo] = []
        with self._lock:
            for t in self._tunnels.values():
                if t.status == "active" and (now - t.last_connection_at) > IDLE_TTL:
                    to_close.append(t)
        for t in to_close:
            logger.info("Closing idle tunnel %s (port %d)", t.id, t.local_port)
            self._shutdown_tunnel(t)

    def close_all(self):
        """Shutdown all tunnels (used at app shutdown)."""
        with self._lock:
            tunnels = list(self._tunnels.values())
        for t in tunnels:
            self._shutdown_tunnel(t)

    # -- Internal -----------------------------------------------------------

    def _shutdown_tunnel(self, info: TunnelInfo):
        info._stop_event.set()
        info.status = "closed"

        if info._http_server:
            try:
                info._http_server.shutdown()
            except Exception:
                pass

        for attr in ("_vm_ssh", "_bastion"):
            client = getattr(info, attr, None)
            if client:
                try:
                    client.close()
                except Exception:
                    pass

        with self._lock:
            self._tunnels.pop(info.id, None)
            self._free_port(info.local_port)

    def _run_tunnel(self, info: TunnelInfo):
        """Listener thread: establish SSH, then serve HTTP proxy."""
        try:
            # 1. Look up node
            fablib = get_fablib()
            from app.slice_registry import get_slice_uuid
            uuid_val = get_slice_uuid(info.slice_name)
            if uuid_val:
                try:
                    slice_obj = fablib.get_slice(slice_id=uuid_val)
                except Exception:
                    slice_obj = fablib.get_slice(info.slice_name)
            else:
                slice_obj = fablib.get_slice(info.slice_name)
            node_obj = slice_obj.get_node(info.node_name)
            mgmt_ip = str(node_obj.get_management_ip())
            if not mgmt_ip:
                raise ValueError(f"Node {info.node_name} has no management IP")
            username = "ubuntu"
            try:
                username = str(node_obj.get_username()) or "ubuntu"
            except Exception:
                pass

            # 2. SSH to bastion
            ssh_config = _get_ssh_config(slice_name=info.slice_name)
            bastion = _connect_bastion(ssh_config)
            info._bastion = bastion

            # 3. Tunnel through bastion to VM:22
            bastion_transport = bastion.get_transport()
            tunnel_channel = bastion_transport.open_channel(
                "direct-tcpip", (mgmt_ip, 22), ("127.0.0.1", 0)
            )

            # 4. SSH into VM
            vm_ssh = paramiko.SSHClient()
            vm_ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            slice_pkey = _load_private_key(ssh_config["slice_key"])
            vm_ssh.connect(
                hostname=mgmt_ip,
                username=username,
                pkey=slice_pkey,
                sock=tunnel_channel,
                timeout=15,
            )
            info._vm_ssh = vm_ssh

            # 5. Start HTTP proxy server
            handler_class = _make_handler(info)
            srv = http.server.ThreadingHTTPServer(
                ("0.0.0.0", info.local_port), handler_class
            )
            srv.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            info._http_server = srv
            info.status = "active"
            logger.info(
                "Tunnel %s active: localhost:%d → %s(%s):%d",
                info.id, info.local_port, info.node_name, mgmt_ip, info.remote_port,
            )

            # serve_forever blocks until shutdown() is called
            srv.serve_forever()

        except Exception as e:
            logger.exception("Tunnel %s setup failed", info.id)
            info.status = "error"
            info.error = str(e)


def _make_handler(tunnel_info: TunnelInfo):
    """Create a request handler class bound to a specific tunnel."""

    class TunnelProxyHandler(http.server.BaseHTTPRequestHandler):
        """HTTP reverse proxy that forwards requests through the SSH tunnel
        and strips iframe-blocking headers from responses."""

        # Suppress per-request log lines (too noisy)
        def log_message(self, format, *args):
            pass

        def do_request(self):
            tunnel_info.last_connection_at = time.time()

            # Read request body if present
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            # Open SSH channel to VM's localhost:remote_port
            try:
                vm_transport = tunnel_info._vm_ssh.get_transport()
                if not vm_transport or not vm_transport.is_active():
                    self.send_error(502, "SSH tunnel to VM is no longer active")
                    return
                channel = vm_transport.open_channel(
                    "direct-tcpip",
                    ("127.0.0.1", tunnel_info.remote_port),
                    ("127.0.0.1", 0),
                )
            except Exception as e:
                self.send_error(502, f"Failed to open SSH channel: {e}")
                return

            try:
                conn = http.client.HTTPConnection("127.0.0.1", tunnel_info.remote_port)
                conn.sock = _ChannelSocket(channel)

                # Forward headers, stripping hop-by-hop and accept-encoding
                fwd_headers = {}
                for k, v in self.headers.items():
                    lk = k.lower()
                    if lk in _HOP_HEADERS or lk == "accept-encoding" or lk == "host":
                        continue
                    fwd_headers[k] = v
                fwd_headers["Host"] = f"127.0.0.1:{tunnel_info.remote_port}"
                fwd_headers["Accept-Encoding"] = "identity"

                conn.request(self.command, self.path, body=body, headers=fwd_headers)
                resp = conn.getresponse()

                # Send status
                self.send_response_only(resp.status, resp.reason)

                # Forward response headers, stripping iframe-blockers and hop-by-hop
                for k, v in resp.getheaders():
                    lk = k.lower()
                    if lk in _STRIP_HEADERS or lk in _HOP_HEADERS or lk == "content-length" or lk == "content-encoding":
                        continue
                    self.send_header(k, v)

                resp_body = resp.read()
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)

            except Exception as e:
                try:
                    self.send_error(502, f"Proxy error: {e}")
                except Exception:
                    pass
            finally:
                try:
                    channel.close()
                except Exception:
                    pass

        # Handle all HTTP methods
        do_GET = do_request
        do_POST = do_request
        do_PUT = do_request
        do_DELETE = do_request
        do_PATCH = do_request
        do_HEAD = do_request
        do_OPTIONS = do_request

    return TunnelProxyHandler


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_manager: Optional[TunnelManager] = None
_manager_lock = threading.Lock()


def get_tunnel_manager() -> TunnelManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = TunnelManager()
    return _manager
