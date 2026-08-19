"""Tests for error handler middleware behaviour."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest


@pytest.fixture()
def error_app():
    """Create a minimal FastAPI app with routes that raise various errors."""
    app = FastAPI()

    @app.get("/raise-400")
    def raise_400():
        raise HTTPException(status_code=400, detail="Bad input data")

    @app.get("/raise-500-path")
    def raise_500_with_path():
        raise HTTPException(
            status_code=500,
            detail="Error reading /home/fabric/work/config/file.txt",
        )

    @app.get("/raise-500-generic")
    def raise_500_generic():
        raise HTTPException(status_code=500, detail="Something went wrong")

    @app.get("/raise-500-long-orchestrator")
    def raise_500_long_orchestrator():
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to delete Slices [abc] that are not yet stable, "
                "try again later. "
                + ("additional detail " * 40)
            ),
        )

    @app.get("/raise-500-secret-path")
    def raise_500_secret_path():
        raise HTTPException(
            status_code=500,
            detail=(
                "Traceback most recent call last\n"
                "File /home/fabric/work/config/secrets.py line 1\n"
                "FABRIC failed with token=super-secret-value password=hunter2 "
                "while reading /home/fabric/work/config/file.txt"
            ),
        )

    @app.get("/unhandled")
    def unhandled_error():
        raise RuntimeError("unexpected crash in handler")

    from app.error_handler import install_error_handlers
    install_error_handlers(app)

    return app


@pytest.fixture()
def error_client(error_app):
    with TestClient(error_app, raise_server_exceptions=False) as tc:
        yield tc


class TestHTTPException400:
    def test_400_returns_original_detail(self, error_client):
        resp = error_client.get("/raise-400")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Bad input data"


class TestHTTPException500:
    def test_500_with_path_detail_is_sanitized(self, error_client):
        resp = error_client.get("/raise-500-path")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Error reading [path]"

    def test_500_generic_detail_is_returned(self, error_client):
        resp = error_client.get("/raise-500-generic")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Something went wrong"

    def test_500_long_orchestrator_detail_keeps_actionable_prefix(self, error_client):
        resp = error_client.get("/raise-500-long-orchestrator")

        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert "not yet stable" in detail
        assert "try again later" in detail
        assert len(detail) <= 240

    def test_500_sensitive_detail_redacts_paths_and_secret_values(self, error_client):
        resp = error_client.get("/raise-500-secret-path")

        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert "/home/fabric" not in detail
        assert "super-secret-value" not in detail
        assert "hunter2" not in detail
        assert "token=[redacted]" in detail
        assert "password=[redacted]" in detail


class TestUnhandledException:
    def test_unhandled_returns_500(self, error_client):
        resp = error_client.get("/unhandled")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "An internal error occurred. Check server logs for details."
