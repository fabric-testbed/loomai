"""Tests for artifact CRUD endpoints (local and remote)."""

import json
import os
import shutil
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import httpx
import pytest


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


class TestValidateArtifact:
    def test_validate_local_shipped_weave_has_no_errors(self, client, storage_dir):
        src = Path(__file__).resolve().parents[2] / "default_artifacts" / "Hello_FABRIC"
        dst = storage_dir / "my_artifacts" / "Hello_FABRIC"
        shutil.copytree(src, dst)

        resp = client.post("/api/artifacts/validate", json={"dir_name": "Hello_FABRIC"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["artifact_type"] == "weave"
        assert data["error_count"] == 0
        assert data["source"] == {"type": "local", "dir_name": "Hello_FABRIC"}

    def test_validate_inline_reports_actionable_findings(self, client):
        resp = client.post("/api/artifacts/validate", json={
            "weave_json": {
                "name": "Bad Weave",
                "run_script": "weave.sh",
                "args": {"SLICE_NAME": "bad-shape"},
            },
            "scripts": {
                "weave.sh": "#!/bin/bash\npython3 run.py\nmkdir -p result\necho ok > result/output.txt\n",
            },
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert data["error_count"] >= 1
        codes = {finding["code"]: finding for finding in data["findings"]}
        assert codes["WEAVE_ARGS_SHAPE"]["path"] == "weave.json"
        assert codes["WEAVE_ARGS_SHAPE"]["line"] >= 1
        assert codes["SCRIPT_SET_E_MISSING"]["path"] == "weave.sh"
        assert codes["SCRIPT_PROGRESS_MARKER_MISSING"]["path"] == "weave.sh"
        assert codes["SCRIPT_RESULTS_PATH_CONVENTION"]["line"] in {3, 4}
        assert "fix-hint" in codes["SCRIPT_RESULTS_PATH_CONVENTION"]

    def test_validate_local_does_not_mutate_artifact(self, client, storage_dir):
        art_dir = storage_dir / "my_artifacts" / "Read_Only_Check"
        art_dir.mkdir(parents=True)
        weave_json = '{"run_script": "weave.sh", "args": "bad"}'
        weave_sh = "#!/bin/bash\npython3 run.py\n"
        (art_dir / "weave.json").write_text(weave_json)
        (art_dir / "weave.sh").write_text(weave_sh)

        resp = client.post("/api/artifacts/validate", json={"dir_name": "Read_Only_Check"})

        assert resp.status_code == 200
        assert (art_dir / "weave.json").read_text() == weave_json
        assert (art_dir / "weave.sh").read_text() == weave_sh


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
        detail = resp.json()["detail"]
        assert detail["error"] == "ARTIFACT_NOT_LINKED"
        assert "Cannot update" in detail["detail"]

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
        detail = resp.json()["detail"]
        assert detail["error"] == "ARTIFACT_NOT_LINKED"
        assert "Cannot fork" in detail["detail"]

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


class TestErrorEnvelopes:
    """FC18-2: structured error envelopes for the artifact routes."""

    def test_publish_missing_local_artifact_envelope(self, client):
        """Publishing an absent local dir_name → 404 ARTIFACT_NOT_FOUND envelope."""
        with patch("app.routes.artifacts._get_auth_headers",
                    return_value={"Authorization": "Bearer fake"}):
            resp = client.post("/api/artifacts/publish", json={
                "dir_name": "does_not_exist",
                "category": "weave",
                "title": "Nope",
                "description": "Test desc",
            })
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["error"] == "ARTIFACT_NOT_FOUND"
        assert "does_not_exist" in detail["detail"]
        assert detail["dir_name"] == "does_not_exist"

    def test_publish_without_token_envelope(self, client, storage_dir):
        """Publishing with no token → 401 ARTIFACT_TOKEN_MISSING envelope."""
        token_path = storage_dir / "fabric_config" / "id_token.json"
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text("{}")

        resp = client.post("/api/artifacts/publish", json={
            "dir_name": "whatever",
            "category": "weave",
            "title": "Nope",
            "description": "Test desc",
        })
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert detail["error"] == "ARTIFACT_TOKEN_MISSING"

    def test_download_upstream_error_envelope(self, client):
        """Upstream fetch failure on download → 502 ARTIFACT_UPSTREAM_ERROR envelope."""
        with patch("app.routes.artifacts._fetch_artifact",
                    new_callable=AsyncMock,
                    side_effect=Exception("Bearer secret=leaked-token upstream 503 /home/fabric/x")):
            resp = client.post("/api/artifacts/download", json={"uuid": "up-err-uuid"})
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail["error"] == "ARTIFACT_UPSTREAM_ERROR"
        assert detail["uuid"] == "up-err-uuid"
        # Sanitizer redacts secret assignments and absolute paths from upstream text.
        assert "leaked-token" not in detail["detail"]
        assert "/home/fabric" not in detail["detail"]

    def test_download_unsafe_archive_envelope(self, client, storage_dir):
        """A downloaded archive with traversal paths → 400 ARTIFACT_ARCHIVE_UNSAFE envelope."""
        import io
        import tarfile

        (storage_dir / "my_artifacts").mkdir(parents=True, exist_ok=True)

        # Build a tarball whose member escapes the extraction root.
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            data = b"malicious"
            info = tarfile.TarInfo(name="../evil.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        archive_bytes = buf.getvalue()

        art = {
            "uuid": "unsafe-uuid",
            "title": "Unsafe",
            "tags": [{"tag": "fabric"}],
            "description_short": "s",
            "description_long": "d",
            "versions": [{"uuid": "v1", "active": True, "urn": "urn:x"}],
        }
        content_resp = MagicMock()
        content_resp.content = archive_bytes
        content_resp.raise_for_status = MagicMock()

        with patch("app.routes.artifacts._fetch_artifact",
                    new_callable=AsyncMock, return_value=art), \
             patch("app.routes.artifacts._get_auth_headers",
                    return_value={"Authorization": "Bearer fake"}), \
             patch("app.routes.artifacts.ai_client.get",
                    new=AsyncMock(return_value=content_resp)):
            resp = client.post("/api/artifacts/download", json={"uuid": "unsafe-uuid"})
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["error"] == "ARTIFACT_ARCHIVE_UNSAFE"


class TestUpdateRemoteArtifactTags:
    """The Artifact Manager clears tags on a PUT that omits them; updates must not."""

    def _put_resp(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"uuid": "art-1", "title": "T", "tags": []})
        return resp

    def _get_resp(self, tags):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"uuid": "art-1", "tags": tags})
        return resp

    def _update(self, client, body, *, current_tags=None, get_error=None):
        with patch("app.routes.artifacts._get_auth_headers",
                   return_value={"Authorization": "Bearer fake"}), \
             patch("app.routes.artifacts.fabric_client") as mock_client:
            if get_error is not None:
                mock_client.get = AsyncMock(side_effect=get_error)
            else:
                mock_client.get = AsyncMock(return_value=self._get_resp(current_tags))
            mock_client.put = AsyncMock(return_value=self._put_resp())
            resp = client.put("/api/artifacts/remote/art-1", json=body)
        return resp, mock_client

    def test_update_without_tags_resends_current_tags(self, client):
        resp, mc = self._update(client, {"title": "New title"},
                                current_tags=["loomai:weave", "gpu"])

        assert resp.status_code == 200
        sent = mc.put.call_args.kwargs["json"]
        assert sent["title"] == "New title"
        assert sent["tags"] == ["loomai:weave", "gpu"]

    def test_category_without_tags_adds_category_tag_to_current(self, client):
        resp, mc = self._update(client, {"title": "T", "category": "weave"},
                                current_tags=["gpu"])

        assert resp.status_code == 200
        assert mc.put.call_args.kwargs["json"]["tags"] == ["gpu", "loomai:weave"]

    def test_category_tag_not_duplicated(self, client):
        resp, mc = self._update(client, {"title": "T", "category": "weave"},
                                current_tags=["loomai:weave"])

        assert resp.status_code == 200
        assert mc.put.call_args.kwargs["json"]["tags"] == ["loomai:weave"]

    def test_explicit_tags_are_sent_without_reading_current(self, client):
        resp, mc = self._update(client, {"tags": ["gpu"], "category": "weave"},
                                current_tags=["old"])

        assert resp.status_code == 200
        assert mc.get.await_count == 0
        assert set(mc.put.call_args.kwargs["json"]["tags"]) == {"gpu", "loomai:weave"}

    def test_explicit_empty_tags_still_clear_them(self, client):
        resp, mc = self._update(client, {"tags": []}, current_tags=["old"])

        assert resp.status_code == 200
        assert mc.get.await_count == 0
        assert mc.put.call_args.kwargs["json"]["tags"] == []

    def test_unreadable_current_tags_block_the_update(self, client):
        resp, mc = self._update(client, {"title": "New title"},
                                get_error=httpx.ConnectError("down"))

        assert resp.status_code == 502
        assert "would have cleared" in json.dumps(resp.json())
        assert mc.put.await_count == 0


class TestArchiveLinkMembers:
    def _download(self, client, archive_bytes):
        art = {
            "uuid": "link-uuid",
            "title": "Linky",
            "tags": [{"tag": "fabric"}],
            "description_short": "s",
            "description_long": "d",
            "versions": [{"uuid": "v1", "active": True, "urn": "urn:x"}],
        }
        content_resp = MagicMock()
        content_resp.content = archive_bytes
        content_resp.raise_for_status = MagicMock()
        with patch("app.routes.artifacts._fetch_artifact",
                   new_callable=AsyncMock, return_value=art), \
             patch("app.routes.artifacts._get_auth_headers",
                   return_value={"Authorization": "Bearer fake"}), \
             patch("app.routes.artifacts.ai_client.get",
                   new=AsyncMock(return_value=content_resp)):
            return client.post("/api/artifacts/download", json={"uuid": "link-uuid"})

    @pytest.mark.parametrize("linktype", ["sym", "hard"])
    def test_link_members_rejected(self, client, storage_dir, linktype):
        """A symlink/hardlink to a path outside the archive, followed by a file
        under the link name, would overwrite the target (zip-slip); reject it."""
        import io
        import tarfile

        (storage_dir / "my_artifacts").mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            link = tarfile.TarInfo(name="cfg")
            link.type = tarfile.SYMTYPE if linktype == "sym" else tarfile.LNKTYPE
            link.linkname = "/home/fabric/work/fabric_config" if linktype == "sym" else "README.md"
            tf.addfile(link)
            data = b"evil"
            info = tarfile.TarInfo(name="cfg/id_token.json")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

        resp = self._download(client, buf.getvalue())

        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "ARTIFACT_ARCHIVE_UNSAFE"
