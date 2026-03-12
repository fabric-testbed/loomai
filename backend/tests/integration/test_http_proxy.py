"""Tests for HTTP proxy endpoint."""

from unittest.mock import patch, MagicMock


class TestHttpProxy:
    def test_proxy_returns_502_on_connection_error(self, client):
        """Proxy should return 502 when no SSH tunnel can be established."""
        with patch("app.routes.http_proxy._get_vm_ssh",
                    side_effect=Exception("No SSH connection")):
            resp = client.get("/api/proxy/test-slice/node1/8080/")
        assert resp.status_code == 502
        assert "Proxy error" in resp.text

    def test_proxy_returns_502_with_details(self, client):
        with patch("app.routes.http_proxy._get_vm_ssh",
                    side_effect=ValueError("Node node1 has no management IP")):
            resp = client.get("/api/proxy/test-slice/node1/9090/index.html")
        assert resp.status_code == 502
        assert "management IP" in resp.text

    def test_proxy_forwards_get_request(self, client):
        """Test that a successful proxy request returns the upstream response."""
        with patch("app.routes.http_proxy._proxy_request",
                    return_value=(200, {"Content-Type": "text/plain"}, b"Hello from VM")):
            resp = client.get("/api/proxy/test-slice/node1/8080/healthz")
        assert resp.status_code == 200
        assert resp.text == "Hello from VM"

    def test_proxy_forwards_post_request(self, client):
        with patch("app.routes.http_proxy._proxy_request",
                    return_value=(201, {"Content-Type": "application/json"}, b'{"status":"ok"}')):
            resp = client.post("/api/proxy/test-slice/node1/8080/api/data",
                               json={"key": "value"})
        assert resp.status_code == 201
        assert resp.json() == {"status": "ok"}

    def test_proxy_rewrites_html(self, client):
        """Test that HTML responses get base-tag and script injection."""
        html = b'<html><head><title>Test</title></head><body>Hello</body></html>'
        with patch("app.routes.http_proxy._proxy_request",
                    return_value=(200, {"Content-Type": "text/html"}, html)):
            resp = client.get("/api/proxy/myslice/mynode/3000/")
        assert resp.status_code == 200
        # The rewriter injects a <base> tag and a <script> interceptor
        assert "<base href=" in resp.text
        assert "<script>" in resp.text
        assert "rw(u)" in resp.text  # the rewrite function

    def test_proxy_strips_hop_by_hop_headers(self, client):
        """Hop-by-hop headers (transfer-encoding, connection) should be stripped."""
        with patch("app.routes.http_proxy._proxy_request",
                    return_value=(200,
                                  {"Content-Type": "text/plain",
                                   "Connection": "keep-alive",
                                   "Transfer-Encoding": "chunked"},
                                  b"data")):
            resp = client.get("/api/proxy/test-slice/node1/8080/test")
        assert resp.status_code == 200
        assert "connection" not in {k.lower() for k in resp.headers.keys()}
        assert "transfer-encoding" not in {k.lower() for k in resp.headers.keys()}

    def test_proxy_rewrites_redirect_location(self, client):
        """Absolute redirect Location headers should be rewritten through the proxy."""
        with patch("app.routes.http_proxy._proxy_request",
                    return_value=(302,
                                  {"Content-Type": "text/plain",
                                   "Location": "/login"},
                                  b"")):
            resp = client.get("/api/proxy/test-slice/node1/8080/dashboard",
                              follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/api/proxy/test-slice/node1/8080/login"


# TODO: WebSocket proxy tests (not applicable — this module only handles HTTP)
