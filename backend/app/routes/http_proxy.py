"""HTTP proxy endpoint that tunnels requests to FABRIC VMs through the SSH bastion."""
from __future__ import annotations

import asyncio
import http.client
import logging
import re
import socket
import threading
import time
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

import paramiko

from app.fablib_manager import get_fablib
from app.routes.terminal import _get_ssh_config, _connect_bastion, _load_private_key

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Connection cache: reuse bastion + VM SSH connections per (slice, node)
# ---------------------------------------------------------------------------
_conn_lock = threading.Lock()
_conn_cache: dict[tuple[str, str], dict] = {}  # (slice, node) -> {bastion, vm_ssh, mgmt_ip, username, ts}
_CACHE_TTL = 300  # seconds


def _cleanup_stale():
    """Remove connections older than TTL."""
    now = time.time()
    stale = [k for k, v in _conn_cache.items() if now - v["ts"] > _CACHE_TTL]
    for k in stale:
        entry = _conn_cache.pop(k, None)
        if entry:
            for key in ("vm_ssh", "bastion"):
                try:
                    c = entry.get(key)
                    if c:
                        c.close()
                except Exception:
                    pass


def _get_vm_ssh(slice_name: str, node_name: str) -> tuple[paramiko.SSHClient, paramiko.SSHClient, str]:
    """Return (bastion, vm_ssh, mgmt_ip) with caching.

    Uses a two-hop SSH connection: bastion → tunnel to VM:22 → SSH into VM.
    This lets us port-forward to localhost on the VM, reaching services that
    only bind to 127.0.0.1.
    """
    key = (slice_name, node_name)
    with _conn_lock:
        _cleanup_stale()
        cached = _conn_cache.get(key)
        if cached:
            # Check both transports are alive
            b_transport = cached["bastion"].get_transport()
            v_transport = cached["vm_ssh"].get_transport()
            if (b_transport and b_transport.is_active() and
                    v_transport and v_transport.is_active()):
                cached["ts"] = time.time()
                return cached["bastion"], cached["vm_ssh"], cached["mgmt_ip"]
            else:
                # Stale — close and rebuild
                for c_key in ("vm_ssh", "bastion"):
                    try:
                        cached[c_key].close()
                    except Exception:
                        pass
                _conn_cache.pop(key, None)

    # Look up management IP and username via FABlib
    fablib = get_fablib()
    from app.slice_registry import get_slice_uuid
    uuid = get_slice_uuid(slice_name)
    if uuid:
        try:
            slice_obj = fablib.get_slice(slice_id=uuid)
        except Exception:
            slice_obj = fablib.get_slice(slice_name)
    else:
        slice_obj = fablib.get_slice(slice_name)
    node_obj = slice_obj.get_node(node_name)
    mgmt_ip = str(node_obj.get_management_ip())
    if not mgmt_ip:
        raise ValueError(f"Node {node_name} has no management IP")

    username = "ubuntu"
    try:
        username = str(node_obj.get_username()) or "ubuntu"
    except Exception:
        pass

    ssh_config = _get_ssh_config(slice_name=slice_name)

    # Hop 1: connect to bastion
    bastion = _connect_bastion(ssh_config)

    # Hop 2: open tunnel through bastion to VM:22, then SSH into the VM
    bastion_transport = bastion.get_transport()
    tunnel_channel = bastion_transport.open_channel(
        "direct-tcpip", (mgmt_ip, 22), ("127.0.0.1", 0)
    )

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

    with _conn_lock:
        _conn_cache[key] = {
            "bastion": bastion,
            "vm_ssh": vm_ssh,
            "mgmt_ip": mgmt_ip,
            "username": username,
            "ts": time.time(),
        }

    return bastion, vm_ssh, mgmt_ip


def _open_http_tunnel(vm_ssh: paramiko.SSHClient, port: int) -> paramiko.Channel:
    """Open a direct-tcpip channel through the VM's SSH to localhost:port.

    Since we're already SSH'd into the VM, this reaches services bound to
    127.0.0.1 as well as 0.0.0.0.
    """
    transport = vm_ssh.get_transport()
    return transport.open_channel("direct-tcpip", ("127.0.0.1", port), ("127.0.0.1", 0))


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


def _proxy_request(
    slice_name: str,
    node_name: str,
    port: int,
    method: str,
    path: str,
    headers: dict[str, str],
    body: Optional[bytes],
) -> tuple[int, dict[str, str], bytes]:
    """Execute an HTTP request through the two-hop SSH tunnel and return (status, headers, body)."""
    _bastion, vm_ssh, mgmt_ip = _get_vm_ssh(slice_name, node_name)
    channel = _open_http_tunnel(vm_ssh, port)

    try:
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.sock = _ChannelSocket(channel)

        # Forward relevant headers; strip Accept-Encoding so the VM
        # always sends uncompressed responses (we may need to rewrite them).
        fwd_headers = {}
        for k, v in headers.items():
            lk = k.lower()
            if lk in ("host", "connection", "transfer-encoding", "accept-encoding"):
                continue
            fwd_headers[k] = v
        fwd_headers["Host"] = f"127.0.0.1:{port}"
        fwd_headers["Accept-Encoding"] = "identity"

        conn.request(method, path, body=body, headers=fwd_headers)
        resp = conn.getresponse()

        resp_headers = {k: v for k, v in resp.getheaders()}
        resp_body = resp.read()

        return resp.status, resp_headers, resp_body
    finally:
        try:
            channel.close()
        except Exception:
            pass


