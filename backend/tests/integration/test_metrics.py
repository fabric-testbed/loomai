"""Tests for Prometheus metrics proxy endpoints."""

import json
from unittest.mock import patch, AsyncMock, MagicMock

import httpx
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_prom_response(result: list[dict]):
    """Create a mock httpx Response for a Prometheus instant query."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "status": "success",
        "data": {"resultType": "vector", "result": result},
    }
    return mock_resp


def _prom_entry(metric: dict, value: float) -> dict:
    return {"metric": metric, "value": [1700000000, str(value)]}


# ---------------------------------------------------------------------------
# GET /metrics/site/{name}
# ---------------------------------------------------------------------------

class TestSiteMetrics:
    def test_returns_site_metrics(self, client):
        """GET /metrics/site/RENC should return CPU load and dataplane traffic."""
        load_entry = _prom_entry({"rack": "renc", "instance": "w1"}, 2.5)
        dp_in_entry = _prom_entry({"rack": "renc"}, 1000000)
        dp_out_entry = _prom_entry({"rack": "renc"}, 500000)

        async def mock_get(url, params=None):
            query = params.get("query", "")
            if "node_load1" in query:
                return _mock_prom_response([load_entry])
            elif "node_load5" in query:
                return _mock_prom_response([load_entry])
            elif "node_load15" in query:
                return _mock_prom_response([load_entry])
            elif "dataplaneInBits" in query:
                return _mock_prom_response([dp_in_entry])
            elif "dataplaneOutBits" in query:
                return _mock_prom_response([dp_out_entry])
            return _mock_prom_response([])

        with patch("app.routes.metrics.metrics_client") as mock_client:
            mock_client.get = AsyncMock(side_effect=mock_get)
            resp = client.get("/api/metrics/site/RENC")

        assert resp.status_code == 200
        data = resp.json()
        assert data["site"] == "RENC"
        assert "node_load1" in data
        assert "dataplaneInBits" in data
        assert "dataplaneOutBits" in data
        assert len(data["node_load1"]) == 1
        assert data["node_load1"][0]["metric"]["rack"] == "renc"

    def test_site_metrics_empty_results(self, client):
        """GET /api/metrics/site/UNKNOWN should return empty metric lists."""
        with patch("app.routes.metrics.metrics_client") as mock_client:
            mock_client.get = AsyncMock(return_value=_mock_prom_response([]))
            resp = client.get("/api/metrics/site/UNKNOWN")

        assert resp.status_code == 200
        data = resp.json()
        assert data["site"] == "UNKNOWN"
        assert data["node_load1"] == []

    def test_site_metrics_prometheus_error(self, client):
        """GET /api/metrics/site/X should return 502 on Prometheus failure."""
        with patch("app.routes.metrics.metrics_client") as mock_client:
            mock_client.get = AsyncMock(side_effect=httpx.HTTPError("connection failed"))
            resp = client.get("/api/metrics/site/RENC")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# GET /metrics/link/{a}/{b}
# ---------------------------------------------------------------------------

class TestLinkMetrics:
    def test_returns_link_metrics(self, client):
        """GET /metrics/link/RENC/UCSD should return bidirectional traffic."""
        in_entry = _prom_entry({"src_rack": "renc", "dst_rack": "ucsd"}, 2000000)
        out_entry = _prom_entry({"src_rack": "renc", "dst_rack": "ucsd"}, 1500000)
        rev_in = _prom_entry({"src_rack": "ucsd", "dst_rack": "renc"}, 1000000)
        rev_out = _prom_entry({"src_rack": "ucsd", "dst_rack": "renc"}, 800000)

        call_count = 0

        async def mock_get(url, params=None):
            nonlocal call_count
            query = params.get("query", "")
            call_count += 1

            if 'src_rack="renc"' in query and "InBits" in query:
                return _mock_prom_response([in_entry])
            elif 'src_rack="renc"' in query and "OutBits" in query:
                return _mock_prom_response([out_entry])
            elif 'src_rack="ucsd"' in query and "InBits" in query:
                return _mock_prom_response([rev_in])
            elif 'src_rack="ucsd"' in query and "OutBits" in query:
                return _mock_prom_response([rev_out])
            return _mock_prom_response([])

        with patch("app.routes.metrics.metrics_client") as mock_client:
            mock_client.get = AsyncMock(side_effect=mock_get)
            resp = client.get("/api/metrics/link/RENC/UCSD")

        assert resp.status_code == 200
        data = resp.json()
        assert data["site_a"] == "RENC"
        assert data["site_b"] == "UCSD"
        assert "a_to_b_in" in data
        assert "a_to_b_out" in data
        assert "b_to_a_in" in data
        assert "b_to_a_out" in data
        assert len(data["a_to_b_in"]) == 1

    def test_link_metrics_prometheus_error(self, client):
        """GET /api/metrics/link/X/Y should return 502 on Prometheus failure."""
        with patch("app.routes.metrics.metrics_client") as mock_client:
            mock_client.get = AsyncMock(side_effect=httpx.HTTPError("timeout"))
            resp = client.get("/api/metrics/link/RENC/UCSD")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# _simplify helper
# ---------------------------------------------------------------------------

class TestSimplify:
    def test_simplify_multiple_results(self):
        """_simplify should convert Prometheus results to simplified pairs."""
        from app.routes.metrics import _simplify
        results = [
            {"metric": {"rack": "renc", "instance": "w1"}, "value": [1700000000, "2.5"]},
            {"metric": {"rack": "renc", "instance": "w2"}, "value": [1700000000, "1.2"]},
        ]
        out = _simplify(results)
        assert len(out) == 2
        assert out[0]["metric"]["instance"] == "w1"
        assert out[1]["metric"]["instance"] == "w2"

    def test_simplify_empty(self):
        """_simplify with empty list should return empty list."""
        from app.routes.metrics import _simplify
        assert _simplify([]) == []

    def test_simplify_missing_fields(self):
        """_simplify should handle missing metric/value fields gracefully."""
        from app.routes.metrics import _simplify
        results = [{"metric": {}, "value": [None, None]}]
        out = _simplify(results)
        assert len(out) == 1
        assert out[0]["metric"] == {}
