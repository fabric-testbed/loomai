"""Tests for experiment (runnable weave) management routes.

Covers: list, create, get, update, delete, readme CRUD, script CRUD,
name sanitization, path validation.
"""

import json
import os

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_experiment(storage_dir, dir_name, *, meta=None, readme=None,
                     scripts=None, weave_json=True, weave_sh=True):
    """Create an experiment directory with configurable contents.

    Note: list_experiments reads metadata from weave.json first (if present),
    so the weave.json name determines the display name in listings.
    """
    exp_dir = storage_dir / "my_artifacts" / dir_name
    exp_dir.mkdir(parents=True, exist_ok=True)

    if meta is None:
        meta = {"name": dir_name, "description": "", "author": "", "tags": []}
    (exp_dir / "experiment.json").write_text(json.dumps(meta))

    if weave_json:
        # Use meta name so listing shows the expected name
        wj = {"name": meta.get("name", dir_name),
              "run_script": "weave.sh", "log_file": "weave.log"}
        (exp_dir / "weave.json").write_text(json.dumps(wj))

    if weave_sh:
        sh = exp_dir / "weave.sh"
        sh.write_text("#!/bin/bash\necho running\n")
        os.chmod(str(sh), 0o755)

    if readme:
        (exp_dir / "README.md").write_text(readme)

    if scripts:
        sd = exp_dir / "scripts"
        sd.mkdir(exist_ok=True)
        for fname, content in scripts.items():
            (sd / fname).write_text(content)

    return exp_dir


# ---------------------------------------------------------------------------
# List experiments
# ---------------------------------------------------------------------------

class TestListExperiments:
    def test_list_empty(self, client, storage_dir):
        resp = client.get("/api/experiments")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_finds_runnable_weave(self, client, storage_dir):
        _make_experiment(storage_dir, "exp1",
                         meta={"name": "Experiment One"})
        resp = client.get("/api/experiments")
        assert resp.status_code == 200
        names = [e["name"] for e in resp.json()]
        assert "Experiment One" in names

    def test_list_skips_non_runnable(self, client, storage_dir):
        """Dirs without weave.sh should be skipped."""
        _make_experiment(storage_dir, "no_sh", weave_sh=False)
        resp = client.get("/api/experiments")
        dir_names = [e.get("dir_name") for e in resp.json()]
        assert "no_sh" not in dir_names

    def test_list_includes_metadata(self, client, storage_dir):
        sd = _make_experiment(storage_dir, "meta_exp",
                              meta={"name": "Meta Exp"},
                              scripts={"run.sh": "echo hi"},
                              readme="# Hello")
        resp = client.get("/api/experiments")
        exp = next(e for e in resp.json() if e["dir_name"] == "meta_exp")
        assert exp["has_template"] is True  # experiment.json == template marker
        assert exp["has_readme"] is True
        assert exp["script_count"] == 1


# ---------------------------------------------------------------------------
# Create experiment
# ---------------------------------------------------------------------------

