"""Tests for tunnel API routes."""

from unittest.mock import patch, MagicMock

import pytest

from app.tunnel_manager import TunnelInfo


class TestListTunnels:
    def test_list_empty(self, client):
        with patch("app.routes.tunnels.get_tunnel_manager") as mock_mgr:
            mock_mgr.return_value.list_tunnels.return_value = []
            resp = client.get("/api/tunnels")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_tunnels(self, client):
        tunnel_data = [
            {"id": "t1", "slice_name": "s1", "node_name": "n1",
             "remote_port": 8080, "local_port": 9100, "status": "active",
             "created_at": 1000, "last_connection_at": 1000, "error": None},
        ]
        with patch("app.routes.tunnels.get_tunnel_manager") as mock_mgr:
            mock_mgr.return_value.list_tunnels.return_value = tunnel_data
            resp = client.get("/api/tunnels")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["id"] == "t1"


class TestCloseTunnel:
    def test_close_existing(self, client):
        with patch("app.routes.tunnels.get_tunnel_manager") as mock_mgr:
            mock_mgr.return_value.close_tunnel.return_value = True
            resp = client.delete("/api/tunnels/t1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "closed"

    def test_close_nonexistent(self, client):
        with patch("app.routes.tunnels.get_tunnel_manager") as mock_mgr:
            mock_mgr.return_value.close_tunnel.return_value = False
            resp = client.delete("/api/tunnels/nonexistent")
        assert resp.status_code == 404


class TestCreateTunnel:
    def test_create_returns_tunnel_info(self, client):
        import time
        mock_info = MagicMock()
        mock_info.to_dict.return_value = {
            "id": "new-tunnel",
            "slice_name": "s1",
            "node_name": "n1",
            "remote_port": 8080,
            "local_port": 9100,
            "status": "connecting",
            "created_at": time.time(),
            "last_connection_at": time.time(),
            "error": None,
        }
        with patch("app.routes.tunnels.get_tunnel_manager") as mock_mgr:
            mock_mgr.return_value.create_tunnel.return_value = mock_info
            resp = client.post("/api/tunnels", json={
                "slice_name": "s1", "node_name": "n1", "port": 8080,
            })
        assert resp.status_code == 200
        assert resp.json()["id"] == "new-tunnel"

    def test_create_runtime_error(self, client):
        with patch("app.routes.tunnels.get_tunnel_manager") as mock_mgr:
            mock_mgr.return_value.create_tunnel.side_effect = RuntimeError("No ports")
            resp = client.post("/api/tunnels", json={
                "slice_name": "s1", "node_name": "n1", "port": 8080,
            })
        assert resp.status_code == 503
