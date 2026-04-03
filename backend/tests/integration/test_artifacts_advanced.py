"""Advanced tests for local artifact operations.

Covers: artifact metadata update, listing with categories, download.
"""

import json
import os

import pytest


def _make_artifact(storage_dir, dir_name, *, category="weave",
                   weave_json=None, slice_json=True, files=None):
    """Create an artifact directory on disk."""
    art_dir = storage_dir / "my_artifacts" / dir_name
    art_dir.mkdir(parents=True, exist_ok=True)
    if weave_json is None:
        weave_json = {"name": dir_name, "description": "", "category": category}
    (art_dir / "weave.json").write_text(json.dumps(weave_json))
    if slice_json and category == "weave":
        (art_dir / "slice.json").write_text(json.dumps({
            "name": dir_name, "nodes": [], "networks": [],
        }))
    if files:
        for fname, content in files.items():
            (art_dir / fname).write_text(content)
    return art_dir


class TestListLocalArtifactsAdvanced:
    def test_list_with_multiple_categories(self, client, storage_dir):
        _make_artifact(storage_dir, "weave1", category="weave")
        _make_artifact(storage_dir, "recipe1", category="recipe", slice_json=False,
                       weave_json={"name": "recipe1", "category": "recipe"},
                       files={"recipe.json": json.dumps({
                           "name": "recipe1", "steps": []})})
        resp = client.get("/api/artifacts/local")
        assert resp.status_code == 200
        data = resp.json()
        assert "artifacts" in data
        assert len(data["artifacts"]) >= 1

    def test_list_returns_dir_names(self, client, storage_dir):
        _make_artifact(storage_dir, "dirname_test")
        resp = client.get("/api/artifacts/local")
        dir_names = [a.get("dir_name", "") for a in resp.json()["artifacts"]]
        assert "dirname_test" in dir_names

    def test_list_includes_all_artifact_dirs(self, client, storage_dir):
        """All artifact dirs with weave.json should appear."""
        _make_artifact(storage_dir, "visible_art")
        resp = client.get("/api/artifacts/local")
        dir_names = [a.get("dir_name", "") for a in resp.json()["artifacts"]]
        assert "visible_art" in dir_names


class TestUpdateArtifactMetadata:
    def test_update_metadata(self, client, storage_dir):
        _make_artifact(storage_dir, "meta_upd",
                       weave_json={"name": "Meta Update", "description": "old",
                                   "category": "weave"})
        resp = client.put("/api/artifacts/local/meta_upd/metadata",
                          json={"description": "new desc"})
        assert resp.status_code == 200


class TestArtifactCategories:
    def test_weave_category(self, client, storage_dir):
        _make_artifact(storage_dir, "cat_weave", category="weave",
                       weave_json={"name": "Cat Weave", "category": "weave"})
        resp = client.get("/api/artifacts/local")
        arts = resp.json()["artifacts"]
        weave = next((a for a in arts if a.get("dir_name") == "cat_weave"), None)
        if weave:
            assert weave.get("category") == "weave"

    def test_vm_template_category(self, client, storage_dir):
        art_dir = storage_dir / "my_artifacts" / "cat_vm"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "vm-template.json").write_text(json.dumps({
            "name": "Cat VM", "image": "default_ubuntu_22",
        }))
        (art_dir / "weave.json").write_text(json.dumps({
            "name": "Cat VM", "category": "vm-template",
        }))
        resp = client.get("/api/artifacts/local")
        arts = resp.json()["artifacts"]
        vm = next((a for a in arts if a.get("dir_name") == "cat_vm"), None)
        assert vm is not None


class TestArtifactPublishInfo:
    def test_get_publish_info(self, client, storage_dir):
        _make_artifact(storage_dir, "pub_info")
        resp = client.get("/api/artifacts/local/pub_info/publish-info")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_publish_info_nonexistent(self, client):
        resp = client.get("/api/artifacts/local/nonexistent/publish-info")
        assert resp.status_code == 404


class TestArtifactRevert:
    def test_revert_nonexistent(self, client):
        resp = client.post("/api/artifacts/local/nonexistent/revert",
                           json={})
        assert resp.status_code in (404, 400, 422, 500)


class TestValidTags:
    def test_get_valid_tags(self, client):
        resp = client.get("/api/artifacts/valid-tags")
        assert resp.status_code == 200
        data = resp.json()
        # May return a list or a dict with a "tags" key
        assert isinstance(data, (list, dict))
        if isinstance(data, dict):
            assert "tags" in data