def _rewrite_html(body: bytes, content_type: str, slice_name: str, node_name: str, port: int) -> bytes:
    """Rewrite absolute URL paths in HTML so sub-resources load through the proxy.

    Only HTML gets attribute rewriting (src, href, action) and the JS interceptor.
    CSS gets url() rewriting.  JavaScript is left untouched — the injected
    fetch/XHR/createElement interceptors handle dynamic requests at runtime.
    """
    is_html = "text/html" in content_type
    is_css = "text/css" in content_type
    if not is_html and not is_css:
        return body

    prefix = f"/api/proxy/{slice_name}/{node_name}/{port}"
    text = body.decode("utf-8", errors="replace")

    if is_html:
        # Inject <base> tag and interceptors for fetch, XHR, createElement,
        # and History API so all resource loads route through the proxy.
        inject = (
            f'<base href="{prefix}/">'
            f'<script>'
            f'(function(){{'
            f'var P="{prefix}";'
            f'function rw(u){{if(typeof u==="string"&&u.startsWith("/")&&!u.startsWith(P))return P+u;return u;}}'
            # fetch
            f'var _fetch=window.fetch;'
            f'window.fetch=function(u,o){{return _fetch.call(this,rw(u),o);}};'
            # XMLHttpRequest
            f'var _open=XMLHttpRequest.prototype.open;'
            f'XMLHttpRequest.prototype.open=function(m,u){{arguments[1]=rw(u);return _open.apply(this,arguments);}};'
            # createElement — intercept script/link/img src and href
            f'var _ce=document.createElement.bind(document);'
            f'document.createElement=function(tag){{'
            f'var el=_ce(tag);'
            f'var lt=tag.toLowerCase();'
            f'if(lt==="script"||lt==="img"||lt==="link"){{'
            f'var _set=Object.getOwnPropertyDescriptor(HTMLScriptElement.prototype,"src")||Object.getOwnPropertyDescriptor(HTMLElement.prototype,"src");'
            f'["src","href"].forEach(function(attr){{'
            f'var d=Object.getOwnPropertyDescriptor(el.__proto__,attr);'
            f'if(d&&d.set){{Object.defineProperty(el,attr,{{set:function(v){{d.set.call(this,rw(v));}},get:d.get,configurable:true}});}}'
            f'}});'
            f'}}'
            f'return el;'
            f'}};'
            # History pushState/replaceState
            f'var _ps=history.pushState.bind(history);'
            f'history.pushState=function(s,t,u){{return _ps(s,t,u?rw(u):u);}};'
            f'var _rs=history.replaceState.bind(history);'
            f'history.replaceState=function(s,t,u){{return _rs(s,t,u?rw(u):u);}};'
            f'}})()'
            f'</script>'
        )
        if re.search(r'<head[^>]*>', text, re.IGNORECASE):
            text = re.sub(r'(<head[^>]*>)', rf'\1{inject}', text, count=1, flags=re.IGNORECASE)
        else:
            text = inject + text

        # Rewrite src="/...", href="/...", action="/..." in HTML attributes
        text = re.sub(
            r'((?:src|href|action)\s*=\s*["\'])(/(?!/))',
            rf'\1{prefix}\2',
            text,
        )

    # Rewrite url(...) in HTML and CSS
    text = re.sub(
        r'(url\s*\(\s*["\']?)(/(?!/))',
        rf'\1{prefix}\2',
        text,
    )
    return text.encode("utf-8")


# ---------------------------------------------------------------------------
# FastAPI endpoint
# ---------------------------------------------------------------------------

@router.api_route(
    "/api/proxy/{slice_name}/{node_name}/{port}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def http_proxy(
    request: Request,
    slice_name: str,
    node_name: str,
    port: int,
    path: str = "",
):
    """Proxy HTTP requests to a FABRIC VM through a two-hop SSH tunnel.

    Connection path: browser → backend → bastion SSH → VM SSH → localhost:port.
    This reaches services bound to 127.0.0.1 (not just 0.0.0.0).
    """
    loop = asyncio.get_event_loop()

    method = request.method
    req_path = f"/{path}"
    if request.url.query:
        req_path += f"?{request.url.query}"

    headers = dict(request.headers)
    body = await request.body() if method in ("POST", "PUT", "PATCH") else None

    try:
        status, resp_headers, resp_body = await loop.run_in_executor(
            None,
            _proxy_request,
            slice_name,
            node_name,
            port,
            method,
            req_path,
            headers,
            body,
        )
    except Exception as e:
        logger.exception("HTTP proxy error for %s/%s:%d", slice_name, node_name, port)
        return Response(content=f"Proxy error: {e}", status_code=502)

    content_type = resp_headers.get("Content-Type", resp_headers.get("content-type", ""))

    # Rewrite HTML/JS content to route sub-resources through proxy
    resp_body = _rewrite_html(resp_body, content_type, slice_name, node_name, port)

    # Rewrite redirect Location headers so the browser stays in the proxy
    prefix = f"/api/proxy/{slice_name}/{node_name}/{port}"
    for hdr in list(resp_headers.keys()):
        if hdr.lower() == "location":
            loc = resp_headers[hdr]
            # Absolute URL pointing at the VM — strip to path
            abs_match = re.match(r'https?://[^/]+(/.*)$', loc)
            if abs_match:
                loc = abs_match.group(1)
            if loc.startswith("/") and not loc.startswith(prefix):
                resp_headers[hdr] = prefix + loc
        # Strip CSP / X-Frame-Options that block iframe embedding
        if hdr.lower() in ("content-security-policy", "x-frame-options"):
            del resp_headers[hdr]

    # Filter out hop-by-hop headers
    skip = {"transfer-encoding", "connection", "keep-alive", "content-length", "content-encoding"}
    out_headers = {k: v for k, v in resp_headers.items() if k.lower() not in skip}

    return Response(
        content=resp_body,
        status_code=status,
        headers=out_headers,
        media_type=content_type.split(";")[0].strip() if content_type else None,
    )
