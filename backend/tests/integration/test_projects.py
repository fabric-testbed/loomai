"""Tests for project detail endpoints."""

from unittest.mock import patch, MagicMock, AsyncMock

import httpx


class TestProjectDetails:
    def test_get_project_details_success(self, client):
        """GET /api/projects/{uuid}/details with mocked UIS API."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "results": [{
                "uuid": "proj-uuid-123",
                "name": "Test Project",
                "description": "A test project",
                "project_type": "research",
                "active": True,
                "created": "2024-01-01",
                "communities": [],
                "tags": ["test"],
                "project_lead": None,
                "project_owners": [],
                "project_members": [],
                "project_creators": [],
                "project_funding": [],
            }]
        }

        mock_get = AsyncMock(return_value=mock_resp)
        with patch("app.routes.projects.fabric_client") as mock_client:
            mock_client.get = mock_get
            resp = client.get("/api/projects/proj-uuid-123/details")

        assert resp.status_code == 200
        data = resp.json()
        assert data["uuid"] == "proj-uuid-123"
        assert data["name"] == "Test Project"
        assert "slice_counts" in data
        assert "active" in data["slice_counts"]
        assert "total" in data["slice_counts"]

    def test_get_project_details_missing_token(self, client, storage_dir):
        """Removing the token file should yield a 400 error."""
        import os
        token_path = storage_dir / "fabric_config" / "id_token.json"
        if token_path.exists():
            os.remove(token_path)

        resp = client.get("/api/projects/some-uuid/details")
        assert resp.status_code == 400
        assert "token" in resp.json()["detail"].lower()

    def test_get_project_details_uis_error(self, client):
        """UIS API failure should return 502."""
        mock_get = AsyncMock(side_effect=httpx.HTTPError("502 Bad Gateway"))

        with patch("app.routes.projects.fabric_client") as mock_client:
            mock_client.get = mock_get
            resp = client.get("/api/projects/bad-uuid/details")

        assert resp.status_code == 502
