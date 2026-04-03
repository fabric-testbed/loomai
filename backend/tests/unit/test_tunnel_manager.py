"""Unit tests for TunnelManager.

Tests the tunnel manager's port allocation, tunnel lifecycle, listing,
idle cleanup, and close-all without needing real SSH connections.

Port allocation is mocked to avoid failures when the 9100-9199 range
is occupied by other services on the test host.
"""

import socket
import threading
import time
from unittest.mock import patch, MagicMock

import pytest

from app.tunnel_manager import (
    TunnelManager,
    TunnelInfo,
    PORT_RANGE_START,
    PORT_RANGE_END,
    IDLE_TTL,
    _ChannelSocket,
    get_tunnel_manager,
)


# ---------------------------------------------------------------------------
# TunnelInfo
# ---------------------------------------------------------------------------

class TestTunnelInfo:
    def test_to_dict_serializes_correctly(self):
        now = time.time()
        info = TunnelInfo(
            id="abc123",
            slice_name="my-slice",
            node_name="node1",
            remote_port=8080,
            local_port=9100,
            created_at=now,
            last_connection_at=now,
            status="active",
            error=None,
        )
        d = info.to_dict()
        assert d["id"] == "abc123"
        assert d["slice_name"] == "my-slice"
        assert d["node_name"] == "node1"
        assert d["remote_port"] == 8080
        assert d["local_port"] == 9100
        assert d["status"] == "active"
        assert d["error"] is None
        # Internal fields should NOT be in dict
        assert "_bastion" not in d
        assert "_vm_ssh" not in d

    def test_to_dict_with_error(self):
        info = TunnelInfo(
            id="err1",
            slice_name="s",
            node_name="n",
            remote_port=80,
            local_port=9101,
            created_at=0,
            last_connection_at=0,
            status="error",
            error="Connection refused",
        )
        assert info.to_dict()["error"] == "Connection refused"


# ---------------------------------------------------------------------------
# ChannelSocket wrapper
# ---------------------------------------------------------------------------

class TestChannelSocket:
    def test_sendall_delegates(self):
        chan = MagicMock()
        sock = _ChannelSocket(chan)
        sock.sendall(b"hello")
        chan.sendall.assert_called_once_with(b"hello")

    def test_close_delegates(self):
        chan = MagicMock()
        sock = _ChannelSocket(chan)
        sock.close()
        chan.close.assert_called_once()

    def test_settimeout_delegates(self):
        chan = MagicMock()
        sock = _ChannelSocket(chan)
        sock.settimeout(5.0)
        chan.settimeout.assert_called_once_with(5.0)

    def test_makefile_delegates(self):
        chan = MagicMock()
        sock = _ChannelSocket(chan)
        sock.makefile("rb")
        chan.makefile.assert_called_once_with("rb", -1)


# ---------------------------------------------------------------------------
# Helper: mock socket bind to always succeed
# ---------------------------------------------------------------------------

def _mock_socket_bind_success():
    """Return a context manager that makes socket bind always succeed."""
    original_socket = socket.socket

    class MockSocket:
        def __init__(self, *args, **kwargs):
            pass
        def setsockopt(self, *args, **kwargs):
            pass
        def bind(self, addr):
            pass
        def close(self):
            pass

    return patch("app.tunnel_manager.socket.socket", MockSocket)


# ---------------------------------------------------------------------------
# Port allocation
# ---------------------------------------------------------------------------

class TestPortAllocation:
    def test_alloc_port_returns_port_in_range(self):
        mgr = TunnelManager()
        with _mock_socket_bind_success():
            port = mgr._alloc_port()
        assert PORT_RANGE_START <= port <= PORT_RANGE_END
        mgr._free_port(port)

    def test_alloc_port_avoids_used_ports(self):
        mgr = TunnelManager()
        with _mock_socket_bind_success():
            p1 = mgr._alloc_port()
            p2 = mgr._alloc_port()
        assert p1 != p2
        mgr._free_port(p1)
        mgr._free_port(p2)

    def test_free_port_allows_reuse(self):
        mgr = TunnelManager()
        with _mock_socket_bind_success():
            p1 = mgr._alloc_port()
            mgr._free_port(p1)
            p2 = mgr._alloc_port()
        assert PORT_RANGE_START <= p2 <= PORT_RANGE_END
        mgr._free_port(p2)

    def test_alloc_all_ports_raises(self):
        """When all ports are used, should raise RuntimeError."""
        mgr = TunnelManager()
        # Mark all ports as used
        for p in range(PORT_RANGE_START, PORT_RANGE_END + 1):
            mgr._used_ports.add(p)
        with pytest.raises(RuntimeError, match="No free tunnel ports"):
            mgr._alloc_port()


# ---------------------------------------------------------------------------
# Tunnel list, close, close_all
# ---------------------------------------------------------------------------

