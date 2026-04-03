"""Advanced tests for container local file operations.

Covers: list, mkdir, read, write, delete, upload, download, download-folder,
path traversal protection, provisioning, boot config helpers.
"""

import io
import json
import os
import zipfile

import pytest


# ---------------------------------------------------------------------------
# List files
# ---------------------------------------------------------------------------

class TestListFilesAdvanced:
    def test_list_root_returns_known_dirs(self, client, storage_dir):
        resp = client.get("/api/files?path=.")
        assert resp.status_code == 200
        names = [e["name"] for e in resp.json()]
        assert "my_artifacts" in names
        assert "my_slices" in names

    def test_list_nonexistent_dir_returns_404(self, client):
        resp = client.get("/api/files?path=nonexistent_dir")
        assert resp.status_code == 404

    def test_list_hidden_dirs_excluded(self, client, storage_dir):
        """Internal dirs like .provisions should be filtered out."""
        (storage_dir / ".provisions").mkdir(exist_ok=True)
        (storage_dir / ".boot-config").mkdir(exist_ok=True)
        resp = client.get("/api/files?path=.")
        names = [e["name"] for e in resp.json()]
        assert ".provisions" not in names
        assert ".boot-config" not in names

    def test_list_shows_file_metadata(self, client, storage_dir):
        (storage_dir / "info.txt").write_text("data")
        resp = client.get("/api/files?path=.")
        entry = next(e for e in resp.json() if e["name"] == "info.txt")
        assert entry["type"] == "file"
        assert entry["size"] == 4
        assert "modified" in entry

    def test_list_subdir(self, client, storage_dir):
        sub = storage_dir / "my_artifacts" / "sub"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "a.txt").write_text("hello")
        resp = client.get("/api/files?path=my_artifacts/sub")
        assert resp.status_code == 200
        names = [e["name"] for e in resp.json()]
        assert "a.txt" in names


# ---------------------------------------------------------------------------
# Create directory (mkdir)
# ---------------------------------------------------------------------------

