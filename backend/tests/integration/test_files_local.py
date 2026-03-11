"""Tests for container file operations."""

import os


class TestListFiles:
    def test_list_root(self, client, storage_dir):
        resp = client.get("/api/files?path=.")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_includes_dirs(self, client, storage_dir):
        resp = client.get("/api/files?path=.")
        names = [f["name"] for f in resp.json()]
        assert "my_artifacts" in names


class TestMkdir:
    def test_create_directory(self, client, storage_dir):
        resp = client.post("/api/files/mkdir", json={"name": "test_dir"})
        assert resp.status_code == 200
        assert (storage_dir / "test_dir").is_dir()


class TestReadWriteFile:
    def test_write_and_read_file(self, client, storage_dir):
        # Write
        resp = client.put("/api/files/content",
                          json={"path": "test_file.txt", "content": "hello world"})
        assert resp.status_code == 200

        # Read
        resp = client.get("/api/files/content?path=test_file.txt")
        assert resp.status_code == 200
        assert resp.json()["content"] == "hello world"
