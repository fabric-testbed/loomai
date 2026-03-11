"""Tests for weave template CRUD."""

import json
import os
from unittest.mock import patch


class TestListTemplates:
    def test_list_returns_array(self, client):
        resp = client.get("/api/templates")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestSaveTemplate:
    def test_save_custom_template(self, client):
        # Create a slice first, then save as template
        create_resp = client.post("/api/slices?name=tmpl-source")
        sid = create_resp.json()["id"]
        client.post(f"/api/slices/{sid}/nodes",
                    json={"name": "n1", "site": "RENC"})

        resp = client.post("/api/templates",
                           json={"name": "My_Template",
                                 "slice_name": "tmpl-source"})
        assert resp.status_code == 200

    def test_saved_template_appears_in_list(self, client, storage_dir):
        # Create template directory manually
        tmpl_dir = storage_dir / "my_artifacts" / "Test_Tmpl"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "slice.json").write_text(json.dumps({
            "format": "fabric-slice-v1",
            "name": "Test Tmpl",
            "nodes": [],
            "networks": [],
        }))
        (tmpl_dir / "metadata.json").write_text(json.dumps({
            "name": "Test Tmpl",
            "description": "",
            "category": "weave",
        }))

        resp = client.get("/api/templates")
        names = [t["name"] for t in resp.json()]
        assert "Test Tmpl" in names


class TestDeleteTemplate:
    def test_delete_custom_template(self, client, storage_dir):
        # Create a template directory
        tmpl_dir = storage_dir / "my_artifacts" / "deleteme"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "slice.json").write_text(json.dumps({
            "format": "fabric-slice-v1",
            "name": "deleteme",
            "nodes": [],
            "networks": [],
        }))
        (tmpl_dir / "metadata.json").write_text(json.dumps({
            "name": "deleteme",
            "category": "weave",
        }))

        resp = client.delete("/api/templates/deleteme")
        assert resp.status_code == 200
        assert not tmpl_dir.exists()