class TestMkdirAdvanced:
    def test_mkdir_in_root(self, client, storage_dir):
        resp = client.post("/api/files/mkdir", json={"name": "new_folder"})
        assert resp.status_code == 200
        assert resp.json()["created"] == "new_folder"
        assert (storage_dir / "new_folder").is_dir()

    def test_mkdir_nested(self, client, storage_dir):
        resp = client.post("/api/files/mkdir?path=my_artifacts",
                           json={"name": "nested_dir"})
        assert resp.status_code == 200
        assert (storage_dir / "my_artifacts" / "nested_dir").is_dir()

    def test_mkdir_idempotent(self, client, storage_dir):
        """Creating the same dir twice should not error."""
        client.post("/api/files/mkdir", json={"name": "idempotent"})
        resp = client.post("/api/files/mkdir", json={"name": "idempotent"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Read file content
# ---------------------------------------------------------------------------

class TestReadFileAdvanced:
    def test_read_nonexistent_returns_404(self, client):
        resp = client.get("/api/files/content?path=no_such_file.txt")
        assert resp.status_code == 404

    def test_read_returns_content_and_path(self, client, storage_dir):
        (storage_dir / "readme.md").write_text("# Hello")
        resp = client.get("/api/files/content?path=readme.md")
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "# Hello"
        assert data["path"] == "readme.md"

    def test_read_large_file_rejected(self, client, storage_dir):
        """Files > 5 MB should be rejected."""
        big = storage_dir / "big.bin"
        big.write_bytes(b"x" * (6 * 1024 * 1024))
        resp = client.get("/api/files/content?path=big.bin")
        assert resp.status_code == 400
        assert "too large" in resp.json()["detail"].lower()

    def test_read_binary_file_with_replace_errors(self, client, storage_dir):
        """Binary files should be read with errors='replace' (no crash)."""
        (storage_dir / "binary.dat").write_bytes(b"\xff\xfe\x00\x01")
        resp = client.get("/api/files/content?path=binary.dat")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Write file content
# ---------------------------------------------------------------------------

class TestWriteFileAdvanced:
    def test_write_creates_file(self, client, storage_dir):
        resp = client.put("/api/files/content",
                          json={"path": "new.txt", "content": "new content"})
        assert resp.status_code == 200
        assert (storage_dir / "new.txt").read_text() == "new content"

    def test_write_overwrites_existing(self, client, storage_dir):
        (storage_dir / "over.txt").write_text("old")
        resp = client.put("/api/files/content",
                          json={"path": "over.txt", "content": "replaced"})
        assert resp.status_code == 200
        assert (storage_dir / "over.txt").read_text() == "replaced"

    def test_write_returns_status(self, client, storage_dir):
        resp = client.put("/api/files/content",
                          json={"path": "status.txt", "content": "ok"})
        data = resp.json()
        assert data["status"] == "ok"
        assert data["path"] == "status.txt"


# ---------------------------------------------------------------------------
# Delete file/dir
# ---------------------------------------------------------------------------

class TestDeleteFileAdvanced:
    def test_delete_file(self, client, storage_dir):
        (storage_dir / "deleteme.txt").write_text("bye")
        resp = client.delete("/api/files?path=deleteme.txt")
        assert resp.status_code == 200
        assert not (storage_dir / "deleteme.txt").exists()

    def test_delete_directory(self, client, storage_dir):
        d = storage_dir / "rmdir"
        d.mkdir()
        (d / "child.txt").write_text("x")
        resp = client.delete("/api/files?path=rmdir")
        assert resp.status_code == 200
        assert not d.exists()

    def test_delete_root_rejected(self, client):
        resp = client.delete("/api/files?path=")
        assert resp.status_code == 400

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/files?path=no_such_thing")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Upload files (multipart)
# ---------------------------------------------------------------------------

class TestUploadFiles:
    def test_upload_single_file(self, client, storage_dir):
        content = b"file content here"
        resp = client.post(
            "/api/files/upload?path=.",
            files=[("files", ("upload.txt", io.BytesIO(content), "text/plain"))],
        )
        assert resp.status_code == 200
        assert "upload.txt" in resp.json()["uploaded"]
        assert (storage_dir / "upload.txt").read_bytes() == content

    def test_upload_multiple_files(self, client, storage_dir):
        resp = client.post(
            "/api/files/upload?path=.",
            files=[
                ("files", ("a.txt", io.BytesIO(b"aaa"), "text/plain")),
                ("files", ("b.txt", io.BytesIO(b"bbb"), "text/plain")),
            ],
        )
        assert resp.status_code == 200
        uploaded = resp.json()["uploaded"]
        assert "a.txt" in uploaded
        assert "b.txt" in uploaded

    def test_upload_to_subdir(self, client, storage_dir):
        sub = storage_dir / "uploads"
        sub.mkdir()
        resp = client.post(
            "/api/files/upload?path=uploads",
            files=[("files", ("data.csv", io.BytesIO(b"1,2,3"), "text/csv"))],
        )
        assert resp.status_code == 200
        assert (sub / "data.csv").exists()


# ---------------------------------------------------------------------------
# Download file
# ---------------------------------------------------------------------------

class TestDownloadFile:
    def test_download_existing_file(self, client, storage_dir):
        (storage_dir / "dl.txt").write_text("download me")
        resp = client.get("/api/files/download?path=dl.txt")
        assert resp.status_code == 200
        assert resp.content == b"download me"

    def test_download_nonexistent_returns_404(self, client):
        resp = client.get("/api/files/download?path=no_such.txt")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Download folder as zip
# ---------------------------------------------------------------------------

class TestDownloadFolder:
    def test_download_folder_as_zip(self, client, storage_dir):
        folder = storage_dir / "zipme"
        folder.mkdir()
        (folder / "a.txt").write_text("aaa")
        (folder / "b.txt").write_text("bbb")
        resp = client.get("/api/files/download-folder?path=zipme")
        assert resp.status_code == 200
        assert "application/zip" in resp.headers.get("content-type", "")
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        assert "a.txt" in names
        assert "b.txt" in names

    def test_download_folder_nonexistent_returns_404(self, client):
        resp = client.get("/api/files/download-folder?path=no_such_dir")
        assert resp.status_code == 404

    def test_download_folder_excludes_hidden(self, client, storage_dir):
        """Internal dirs (.provisions etc) should be excluded from zip."""
        folder = storage_dir / "zipme2"
        folder.mkdir()
        (folder / "visible.txt").write_text("yes")
        prov = folder / ".provisions"
        prov.mkdir()
        (prov / "secret.json").write_text("{}")
        resp = client.get("/api/files/download-folder?path=zipme2")
        assert resp.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        assert "visible.txt" in names
        assert not any(".provisions" in n for n in names)


# ---------------------------------------------------------------------------
# Path traversal protection
# ---------------------------------------------------------------------------

class TestPathTraversal:
    def test_traversal_blocked_in_list(self, client):
        resp = client.get("/api/files?path=../../etc")
        # Should either 404 (not found under base) or 400 (traversal)
        assert resp.status_code in (400, 404)

    def test_traversal_blocked_in_delete(self, client):
        resp = client.delete("/api/files?path=../../etc/passwd")
        assert resp.status_code in (400, 404)


# ---------------------------------------------------------------------------
# Provisioning endpoints
# ---------------------------------------------------------------------------

class TestProvisioning:
    def test_add_and_list_provisions(self, client, storage_dir):
        resp = client.post("/api/files/provisions", json={
            "source": "my_artifacts",
            "slice_name": "test-slice",
            "node_name": "node1",
            "dest": "/home/ubuntu/data",
        })
        assert resp.status_code == 200
        rule = resp.json()
        assert "id" in rule
        assert rule["source"] == "my_artifacts"

        # List
        list_resp = client.get("/api/files/provisions/test-slice")
        assert list_resp.status_code == 200
        rules = list_resp.json()
        assert len(rules) == 1
        assert rules[0]["id"] == rule["id"]

    def test_delete_provision(self, client, storage_dir):
        # Add
        resp = client.post("/api/files/provisions", json={
            "source": "my_artifacts",
            "slice_name": "prov-slice",
            "node_name": "n1",
            "dest": "/tmp/data",
        })
        rule_id = resp.json()["id"]

        # Delete
        del_resp = client.delete(f"/api/files/provisions/prov-slice/{rule_id}")
        assert del_resp.status_code == 200

        # Verify empty
        list_resp = client.get("/api/files/provisions/prov-slice")
        assert list_resp.json() == []


# ---------------------------------------------------------------------------
# Boot config helpers (via internal functions)
# ---------------------------------------------------------------------------

class TestBootConfig:
    def test_boot_config_dir_created(self, client, storage_dir):
        """The boot config directory is created lazily."""
        from app.routes.files import _boot_config_dir
        d = _boot_config_dir("test-slice")
        assert os.path.isdir(d)
        assert "test-slice" in d

    def test_load_boot_config_empty(self, client, storage_dir):
        """When no boot config exists, return empty structure."""
        from app.routes.files import _load_boot_config
        bc = _load_boot_config("no-slice", "no-node")
        assert "uploads" in bc or bc == {"uploads": [], "commands": [], "network": []}

    def test_load_boot_config_from_file(self, client, storage_dir):
        """Load boot config from JSON file."""
        from app.routes.files import _boot_config_dir
        d = _boot_config_dir("bc-slice")
        config = {
            "uploads": [{"source": "/tmp/a", "dest": "/home/ubuntu/a"}],
            "commands": [{"command": "echo hello", "order": 0}],
            "network": [],
        }
        with open(os.path.join(d, "node1.json"), "w") as f:
            json.dump(config, f)

        from app.routes.files import _load_boot_config
        result = _load_boot_config("bc-slice", "node1")
        assert len(result["uploads"]) == 1
        assert len(result["commands"]) == 1

    def test_get_boot_config_via_api(self, client, storage_dir):
        """GET /api/files/boot-config/{slice}/{node} should work."""
        from app.routes.files import _boot_config_dir
        d = _boot_config_dir("api-slice")
        config = {"uploads": [], "commands": [{"command": "echo test", "order": 0}], "network": []}
        with open(os.path.join(d, "n1.json"), "w") as f:
            json.dump(config, f)
        resp = client.get("/api/files/boot-config/api-slice/n1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["commands"]) == 1

    def test_save_boot_config_via_api(self, client, storage_dir):
        """PUT /api/files/boot-config/{slice}/{node} should save config."""
        # Create a draft slice first so _save_boot_config_to_fablib can find it
        create_resp = client.post("/api/slices?name=bc-save-test")
        sid = create_resp.json()["id"]
        client.post(f"/api/slices/{sid}/nodes",
                    json={"name": "bcnode", "site": "RENC"})
        resp = client.put("/api/files/boot-config/bc-save-test/bcnode",
                          json={"uploads": [],
                                "commands": [{"command": "apt update", "order": 0}],
                                "network": []})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["commands"]) == 1

    def test_save_boot_config_persists(self, client, storage_dir):
        """Boot config should be readable after saving."""
        from app.routes.files import _boot_config_dir
        client.put("/api/files/boot-config/persist-slice/node1",
                   json={"uploads": [],
                         "commands": [{"command": "echo persist", "order": 0}],
                         "network": []})
        resp = client.get("/api/files/boot-config/persist-slice/node1")
        assert resp.status_code == 200
        assert resp.json()["commands"][0]["command"] == "echo persist"


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------

class TestFileHelpers:
    def test_safe_path_normal(self, client, storage_dir):
        from app.routes.files import _safe_path
        base = str(storage_dir)
        result = _safe_path(base, "my_artifacts")
        assert result.endswith("my_artifacts")

    def test_safe_path_rejects_traversal(self, client, storage_dir):
        from app.routes.files import _safe_path
        base = str(storage_dir)
        with pytest.raises(Exception):
            _safe_path(base, "../../etc/passwd")

    def test_entry_dict(self, client, storage_dir):
        (storage_dir / "entry_test.txt").write_text("hello")
        from app.routes.files import _entry
        result = _entry(str(storage_dir / "entry_test.txt"))
        assert result["name"] == "entry_test.txt"
        assert result["type"] == "file"
        assert result["size"] == 5

    def test_entry_dir(self, client, storage_dir):
        (storage_dir / "entry_dir").mkdir()
        from app.routes.files import _entry
        result = _entry(str(storage_dir / "entry_dir"))
        assert result["type"] == "dir"

    def test_provisions_dir_created(self, client, storage_dir):
        from app.routes.files import _provisions_dir
        d = _provisions_dir()
        assert os.path.isdir(d)
        assert ".provisions" in d

    def test_load_provisions_empty(self, client, storage_dir):
        from app.routes.files import _load_provisions
        assert _load_provisions("nonexistent-slice") == []

    def test_save_and_load_provisions(self, client, storage_dir):
        from app.routes.files import _save_provisions, _load_provisions
        rules = [{"id": "r1", "source": "a", "dest": "b", "slice_name": "s", "node_name": "n"}]
        _save_provisions("roundtrip-slice", rules)
        loaded = _load_provisions("roundtrip-slice")
        assert len(loaded) == 1
        assert loaded[0]["id"] == "r1"

    def test_storage_dir(self, client, storage_dir):
        from app.routes.files import _storage_dir
        result = _storage_dir()
        assert os.path.isdir(result)

    def test_load_template_dir_none(self, client, storage_dir):
        from app.routes.files import _load_template_dir
        assert _load_template_dir("no-such-slice") is None

    def test_load_template_dir_returns_path(self, client, storage_dir):
        from app.routes.files import _load_template_dir
        boot_info_dir = storage_dir / ".boot_info"
        boot_info_dir.mkdir(exist_ok=True)
        info = {"template_dir": "/some/path"}
        with open(boot_info_dir / "my-slice.json", "w") as f:
            json.dump(info, f)
        assert _load_template_dir("my-slice") == "/some/path"

    def test_save_boot_config_internal(self, client, storage_dir):
        """Test _save_boot_config writes JSON file correctly."""
        from app.routes.files import _save_boot_config, _boot_config_dir
        config = {"uploads": [], "commands": [{"command": "ls"}], "network": []}
        _save_boot_config("save-test", "n1", config)
        d = _boot_config_dir("save-test")
        with open(os.path.join(d, "n1.json")) as f:
            saved = json.load(f)
        assert saved["commands"][0]["command"] == "ls"