class TestCreateExperiment:
    def test_create_basic(self, client, storage_dir):
        resp = client.post("/api/experiments", json={
            "name": "New Experiment",
            "description": "A test experiment",
            "author": "tester",
            "tags": ["test", "demo"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "New Experiment"
        assert data["description"] == "A test experiment"
        assert data["author"] == "tester"
        assert "test" in data["tags"]

    def test_create_experiment_creates_files(self, client, storage_dir):
        client.post("/api/experiments", json={"name": "File Check"})
        exp_dir = storage_dir / "my_artifacts" / "File_Check"
        assert exp_dir.is_dir()
        assert (exp_dir / "experiment.json").exists()
        assert (exp_dir / "README.md").exists()
        assert (exp_dir / "scripts").is_dir()

    def test_create_duplicate_returns_409(self, client, storage_dir):
        _make_experiment(storage_dir, "dup_exp")
        resp = client.post("/api/experiments", json={"name": "dup_exp"})
        assert resp.status_code == 409

    def test_create_with_invalid_name(self, client):
        resp = client.post("/api/experiments", json={"name": "   "})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Get experiment
# ---------------------------------------------------------------------------

class TestGetExperiment:
    def test_get_returns_full_detail(self, client, storage_dir):
        _make_experiment(storage_dir, "get_exp",
                         meta={"name": "Get Exp", "description": "desc"},
                         readme="# Get Me",
                         scripts={"a.sh": "echo a", "b.py": "print('b')"})
        resp = client.get("/api/experiments/get_exp")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Get Exp"
        assert data["dir_name"] == "get_exp"
        assert "# Get Me" in data["readme"]
        assert len(data["scripts"]) == 2
        assert data["has_template"] is False  # no slice.json

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/api/experiments/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Update experiment
# ---------------------------------------------------------------------------

class TestUpdateExperiment:
    def test_update_metadata(self, client, storage_dir):
        _make_experiment(storage_dir, "upd_exp",
                         meta={"name": "Update Me", "description": "old"})
        resp = client.put("/api/experiments/upd_exp", json={
            "description": "new description",
            "author": "new author",
            "tags": ["updated"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "new description"
        assert data["author"] == "new author"
        assert "updated" in data["tags"]

    def test_update_nonexistent_returns_404(self, client):
        resp = client.put("/api/experiments/nope", json={"description": "x"})
        assert resp.status_code == 404

    def test_partial_update(self, client, storage_dir):
        _make_experiment(storage_dir, "partial_upd",
                         meta={"name": "Partial", "description": "original",
                               "author": "me"})
        # Only update description, author should remain
        resp = client.put("/api/experiments/partial_upd", json={
            "description": "updated",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "updated"


# ---------------------------------------------------------------------------
# Delete experiment
# ---------------------------------------------------------------------------

class TestDeleteExperiment:
    def test_delete_removes_directory(self, client, storage_dir):
        exp_dir = _make_experiment(storage_dir, "del_exp")
        assert exp_dir.exists()
        resp = client.delete("/api/experiments/del_exp")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        assert not exp_dir.exists()

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/experiments/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# README CRUD
# ---------------------------------------------------------------------------

class TestReadme:
    def test_get_readme(self, client, storage_dir):
        _make_experiment(storage_dir, "readme_exp", readme="# My Readme")
        resp = client.get("/api/experiments/readme_exp/readme")
        assert resp.status_code == 200
        assert resp.json()["content"] == "# My Readme"

    def test_get_readme_missing_returns_empty(self, client, storage_dir):
        _make_experiment(storage_dir, "no_readme")
        # Remove README.md if it exists
        rm = storage_dir / "my_artifacts" / "no_readme" / "README.md"
        if rm.exists():
            rm.unlink()
        resp = client.get("/api/experiments/no_readme/readme")
        assert resp.status_code == 200
        assert resp.json()["content"] == ""

    def test_update_readme(self, client, storage_dir):
        _make_experiment(storage_dir, "upd_readme", readme="old")
        resp = client.put("/api/experiments/upd_readme/readme",
                          json={"content": "# Updated\nNew content"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "saved"
        content = (storage_dir / "my_artifacts" / "upd_readme" / "README.md").read_text()
        assert "# Updated" in content

    def test_update_readme_nonexistent_returns_404(self, client):
        resp = client.put("/api/experiments/nope/readme",
                          json={"content": "test"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Script CRUD
# ---------------------------------------------------------------------------

class TestScripts:
    def test_read_script(self, client, storage_dir):
        _make_experiment(storage_dir, "scr_exp",
                         scripts={"run.sh": "#!/bin/bash\necho run"})
        resp = client.get("/api/experiments/scr_exp/scripts/run.sh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "run.sh"
        assert "echo run" in data["content"]

    def test_read_nonexistent_script_returns_404(self, client, storage_dir):
        _make_experiment(storage_dir, "scr_exp2")
        resp = client.get("/api/experiments/scr_exp2/scripts/nope.sh")
        assert resp.status_code == 404

    def test_write_script(self, client, storage_dir):
        _make_experiment(storage_dir, "scr_write")
        resp = client.put("/api/experiments/scr_write/scripts/new.sh",
                          json={"content": "#!/bin/bash\necho new"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "saved"
        path = storage_dir / "my_artifacts" / "scr_write" / "scripts" / "new.sh"
        assert path.exists()
        assert "echo new" in path.read_text()

    def test_write_script_nonexistent_exp_returns_404(self, client):
        resp = client.put("/api/experiments/nope/scripts/x.sh",
                          json={"content": "test"})
        assert resp.status_code == 404

    def test_delete_script(self, client, storage_dir):
        _make_experiment(storage_dir, "scr_del",
                         scripts={"removable.sh": "echo bye"})
        resp = client.delete("/api/experiments/scr_del/scripts/removable.sh")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        path = storage_dir / "my_artifacts" / "scr_del" / "scripts" / "removable.sh"
        assert not path.exists()

    def test_delete_nonexistent_script_returns_404(self, client, storage_dir):
        _make_experiment(storage_dir, "scr_del2")
        resp = client.delete("/api/experiments/scr_del2/scripts/nope.sh")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Name and filename sanitization
# ---------------------------------------------------------------------------

class TestExperimentSanitization:
    def test_sanitize_name_special_chars(self):
        from app.routes.experiments import _sanitize_name
        assert _sanitize_name("my exp!@#") == "my_exp___"

    def test_sanitize_name_empty_raises(self):
        from app.routes.experiments import _sanitize_name
        with pytest.raises(Exception):
            _sanitize_name("   ")

    def test_validate_script_filename(self):
        from app.routes.experiments import _validate_script_filename
        assert _validate_script_filename("run.sh") == "run.sh"
        assert _validate_script_filename("my script!.py") == "my_script_.py"

    def test_validate_script_filename_dot_start_raises(self):
        from app.routes.experiments import _validate_script_filename
        with pytest.raises(Exception):
            _validate_script_filename(".hidden")


# ---------------------------------------------------------------------------
# Cross-testbed experiment template helpers (unit tests)
# ---------------------------------------------------------------------------

class TestVariableSubstitution:
    def test_substitute_string(self):
        from app.routes.experiments import _substitute_variables
        result = _substitute_variables("hello ${NAME}", {"NAME": "world"})
        assert result == "hello world"

    def test_substitute_nested_dict(self):
        from app.routes.experiments import _substitute_variables
        data = {"site": "${SITE}", "nested": {"name": "${NAME}"}}
        result = _substitute_variables(data, {"SITE": "RENC", "NAME": "node1"})
        assert result == {"site": "RENC", "nested": {"name": "node1"}}

    def test_substitute_list(self):
        from app.routes.experiments import _substitute_variables
        data = ["${A}", {"b": "${B}"}, 42]
        result = _substitute_variables(data, {"A": "x", "B": "y"})
        assert result == ["x", {"b": "y"}, 42]

    def test_substitute_no_match_leaves_intact(self):
        from app.routes.experiments import _substitute_variables
        result = _substitute_variables("${UNKNOWN}", {"NAME": "val"})
        assert result == "${UNKNOWN}"

    def test_substitute_non_string_passthrough(self):
        from app.routes.experiments import _substitute_variables
        assert _substitute_variables(42, {"X": "y"}) == 42
        assert _substitute_variables(True, {"X": "y"}) is True
        assert _substitute_variables(None, {"X": "y"}) is None

    def test_substitute_multiple_in_one_string(self):
        from app.routes.experiments import _substitute_variables
        result = _substitute_variables(
            "${A}-${B}-${A}", {"A": "x", "B": "y"}
        )
        assert result == "x-y-x"


class TestBuildCrossTestbedConnections:
    def test_fabnet_connection(self):
        from app.routes.experiments import _build_cross_testbed_connections
        fab = [{"name": "fab1"}, {"name": "fab2"}]
        chi = [{"name": "chi1", "connection_type": "fabnet_v4"}]
        result = _build_cross_testbed_connections(fab, chi)
        assert len(result) == 1
        assert result[0]["fabric_node"] == "fab1"
        assert result[0]["chameleon_node"] == "chi1"
        assert result[0]["type"] == "fabnet_v4"

    def test_no_connection_for_l2_stitch(self):
        from app.routes.experiments import _build_cross_testbed_connections
        fab = [{"name": "fab1"}]
        chi = [{"name": "chi1", "connection_type": "l2_stitch"}]
        result = _build_cross_testbed_connections(fab, chi)
        assert result == []

    def test_no_fabric_nodes(self):
        from app.routes.experiments import _build_cross_testbed_connections
        chi = [{"name": "chi1", "connection_type": "fabnet_v4"}]
        result = _build_cross_testbed_connections([], chi)
        assert result == []

    def test_no_chameleon_nodes(self):
        from app.routes.experiments import _build_cross_testbed_connections
        fab = [{"name": "fab1"}]
        result = _build_cross_testbed_connections(fab, [])
        assert result == []


# ---------------------------------------------------------------------------
# Cross-testbed experiment template endpoints (integration tests)
# ---------------------------------------------------------------------------

def _make_cross_testbed_experiment(storage_dir, dir_name, *, experiment_data=None):
    """Create a cross-testbed experiment template directory."""
    exp_dir = storage_dir / "my_artifacts" / dir_name
    exp_dir.mkdir(parents=True, exist_ok=True)

    if experiment_data is None:
        experiment_data = {
            "format": "loomai-experiment-v1",
            "name": dir_name,
            "description": "Test cross-testbed experiment",
            "author": "tester",
            "tags": ["cross-testbed"],
            "created": "2026-01-01T00:00:00+00:00",
            "variables": [
                {"name": "SLICE_NAME", "label": "Name", "type": "string",
                 "default": "test-slice", "required": True},
                {"name": "FABRIC_SITE", "label": "FABRIC Site", "type": "site",
                 "default": "RENC", "required": False},
            ],
            "fabric": {
                "nodes": [
                    {"name": "fab-node1", "site": "${FABRIC_SITE}",
                     "cores": 4, "ram": 16, "disk": 50,
                     "image": "default_ubuntu_22", "components": []}
                ],
                "networks": [],
                "facility_ports": [],
                "port_mirrors": [],
            },
            "chameleon": {
                "nodes": [
                    {"name": "chi-node1", "site": "CHI@TACC",
                     "node_type": "compute_skylake",
                     "image": "CC-Ubuntu22.04",
                     "connection_type": "fabnet_v4"}
                ],
                "networks": [],
                "floating_ips": [],
            },
            "cross_testbed": {
                "connections": [
                    {"fabric_node": "fab-node1",
                     "chameleon_node": "chi-node1",
                     "type": "fabnet_v4"}
                ],
            },
        }

    (exp_dir / "experiment.json").write_text(json.dumps(experiment_data))

    # Also create weave.json for backward compat
    wj = {"name": experiment_data.get("name", dir_name),
          "run_script": "weave.sh", "log_file": "weave.log",
          "is_experiment": True}
    (exp_dir / "weave.json").write_text(json.dumps(wj))

    return exp_dir


class TestSaveExperimentTemplate:
    def test_save_without_name_returns_400(self, client, storage_dir):
        resp = client.post("/api/experiments/save", json={
            "name": "",
            "description": "test",
        })
        assert resp.status_code == 400

    def test_save_creates_experiment_files(self, client, storage_dir):
        resp = client.post("/api/experiments/save", json={
            "name": "My Cross Test",
            "description": "A cross-testbed test",
            "slice_name": "",  # no slice to export
            "tags": ["cross-testbed", "test"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "loomai-experiment-v1"
        assert data["name"] == "My Cross Test"
        assert "cross-testbed" in data["tags"]

        # Verify files on disk
        exp_dir = storage_dir / "my_artifacts" / "My_Cross_Test"
        assert exp_dir.is_dir()
        assert (exp_dir / "experiment.json").exists()
        assert (exp_dir / "weave.json").exists()
        assert (exp_dir / "scripts").is_dir()
        assert (exp_dir / ".weaveignore").exists()

    def test_save_duplicate_returns_409(self, client, storage_dir):
        _make_cross_testbed_experiment(storage_dir, "dup_cross")
        resp = client.post("/api/experiments/save", json={
            "name": "dup_cross",
            "description": "dup",
        })
        assert resp.status_code == 409

    def test_save_generates_default_variables(self, client, storage_dir):
        resp = client.post("/api/experiments/save", json={
            "name": "Auto Vars",
            "description": "test",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["variables"]) >= 1
        assert data["variables"][0]["name"] == "SLICE_NAME"

    def test_save_preserves_custom_variables(self, client, storage_dir):
        custom_vars = [
            {"name": "NODE_COUNT", "label": "Count", "type": "number",
             "default": 2, "required": False}
        ]
        resp = client.post("/api/experiments/save", json={
            "name": "Custom Vars",
            "description": "test",
            "variables": custom_vars,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["variables"][0]["name"] == "NODE_COUNT"


class TestGetExperimentTemplate:
    def test_get_existing_template(self, client, storage_dir):
        _make_cross_testbed_experiment(storage_dir, "get_tmpl")
        resp = client.get("/api/experiments/get_tmpl/template")
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "loomai-experiment-v1"
        assert "fabric" in data
        assert "chameleon" in data
        assert "cross_testbed" in data
        assert data["dir_name"] == "get_tmpl"

    def test_get_nonexistent_template_returns_404(self, client):
        resp = client.get("/api/experiments/nonexistent/template")
        assert resp.status_code == 404

    def test_get_template_without_experiment_json(self, client, storage_dir):
        """A dir with only weave.json but no experiment.json returns 404."""
        exp_dir = storage_dir / "my_artifacts" / "no_exp_json"
        exp_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / "weave.json").write_text('{"name": "no_exp_json"}')
        resp = client.get("/api/experiments/no_exp_json/template")
        assert resp.status_code == 404


class TestLoadExperimentTemplate:
    def test_load_creates_chameleon_nodes(self, client, storage_dir):
        """Loading a cross-testbed template should populate Chameleon nodes in memory."""
        _make_cross_testbed_experiment(storage_dir, "load_cross")
        resp = client.post("/api/experiments/load_cross/load-experiment", json={
            "variables": {"SLICE_NAME": "my-loaded-slice"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("experiment_loaded") is True
        assert data.get("experiment_name") == "load_cross"
        chi_nodes = data.get("chameleon_nodes", [])
        assert len(chi_nodes) == 1
        assert chi_nodes[0]["name"] == "chi-node1"

    def test_load_applies_variable_substitution(self, client, storage_dir):
        _make_cross_testbed_experiment(storage_dir, "var_sub")
        resp = client.post("/api/experiments/var_sub/load-experiment", json={
            "variables": {"SLICE_NAME": "custom-name", "FABRIC_SITE": "STAR"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("experiment_loaded") is True

    def test_load_uses_defaults_when_no_vars_provided(self, client, storage_dir):
        _make_cross_testbed_experiment(storage_dir, "defaults_test")
        resp = client.post("/api/experiments/defaults_test/load-experiment", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("experiment_loaded") is True

    def test_load_nonexistent_returns_404(self, client):
        resp = client.post("/api/experiments/nonexistent/load-experiment", json={})
        assert resp.status_code == 404

    def test_load_chameleon_only_experiment(self, client, storage_dir):
        """An experiment with only Chameleon nodes and no FABRIC nodes."""
        exp_data = {
            "format": "loomai-experiment-v1",
            "name": "chi-only",
            "description": "Chameleon-only experiment",
            "author": "",
            "tags": [],
            "created": "2026-01-01T00:00:00+00:00",
            "variables": [],
            "fabric": {"nodes": [], "networks": [],
                       "facility_ports": [], "port_mirrors": []},
            "chameleon": {
                "nodes": [
                    {"name": "chi-1", "site": "CHI@UC",
                     "node_type": "compute_haswell",
                     "image": "CC-Ubuntu22.04",
                     "connection_type": ""}
                ],
                "networks": [],
                "floating_ips": [],
            },
            "cross_testbed": {"connections": []},
        }
        _make_cross_testbed_experiment(storage_dir, "chi_only", experiment_data=exp_data)
        resp = client.post("/api/experiments/chi_only/load-experiment", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("experiment_loaded") is True
        assert len(data.get("chameleon_nodes", [])) == 1

    def test_load_populates_chameleon_in_memory_store(self, client, storage_dir):
        """Verify the Chameleon nodes are stored in the in-memory dict."""
        _make_cross_testbed_experiment(storage_dir, "mem_store")
        resp = client.post("/api/experiments/mem_store/load-experiment", json={
            "variables": {"SLICE_NAME": "mem-test"},
        })
        assert resp.status_code == 200

        # Check the in-memory store via the Chameleon API
        chi_resp = client.get("/api/chameleon/slice-nodes/mem-test")
        assert chi_resp.status_code == 200
        chi_nodes = chi_resp.json()
        assert len(chi_nodes) == 1
        assert chi_nodes[0]["name"] == "chi-node1"


# ---------------------------------------------------------------------------
# Artifact category detection for experiments
# ---------------------------------------------------------------------------

class TestExperimentCategoryDetection:
    def test_detect_experiment_category(self, storage_dir):
        from app.routes.artifacts import _detect_category
        exp_dir = storage_dir / "my_artifacts" / "cat_test"
        exp_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / "experiment.json").write_text(json.dumps({
            "format": "loomai-experiment-v1",
            "name": "cat_test",
        }))
        assert _detect_category(str(exp_dir)) == "experiment"

    def test_detect_weave_when_no_experiment_format(self, storage_dir):
        """experiment.json without the v1 format should fall through to weave."""
        from app.routes.artifacts import _detect_category
        exp_dir = storage_dir / "my_artifacts" / "old_exp"
        exp_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / "experiment.json").write_text(json.dumps({
            "name": "old_exp",
            "description": "plain experiment",
        }))
        (exp_dir / "weave.json").write_text(json.dumps({"name": "old_exp"}))
        assert _detect_category(str(exp_dir)) == "weave"

    def test_experiment_category_tag(self):
        from app.routes.artifacts import _CATEGORY_TAGS
        assert "experiment" in _CATEGORY_TAGS
        assert _CATEGORY_TAGS["experiment"] == "loomai:experiment"

    def test_experiment_category_marker(self):
        from app.routes.artifacts import _CATEGORY_MARKERS
        assert "experiment" in _CATEGORY_MARKERS
