"""Tests for project detail endpoints."""

from unittest.mock import patch

import httpx

from app.fabric_call_manager import reset_call_manager


class TestProjectDetails:
    def test_get_project_details_success(self, client):
        """GET /api/projects/{uuid}/details with mocked UIS API."""
        reset_call_manager()  # Ensure no stale cache from other tests
        mock_uis_response = {
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

        with patch("app.routes.projects._fetch_project_details", return_value=mock_uis_response):
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
        reset_call_manager()
        with patch(
            "app.routes.projects._fetch_project_details",
            side_effect=httpx.HTTPError("502 Bad Gateway"),
        ):
            resp = client.get("/api/projects/bad-uuid/details")

        assert resp.status_code == 502
