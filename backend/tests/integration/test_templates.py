"""Tests for weave template CRUD."""

import json
import logging
import os
from unittest.mock import patch


class TestListTemplates:
    def test_list_returns_array(self, client):
        resp = client.get("/api/templates")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestSaveTemplate:
    def _create_and_save(self, client, tmpl_name="My_Template"):
        """Helper: create a draft slice with a node, save as template."""
        create_resp = client.post("/api/slices?name=tmpl-source")
        sid = create_resp.json()["id"]
        client.post(f"/api/slices/{sid}/nodes",
                    json={"name": "n1", "site": "RENC"})
        resp = client.post("/api/templates",
                           json={"name": tmpl_name,
                                 "slice_name": "tmpl-source"})
        return resp

    def test_save_custom_template(self, client):
        resp = self._create_and_save(client)
        assert resp.status_code == 200

    def test_save_template_creates_graphml(self, client, storage_dir):
        self._create_and_save(client, "Graphml_Test")
        graphml = storage_dir / "my_artifacts" / "Graphml_Test" / "slice_topology.graphml"
        assert graphml.exists()
        assert "<graphml>" in graphml.read_text()

    def test_save_template_creates_experiment_py(self, client, storage_dir):
        self._create_and_save(client, "Script_Test")
        exp_py = storage_dir / "my_artifacts" / "Script_Test" / "experiment.py"
        assert exp_py.exists()
        content = exp_py.read_text()
        assert "slice_topology.graphml" in content
        assert "def start(" in content
        assert "def stop(" in content
        assert "def monitor(" in content
        assert "my_slice.load(" in content
        assert "FABRIC_MAX_LEASE_HOURS" in content
        assert "lease_in_hours=max_lease_hours" in content
        assert "_submit_with_lease_policy(my_slice)" in content

    def test_save_template_creates_weave_sh(self, client, storage_dir):
        self._create_and_save(client, "Shell_Test")
        sh = storage_dir / "my_artifacts" / "Shell_Test" / "weave.sh"
        assert sh.exists()
        content = sh.read_text()
        assert "trap cleanup SIGTERM SIGINT" in content
        assert 'SCRIPT="experiment.py"' in content
        assert os.access(str(sh), os.X_OK)

    def test_save_template_weave_json_has_topology(self, client, storage_dir):
        self._create_and_save(client, "Topo_Test")
        wj = storage_dir / "my_artifacts" / "Topo_Test" / "weave.json"
        data = json.loads(wj.read_text())
        assert "nodes" in data
        assert "networks" in data
        assert "args" in data
        assert isinstance(data["args"], list)
        assert data["args"][0]["name"] == "SLICE_NAME"

    def test_saved_template_appears_in_list(self, client, storage_dir):
        # Create template directory manually with weave.json marker
        tmpl_dir = storage_dir / "my_artifacts" / "Test_Tmpl"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "slice.json").write_text(json.dumps({
            "format": "fabric-slice-v1",
            "name": "Test Tmpl",
            "nodes": [],
            "networks": [],
        }))
        (tmpl_dir / "weave.json").write_text(json.dumps({
            "run_script": "weave.sh",
            "log_file": "weave.log",
            "name": "Test Tmpl",
            "description": "",
            "category": "weave",
        }))

        resp = client.get("/api/templates")
        names = [t["name"] for t in resp.json()]
        assert "Test Tmpl" in names


class TestRunTemplate:
    def test_start_run_injects_policy_env_without_clamping_requested_lease(
        self,
        client,
        storage_dir,
        caplog,
    ):
        tmpl_dir = storage_dir / "my_artifacts" / "Env_Weave"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "weave.json").write_text(json.dumps({
            "name": "Env Weave",
            "run_script": "weave.sh",
            "log_file": "weave.log",
        }))
        script = tmpl_dir / "weave.sh"
        script.write_text("#!/usr/bin/env bash\nenv\n")
        os.chmod(script, 0o755)

        captured = {}

        def fake_start_run(**kwargs):
            captured.update(kwargs)
            return "run-env-test"

        caplog.set_level(logging.WARNING, logger="app.routes.templates")
        with patch("app.routes.templates._max_lease_hours_policy", return_value=6), \
             patch("app.run_manager.start_run", side_effect=fake_start_run), \
             patch("app.run_manager.get_run", return_value={
                 "pid": 123,
                 "pgid": 123,
                 "started_at": "2026-07-12T00:00:00Z",
             }):
            resp = client.post("/api/templates/Env_Weave/start-run/auto", json={
                "args": {
                    "SLICE_NAME": "lease-env-test",
                    "FABRIC_LEASE_HOURS": "24",
                    "FABRIC_MAX_LEASE_HOURS": "24",
                },
            })

        assert resp.status_code == 200
        script_args = captured["script_args"]
        assert script_args["FABRIC_MAX_LEASE_HOURS"] == "6"
        assert script_args["FABRIC_LEASE_HOURS"] == "24"
        assert "Ignoring conflicting FABRIC_MAX_LEASE_HOURS" in caplog.text


class TestCleanupScript:
    def test_has_cleanup_script_true(self, client, storage_dir):
        """Cleanup script listed and file exists → has_cleanup_script: true."""
        tmpl_dir = storage_dir / "my_artifacts" / "With_Cleanup"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "slice.json").write_text(json.dumps({
            "name": "With Cleanup", "nodes": [], "networks": [],
        }))
        (tmpl_dir / "weave.json").write_text(json.dumps({
            "name": "With Cleanup",
            "cleanup_script": "weave_cleanup.sh",
        }))
        (tmpl_dir / "weave_cleanup.sh").write_text("#!/bin/bash\necho clean\n")

        # Resync to invalidate template cache after manual dir creation
        client.post("/api/templates/resync")
        resp = client.get("/api/templates")
        tmpl = next(t for t in resp.json() if t["name"] == "With Cleanup")
        assert tmpl["has_cleanup_script"] is True

    def test_has_cleanup_script_false_missing_file(self, client, storage_dir):
        """Cleanup script listed but file missing → has_cleanup_script: false."""
        tmpl_dir = storage_dir / "my_artifacts" / "No_Cleanup_File"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "slice.json").write_text(json.dumps({
            "name": "No Cleanup File", "nodes": [], "networks": [],
        }))
        (tmpl_dir / "weave.json").write_text(json.dumps({
            "name": "No Cleanup File",
            "cleanup_script": "weave_cleanup.sh",
        }))
        # Intentionally NOT creating the weave_cleanup.sh file

        # Resync to invalidate template cache after manual dir creation
        client.post("/api/templates/resync")
        resp = client.get("/api/templates")
        tmpl = next(t for t in resp.json() if t["name"] == "No Cleanup File")
        assert tmpl["has_cleanup_script"] is False


class TestDeleteTemplate:
    def test_delete_custom_template(self, client, storage_dir):
        # Create a template directory with weave.json marker
        tmpl_dir = storage_dir / "my_artifacts" / "deleteme"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "slice.json").write_text(json.dumps({
            "format": "fabric-slice-v1",
            "name": "deleteme",
            "nodes": [],
            "networks": [],
        }))
        (tmpl_dir / "weave.json").write_text(json.dumps({
            "run_script": "weave.sh",
            "log_file": "weave.log",
            "name": "deleteme",
            "category": "weave",
        }))

        resp = client.delete("/api/templates/deleteme")
        assert resp.status_code == 200
        assert not tmpl_dir.exists()
