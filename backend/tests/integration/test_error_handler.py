"""Tests for error handler middleware behaviour.

Since the main app does not currently install a custom exception handler,
these tests verify FastAPI's default error propagation:
 - HTTPException with status 400 returns the original detail.
 - HTTPException with status 500 returns the detail as-is.
 - An unhandled exception returns a generic 500 with "Internal Server Error".

A small standalone FastAPI app is constructed in the fixture so the tests
are self-contained and don't depend on production routes.
"""

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

    @app.get("/unhandled")
    def unhandled_error():
        raise RuntimeError("unexpected crash in handler")

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
    def test_500_with_path_detail_is_returned(self, error_client):
        """A 500 HTTPException still includes its detail string."""
        resp = error_client.get("/raise-500-path")
        assert resp.status_code == 500
        assert "detail" in resp.json()

    def test_500_generic_detail_is_returned(self, error_client):
        resp = error_client.get("/raise-500-generic")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Something went wrong"


class TestUnhandledException:
    def test_unhandled_returns_500(self, error_client):
        resp = error_client.get("/unhandled")
        assert resp.status_code == 500
        # Starlette's default handler returns plain text for unhandled exceptions
        assert "Internal Server Error" in resp.text
