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
        # Create a weave artifact with weave.json marker
        art_dir = storage_dir / "my_artifacts" / "test_weave"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "slice.json").write_text(json.dumps({
            "format": "fabric-slice-v1",
            "name": "Test Weave",
            "nodes": [{"name": "n1"}],
            "networks": [],
        }))
        (art_dir / "weave.json").write_text(json.dumps({
            "run_script": "weave.sh",
            "log_file": "weave.log",
        }))
        (art_dir / "weave.json").write_text(json.dumps({
            "run_script": "weave.sh",
            "log_file": "weave.log",
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
        (art_dir / "weave.json").write_text(json.dumps({
            "run_script": "weave.sh",
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
        with open(art_dir / "weave.json") as f:
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
        # Create a local weave artifact with weave.json marker
        art_dir = storage_dir / "my_artifacts" / "my_weave"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "slice.json").write_text(json.dumps({
            "format": "fabric-slice-v1", "nodes": [], "networks": [],
        }))
        (art_dir / "weave.json").write_text(json.dumps({
            "run_script": "weave.sh",
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


class TestPublishInfo:
    """Tests for GET /artifacts/local/{dir_name}/publish-info."""

    def test_publish_info_local_only(self, client, storage_dir):
        """Local-only artifact (no artifact_uuid) → can_update=False, can_fork=False."""
        art_dir = storage_dir / "my_artifacts" / "local_only"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "weave.json").write_text(json.dumps({
            "name": "Local Weave",
            "run_script": "weave.sh",
        }))

        resp = client.get("/api/artifacts/local/local_only/publish-info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["can_update"] is False
        assert data["can_fork"] is False
        assert data["is_author"] is False
        assert data["artifact_uuid"] is None

    def test_publish_info_author(self, client, storage_dir):
        """Author of linked artifact → can_update=True, can_fork=True."""
        art_dir = storage_dir / "my_artifacts" / "authored_weave"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "weave.json").write_text(json.dumps({
            "name": "Authored Weave",
            "artifact_uuid": "author-uuid-1",
            "source": "artifact-manager",
        }))

        mock_remote = {
            "uuid": "author-uuid-1",
            "title": "Remote Authored",
            "visibility": "public",
            "created_by": {"email": "user@example.com"},
            "authors": [],
            "tags": [],
        }

        with patch("app.routes.artifacts._fetch_artifact",
                    new_callable=AsyncMock, return_value=mock_remote), \
             patch("app.routes.artifacts._get_current_user_identity",
                    return_value=("user@example.com", "Test User")):
            resp = client.get("/api/artifacts/local/authored_weave/publish-info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["can_update"] is True
        assert data["can_fork"] is True
        assert data["is_author"] is True
        assert data["artifact_uuid"] == "author-uuid-1"
        assert data["remote_title"] == "Remote Authored"

    def test_publish_info_not_author(self, client, storage_dir):
        """Non-author of linked artifact → can_update=False, can_fork=True."""
        art_dir = storage_dir / "my_artifacts" / "foreign_weave"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "weave.json").write_text(json.dumps({
            "name": "Foreign Weave",
            "artifact_uuid": "foreign-uuid-1",
            "source": "artifact-manager",
        }))

        mock_remote = {
            "uuid": "foreign-uuid-1",
            "title": "Someone Else's Weave",
            "visibility": "public",
            "created_by": {"email": "other@example.com"},
            "authors": [{"email": "other@example.com"}],
            "tags": [],
        }

        with patch("app.routes.artifacts._fetch_artifact",
                    new_callable=AsyncMock, return_value=mock_remote), \
             patch("app.routes.artifacts._get_current_user_identity",
                    return_value=("user@example.com", "Test User")):
            resp = client.get("/api/artifacts/local/foreign_weave/publish-info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["can_update"] is False
        assert data["can_fork"] is True
        assert data["is_author"] is False

    def test_publish_info_not_found(self, client):
        resp = client.get("/api/artifacts/local/nonexistent/publish-info")
        assert resp.status_code == 404


class TestPublishAction:
    """Tests for the action parameter on POST /artifacts/publish."""

    def test_publish_action_update_requires_uuid(self, client, storage_dir):
        """action=update with no artifact_uuid → 400."""
        art_dir = storage_dir / "my_artifacts" / "no_uuid"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "weave.json").write_text(json.dumps({
            "name": "No UUID",
            "run_script": "weave.sh",
        }))

        with patch("app.routes.artifacts._get_auth_headers",
                    return_value={"Authorization": "Bearer fake"}):
            resp = client.post("/api/artifacts/publish", json={
                "dir_name": "no_uuid",
                "category": "weave",
                "title": "No UUID",
                "description": "Test desc",
                "action": "update",
            })
        assert resp.status_code == 400
        assert "Cannot update" in resp.json()["detail"]

    def test_publish_action_fork_requires_uuid(self, client, storage_dir):
        """action=fork with no artifact_uuid → 400."""
        art_dir = storage_dir / "my_artifacts" / "no_uuid_fork"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "weave.json").write_text(json.dumps({
            "name": "No UUID Fork",
            "run_script": "weave.sh",
        }))

        with patch("app.routes.artifacts._get_auth_headers",
                    return_value={"Authorization": "Bearer fake"}):
            resp = client.post("/api/artifacts/publish", json={
                "dir_name": "no_uuid_fork",
                "category": "weave",
                "title": "No UUID Fork",
                "description": "Test desc",
                "action": "fork",
            })
        assert resp.status_code == 400
        assert "Cannot fork" in resp.json()["detail"]

    def test_publish_action_fork_writes_provenance(self, client, storage_dir):
        """action=fork writes forked_from to weave.json."""
        art_dir = storage_dir / "my_artifacts" / "fork_test"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "weave.json").write_text(json.dumps({
            "name": "Fork Test",
            "artifact_uuid": "original-uuid-1",
            "source": "artifact-manager",
        }))

        mock_remote = {
            "uuid": "original-uuid-1",
            "title": "Original Artifact",
            "versions": [{"version": "1.0.0", "active": True, "uuid": "v1"}],
            "tags": [],
        }
        mock_create_resp = MagicMock()
        mock_create_resp.status_code = 200
        mock_create_resp.raise_for_status = MagicMock()
        mock_create_resp.json.return_value = {"uuid": "new-fork-uuid"}

        mock_update_resp = MagicMock()
        mock_update_resp.status_code = 200
        mock_update_resp.raise_for_status = MagicMock()
        mock_update_resp.json.return_value = {}

        mock_upload_resp = MagicMock()
        mock_upload_resp.status_code = 200
        mock_upload_resp.raise_for_status = MagicMock()
        mock_upload_resp.json.return_value = {"version": "1.0.0"}

        import app.http_pool as pool

        with patch("app.routes.artifacts._get_auth_headers",
                    return_value={"Authorization": "Bearer fake"}), \
             patch("app.routes.artifacts._fetch_artifact",
                    new_callable=AsyncMock, return_value=mock_remote), \
             patch.object(pool.fabric_client, "post",
                          new=AsyncMock(return_value=mock_create_resp)), \
             patch.object(pool.fabric_client, "put",
                          new=AsyncMock(return_value=mock_update_resp)), \
             patch.object(pool.ai_client, "post",
                          new=AsyncMock(return_value=mock_upload_resp)):
            resp = client.post("/api/artifacts/publish", json={
                "dir_name": "fork_test",
                "category": "weave",
                "title": "My Fork",
                "description": "Forked version",
                "action": "fork",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "published"
        assert data["uuid"] == "new-fork-uuid"
        assert data["forked_from"] == "original-uuid-1"

        # Verify forked_from was written to weave.json
        with open(art_dir / "weave.json") as f:
            meta = json.load(f)
        assert "forked_from" in meta
        assert meta["forked_from"]["artifact_uuid"] == "original-uuid-1"
        assert meta["forked_from"]["version"] == "1.0.0"
        assert meta["forked_from"]["title"] == "Original Artifact"
        assert meta["artifact_uuid"] == "new-fork-uuid"


class TestDownloadDedup:
    """Tests for download deduplication by artifact_uuid."""

    def test_find_local_by_uuid(self, storage_dir):
        """_find_local_by_uuid finds an existing artifact by UUID."""
        from app.routes.artifacts import _find_local_by_uuid

        art_dir = storage_dir / "my_artifacts" / "existing_art"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "weave.json").write_text(json.dumps({
            "name": "Existing",
            "artifact_uuid": "dedup-uuid-1",
        }))

        result = _find_local_by_uuid("dedup-uuid-1")
        assert result == "existing_art"

    def test_find_local_by_uuid_not_found(self, storage_dir):
        """_find_local_by_uuid returns None when UUID not present locally."""
        from app.routes.artifacts import _find_local_by_uuid

        # Ensure my_artifacts exists but doesn't have the UUID
        (storage_dir / "my_artifacts").mkdir(parents=True, exist_ok=True)
        result = _find_local_by_uuid("nonexistent-uuid")
        assert result is None
