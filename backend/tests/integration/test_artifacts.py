"""Tests for artifact CRUD endpoints (local and remote)."""

import json
import os
from unittest.mock import patch, AsyncMock, MagicMock

import httpx


class TestListLocalArtifacts:
    def test_local_empty_returns_empty_list(self, client):
        resp = client.get("/api/artifacts/local")
        assert resp.status_code == 200
        data = resp.json()
        assert "artifacts" in data
        assert isinstance(data["artifacts"], list)

    def test_local_returns_weave(self, client, storage_dir):
        # Create a weave artifact (slice.json + deploy.sh)
        art_dir = storage_dir / "my_artifacts" / "test_weave"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "slice.json").write_text(json.dumps({
            "format": "fabric-slice-v1",
            "name": "Test Weave",
            "nodes": [{"name": "n1"}],
            "networks": [],
        }))
        (art_dir / "deploy.sh").write_text("#!/bin/bash\necho deploy")
        (art_dir / "metadata.json").write_text(json.dumps({
            "name": "Test Weave",
            "description": "A test weave",
        }))

        resp = client.get("/api/artifacts/local")
        assert resp.status_code == 200
        data = resp.json()
        arts = data["artifacts"]
        assert len(arts) >= 1
        weave = next((a for a in arts if a["dir_name"] == "test_weave"), None)
        assert weave is not None
        assert weave["category"] == "weave"
        assert weave["name"] == "Test Weave"

    def test_local_returns_vm_template(self, client, storage_dir):
        art_dir = storage_dir / "my_artifacts" / "test_vm"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "vm-template.json").write_text(json.dumps({
            "name": "Test VM",
            "image": "ubuntu_22",
        }))

        resp = client.get("/api/artifacts/local")
        data = resp.json()
        vm = next((a for a in data["artifacts"] if a["dir_name"] == "test_vm"), None)
        assert vm is not None
        assert vm["category"] == "vm-template"

    def test_local_returns_recipe(self, client, storage_dir):
        art_dir = storage_dir / "my_artifacts" / "test_recipe"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "recipe.json").write_text(json.dumps({
            "name": "Test Recipe",
            "steps": [],
        }))

        resp = client.get("/api/artifacts/local")
        data = resp.json()
        recipe = next((a for a in data["artifacts"] if a["dir_name"] == "test_recipe"), None)
        assert recipe is not None
        assert recipe["category"] == "recipe"

    def test_local_skips_other_dirs(self, client, storage_dir):
        # A directory with no recognizable files should be skipped
        art_dir = storage_dir / "my_artifacts" / "random_dir"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "notes.txt").write_text("some notes")

        resp = client.get("/api/artifacts/local")
        data = resp.json()
        names = [a["dir_name"] for a in data["artifacts"]]
        assert "random_dir" not in names


