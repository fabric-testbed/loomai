"""Tests for jupyter/notebook routes — structured error envelopes (FC18-2)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


class TestLaunchNotebookErrors:
    def test_launch_missing_artifact_returns_envelope(self, client):
        resp = client.post("/api/notebooks/no-such-notebook/launch")
        assert resp.status_code == 404
        body = resp.json()
        assert body["detail"]["error"] == "NOTEBOOK_NOT_FOUND"
        assert "no-such-notebook" in body["detail"]["detail"]
        assert "not found" in body["detail"]["detail"]
        assert body["detail"]["name"] == "no-such-notebook"

    def test_launch_invalid_name_returns_envelope(self, client):
        # A whitespace-only name sanitizes to empty → 400
        resp = client.post("/api/notebooks/%20/launch")
        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"]["error"] == "NOTEBOOK_NAME_INVALID"
        assert "Notebook name" in body["detail"]["detail"]


class TestResetNotebookErrors:
    def test_reset_without_original_returns_envelope(self, client):
        resp = client.post("/api/notebooks/never-launched/reset")
        assert resp.status_code == 404
        body = resp.json()
        assert body["detail"]["error"] == "NOTEBOOK_ORIGINAL_NOT_FOUND"
        assert "never-launched" in body["detail"]["detail"]
        assert body["detail"]["name"] == "never-launched"


class TestPublishForkErrors:
    def _publish_body(self):
        return {"title": "Forked Notebook", "description": "A test fork"}

    def _make_workspace(self, storage_dir, name):
        work_dir = storage_dir / "notebooks" / name
        work_dir.mkdir(parents=True)
        (work_dir / "demo.ipynb").write_text("{}")
        return work_dir

    def test_publish_without_workspace_returns_envelope(self, client):
        resp = client.post("/api/notebooks/no-workspace/publish-fork",
                           json=self._publish_body())
        assert resp.status_code == 404
        body = resp.json()
        assert body["detail"]["error"] == "NOTEBOOK_WORKSPACE_NOT_FOUND"
        assert "launch the notebook first" in body["detail"]["detail"]
        assert body["detail"]["name"] == "no-workspace"

    def test_publish_without_token_returns_envelope(self, client, storage_dir):
        self._make_workspace(storage_dir, "my-nb")
        with patch("app.routes.artifacts._get_auth_headers", return_value=None):
            resp = client.post("/api/notebooks/my-nb/publish-fork",
                               json=self._publish_body())
        assert resp.status_code == 401
        body = resp.json()
        assert body["detail"]["error"] == "NOTEBOOK_TOKEN_MISSING"
        assert "log in" in body["detail"]["detail"]

    def test_publish_upstream_error_returns_envelope(self, client, storage_dir):
        self._make_workspace(storage_dir, "my-nb2")

        request = httpx.Request("POST", "https://artifacts.example/api/artifacts")
        response = httpx.Response(403, text="permission denied for project",
                                  request=request)
        err = httpx.HTTPStatusError("upstream error", request=request,
                                    response=response)
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=err)

        with patch("app.routes.artifacts._get_auth_headers",
                   return_value={"Authorization": "Bearer fake"}), \
             patch("app.routes.jupyter.fabric_client", mock_client):
            resp = client.post("/api/notebooks/my-nb2/publish-fork",
                               json=self._publish_body())

        # Upstream status code is passed through unchanged
        assert resp.status_code == 403
        body = resp.json()
        assert body["detail"]["error"] == "NOTEBOOK_UPSTREAM_ERROR"
        assert "permission denied" in body["detail"]["detail"]
        assert body["detail"]["upstream_status"] == 403
        assert body["detail"]["name"] == "my-nb2"

    def test_publish_connection_error_returns_envelope(self, client, storage_dir):
        self._make_workspace(storage_dir, "my-nb3")

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=RuntimeError("connection reset"))

        with patch("app.routes.artifacts._get_auth_headers",
                   return_value={"Authorization": "Bearer fake"}), \
             patch("app.routes.jupyter.fabric_client", mock_client):
            resp = client.post("/api/notebooks/my-nb3/publish-fork",
                               json=self._publish_body())

        assert resp.status_code == 502
        body = resp.json()
        assert body["detail"]["error"] == "NOTEBOOK_PUBLISH_FAILED"
        assert "connection reset" in body["detail"]["detail"]