def _make_tunnel_info(mgr, tid, status="active"):
    """Helper to create a TunnelInfo and register it."""
    now = time.time()
    # Directly assign port without binding
    port = PORT_RANGE_START + len(mgr._tunnels)
    mgr._used_ports.add(port)
    info = TunnelInfo(
        id=tid,
        slice_name="s",
        node_name="n",
        remote_port=80,
        local_port=port,
        created_at=now,
        last_connection_at=now,
        status=status,
    )
    mgr._tunnels[tid] = info
    return info


class TestTunnelLifecycle:
    def test_list_tunnels_empty(self):
        mgr = TunnelManager()
        assert mgr.list_tunnels() == []

    def test_list_tunnels_shows_tunnels(self):
        mgr = TunnelManager()
        _make_tunnel_info(mgr, "t1")
        tunnels = mgr.list_tunnels()
        assert len(tunnels) == 1
        assert tunnels[0]["id"] == "t1"

    def test_close_tunnel_returns_true(self):
        mgr = TunnelManager()
        info = _make_tunnel_info(mgr, "t2")
        assert mgr.close_tunnel("t2") is True
        assert info.status == "closed"
        assert "t2" not in mgr._tunnels

    def test_close_nonexistent_returns_false(self):
        mgr = TunnelManager()
        assert mgr.close_tunnel("nonexistent") is False

    def test_close_all_shuts_down_everything(self):
        mgr = TunnelManager()
        for tid in ["a", "b", "c"]:
            _make_tunnel_info(mgr, tid)
        mgr.close_all()
        assert len(mgr._tunnels) == 0


# ---------------------------------------------------------------------------
# Idle cleanup
# ---------------------------------------------------------------------------

class TestIdleCleanup:
    def test_cleanup_idle_closes_old_tunnels(self):
        mgr = TunnelManager()
        info = _make_tunnel_info(mgr, "idle1")
        info.last_connection_at = time.time() - IDLE_TTL - 10
        mgr.cleanup_idle()
        assert info.status == "closed"

    def test_cleanup_idle_keeps_active_tunnels(self):
        mgr = TunnelManager()
        info = _make_tunnel_info(mgr, "active1")
        info.last_connection_at = time.time()  # just now
        mgr.cleanup_idle()
        assert info.status == "active"


# ---------------------------------------------------------------------------
# Shutdown tunnel helper
# ---------------------------------------------------------------------------

class TestShutdownTunnel:
    def test_shutdown_closes_ssh_clients(self):
        mgr = TunnelManager()
        info = _make_tunnel_info(mgr, "shut1")
        mock_bastion = MagicMock()
        mock_vm = MagicMock()
        mock_server = MagicMock()
        info._bastion = mock_bastion
        info._vm_ssh = mock_vm
        info._http_server = mock_server

        mgr._shutdown_tunnel(info)
        mock_bastion.close.assert_called_once()
        mock_vm.close.assert_called_once()
        mock_server.shutdown.assert_called_once()
        assert info.status == "closed"

    def test_shutdown_handles_close_errors(self):
        """Shutdown should not crash even if close() raises."""
        mgr = TunnelManager()
        info = _make_tunnel_info(mgr, "shut_err")
        mock_bastion = MagicMock()
        mock_bastion.close.side_effect = Exception("connection lost")
        info._bastion = mock_bastion
        mgr._shutdown_tunnel(info)  # Should not raise
        assert info.status == "closed"


# ---------------------------------------------------------------------------
# Create tunnel (reuse existing)
# ---------------------------------------------------------------------------

class TestCreateTunnel:
    def test_create_reuses_active_tunnel(self):
        """If an active tunnel to the same target exists, reuse it."""
        mgr = TunnelManager()
        info = _make_tunnel_info(mgr, "reuse1")
        info.slice_name = "s1"
        info.node_name = "n1"
        info.remote_port = 8080
        info.status = "active"

        # Attempt to create a tunnel to the same target
        result = mgr.create_tunnel("s1", "n1", 8080)
        assert result.id == "reuse1"  # Should reuse

    def test_create_cleans_dead_tunnels(self):
        """Dead tunnels to the same target should be cleaned up."""
        mgr = TunnelManager()
        info = _make_tunnel_info(mgr, "dead1")
        info.slice_name = "s1"
        info.node_name = "n1"
        info.remote_port = 8080
        info.status = "error"

        with _mock_socket_bind_success():
            # Creating a new tunnel should clean the dead one first
            # then create a new one (which starts a thread)
            with patch.object(mgr, "_run_tunnel"):
                result = mgr.create_tunnel("s1", "n1", 8080)
        assert result.id != "dead1"
        assert "dead1" not in mgr._tunnels


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestGetTunnelManager:
    def test_returns_same_instance(self):
        import app.tunnel_manager as tm
        old = tm._manager
        tm._manager = None
        try:
            mgr1 = get_tunnel_manager()
            mgr2 = get_tunnel_manager()
            assert mgr1 is mgr2
        finally:
            tm._manager = old