class TestUpdateLocalMetadata:
    def test_update_name_and_description(self, client, storage_dir):
        art_dir = storage_dir / "my_artifacts" / "meta_test"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "slice.json").write_text(json.dumps({
            "format": "fabric-slice-v1", "nodes": [], "networks": [],
        }))
        (art_dir / "deploy.sh").write_text("#!/bin/bash")
        (art_dir / "metadata.json").write_text(json.dumps({
            "name": "Original",
            "description": "Old desc",
        }))

        resp = client.put("/api/artifacts/local/meta_test/metadata",
                          json={"name": "Updated", "description": "New desc"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["metadata"]["name"] == "Updated"
        assert data["metadata"]["description"] == "New desc"

        # Verify persisted on disk
        with open(art_dir / "metadata.json") as f:
            saved = json.load(f)
        assert saved["name"] == "Updated"

    def test_update_nonexistent_returns_404(self, client):
        resp = client.put("/api/artifacts/local/nonexistent/metadata",
                          json={"name": "X"})
        assert resp.status_code == 404


class TestListRemoteArtifacts:
    def test_remote_list_success(self, client):
        mock_artifacts = [
            {
                "uuid": "art-uuid-1",
                "title": "Test Artifact",
                "tags": ["fabric"],
                "description_short": "Short desc",
                "description_long": "Long desc [LoomAI Weave]",
            }
        ]
        with patch("app.routes.artifacts._fetch_all_artifacts",
                    new_callable=AsyncMock, return_value=mock_artifacts):
            resp = client.get("/api/artifacts/remote")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 1
        assert len(data["artifacts"]) == 1
        assert data["artifacts"][0]["uuid"] == "art-uuid-1"
        assert "tags" in data

    def test_remote_list_handles_api_error(self, client):
        with patch("app.routes.artifacts._fetch_all_artifacts",
                    new_callable=AsyncMock,
                    side_effect=Exception("connection refused")):
            resp = client.get("/api/artifacts/remote")
        assert resp.status_code == 502


class TestRefreshRemoteArtifacts:
    def test_refresh_clears_cache_and_fetches(self, client):
        from app.routes.artifacts import _cache
        _cache["fetched_at"] = 999  # pretend it was cached

        mock_artifacts = [
            {
                "uuid": "art-uuid-2",
                "title": "Refreshed",
                "tags": [],
                "description_short": "Short",
                "description_long": "",
            }
        ]
        with patch("app.routes.artifacts._fetch_all_artifacts",
                    new_callable=AsyncMock, return_value=mock_artifacts):
            resp = client.post("/api/artifacts/remote/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 1


class TestGetRemoteArtifact:
    def test_get_existing_artifact(self, client):
        mock_art = {
            "uuid": "art-uuid-3",
            "title": "Single Artifact",
            "tags": [{"tag": "fabric"}],
            "description_short": "Short",
            "description_long": "Detailed [LoomAI Weave]",
        }
        with patch("app.routes.artifacts._fetch_artifact",
                    new_callable=AsyncMock, return_value=mock_art):
            resp = client.get("/api/artifacts/remote/art-uuid-3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["uuid"] == "art-uuid-3"
        assert data["category"] == "weave"
        # Tags should be normalized to strings
        assert isinstance(data["tags"][0], str)

    def test_get_remote_artifact_api_error(self, client):
        with patch("app.routes.artifacts._fetch_artifact",
                    new_callable=AsyncMock,
                    side_effect=Exception("not found")):
            resp = client.get("/api/artifacts/remote/nonexistent-uuid")
        assert resp.status_code == 502


class TestValidTags:
    def test_valid_tags_success(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"tag": "fabric", "restricted": False},
                {"tag": "admin-only", "restricted": True},
            ]
        }

        import app.http_pool as pool
        with patch.object(pool.fabric_client, "get",
                          new=AsyncMock(return_value=mock_resp)):
            resp = client.get("/api/artifacts/valid-tags")
        assert resp.status_code == 200
        data = resp.json()
        assert "tags" in data
        assert len(data["tags"]) == 2
        assert data["tags"][0]["tag"] == "fabric"
        assert data["tags"][1]["restricted"] is True


class TestDeleteRemoteArtifact:
    def test_delete_without_token(self, client, storage_dir):
        # Remove the token file to simulate no auth
        token_path = storage_dir / "fabric_config" / "id_token.json"
        token_path.write_text("{}")

        resp = client.delete("/api/artifacts/remote/some-uuid")
        assert resp.status_code == 401

    def test_delete_success(self, client):
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("app.routes.artifacts._get_auth_headers",
                    return_value={"Authorization": "Bearer fake"}), \
             patch("app.routes.artifacts.fabric_client") as mock_client:
            mock_client.delete = AsyncMock(return_value=mock_resp)
            resp = client.delete("/api/artifacts/remote/del-uuid")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert data["uuid"] == "del-uuid"


class TestDeleteArtifactVersion:
    def test_delete_version_success(self, client):
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("app.routes.artifacts._get_auth_headers",
                    return_value={"Authorization": "Bearer fake"}), \
             patch("app.routes.artifacts.fabric_client") as mock_client:
            mock_client.delete = AsyncMock(return_value=mock_resp)
            resp = client.delete("/api/artifacts/remote/art-uuid/version/ver-uuid")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert data["version_uuid"] == "ver-uuid"


class TestMyArtifacts:
    def test_my_artifacts_returns_structure(self, client, storage_dir):
        # Create a local weave artifact
        art_dir = storage_dir / "my_artifacts" / "my_weave"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "slice.json").write_text(json.dumps({
            "format": "fabric-slice-v1", "nodes": [], "networks": [],
        }))
        (art_dir / "deploy.sh").write_text("#!/bin/bash")
        (art_dir / "metadata.json").write_text(json.dumps({
            "name": "My Weave",
            "source": "artifact-manager",
            "artifact_uuid": "remote-uuid-1",
        }))

        with patch("app.routes.artifacts._get_current_user_identity",
                    return_value=("user@example.com", "Test User")), \
             patch("app.routes.artifacts._fetch_all_artifacts",
                    new_callable=AsyncMock, return_value=[]):
            resp = client.get("/api/artifacts/my")
        assert resp.status_code == 200
        data = resp.json()
        assert "local_artifacts" in data
        assert "authored_remote_only" in data
        assert "user_email" in data
        assert data["user_email"] == "user@example.com"
        assert len(data["local_artifacts"]) >= 1
