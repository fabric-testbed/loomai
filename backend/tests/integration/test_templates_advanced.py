"""Advanced tests for template and weave management routes.

Covers: tool files CRUD, template detail/update, create-blank, resync,
background run endpoints, weave log, weave config reading.
"""

import json
import os
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers — create a template directory on disk
# ---------------------------------------------------------------------------

def _make_template(storage_dir, name, *, weave_json=None, slice_json=None,
                   tools=None, weave_sh=False, log_content=None):
    """Create a template directory with configurable contents."""
    tmpl_dir = storage_dir / "my_artifacts" / name
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    if slice_json is None:
        slice_json = {"name": name, "nodes": [], "networks": []}
    (tmpl_dir / "slice.json").write_text(json.dumps(slice_json))
    if weave_json is None:
        weave_json = {"name": name, "run_script": "weave.sh", "log_file": "weave.log"}
    (tmpl_dir / "weave.json").write_text(json.dumps(weave_json))
    if weave_sh:
        sh = tmpl_dir / "weave.sh"
        sh.write_text("#!/bin/bash\necho running\n")
        os.chmod(str(sh), 0o755)
    if tools:
        td = tmpl_dir / "tools"
        td.mkdir(exist_ok=True)
        for fname, content in tools.items():
            (td / fname).write_text(content)
    if log_content is not None:
        (tmpl_dir / "weave.log").write_text(log_content)
    return tmpl_dir


# ---------------------------------------------------------------------------
# Get template detail
# ---------------------------------------------------------------------------

class TestGetTemplate:
    def test_get_template_returns_detail(self, client, storage_dir):
        _make_template(storage_dir, "detail_test",
                       tools={"setup.sh": "#!/bin/bash\necho hi"})
        resp = client.get("/api/templates/detail_test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["dir_name"] == "detail_test"
        assert "model" in data
        assert isinstance(data["tools"], list)
        assert any(t["filename"] == "setup.sh" for t in data["tools"])

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/api/templates/no_such_tmpl")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Update template description
# ---------------------------------------------------------------------------

class TestUpdateTemplate:
    def test_update_description(self, client, storage_dir):
        _make_template(storage_dir, "update_me")
        resp = client.put("/api/templates/update_me",
                          json={"description": "New description"})
        assert resp.status_code == 200
        assert resp.json()["description"] == "New description"

    def test_update_nonexistent_returns_404(self, client):
        resp = client.put("/api/templates/nope",
                          json={"description": "test"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Create blank artifact
# ---------------------------------------------------------------------------

class TestCreateBlank:
    def test_create_blank_weave(self, client, storage_dir):
        resp = client.post("/api/templates/create-blank",
                           json={"name": "blank_weave", "category": "weave"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["dir_name"] == "blank_weave"
        assert data["category"] == "weave"
        # Should create slice.json for weaves
        assert (storage_dir / "my_artifacts" / "blank_weave" / "slice.json").exists()
        assert (storage_dir / "my_artifacts" / "blank_weave" / "weave.json").exists()
        assert (storage_dir / "my_artifacts" / "blank_weave" / ".weaveignore").exists()

    def test_create_blank_notebook(self, client, storage_dir):
        resp = client.post("/api/templates/create-blank",
                           json={"name": "blank_nb", "category": "notebook"})
        assert resp.status_code == 200
        # Notebooks should NOT have slice.json
        assert not (storage_dir / "my_artifacts" / "blank_nb" / "slice.json").exists()

    def test_create_duplicate_returns_409(self, client, storage_dir):
        _make_template(storage_dir, "dup_test")
        resp = client.post("/api/templates/create-blank",
                           json={"name": "dup_test"})
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Resync
# ---------------------------------------------------------------------------

class TestResync:
    def test_resync_removes_corrupted(self, client, storage_dir):
        """Dirs without weave.json AND slice.json should be removed."""
        bad_dir = storage_dir / "my_artifacts" / "corrupted"
        bad_dir.mkdir(parents=True, exist_ok=True)
        (bad_dir / "random.txt").write_text("junk")

        resp = client.post("/api/templates/resync")
        assert resp.status_code == 200
        assert not bad_dir.exists()

    def test_resync_keeps_valid(self, client, storage_dir):
        _make_template(storage_dir, "valid_tmpl")
        resp = client.post("/api/templates/resync")
        assert resp.status_code == 200
        names = [t["name"] for t in resp.json()]
        assert "valid_tmpl" in names


# ---------------------------------------------------------------------------
# Tool file CRUD
# ---------------------------------------------------------------------------

class TestToolFiles:
    def test_read_tool_file(self, client, storage_dir):
        _make_template(storage_dir, "tool_tmpl",
                       tools={"setup.sh": "#!/bin/bash\necho setup"})
        resp = client.get("/api/templates/tool_tmpl/tools/setup.sh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "setup.sh"
        assert "echo setup" in data["content"]

    def test_read_nonexistent_tool_returns_404(self, client, storage_dir):
        _make_template(storage_dir, "tool_tmpl2")
        resp = client.get("/api/templates/tool_tmpl2/tools/nope.sh")
        assert resp.status_code == 404

    def test_write_tool_file(self, client, storage_dir):
        _make_template(storage_dir, "tool_write")
        resp = client.put("/api/templates/tool_write/tools/new_script.sh",
                          json={"content": "#!/bin/bash\necho new"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "saved"
        assert (storage_dir / "my_artifacts" / "tool_write" / "tools" / "new_script.sh").exists()

    def test_write_tool_to_nonexistent_template_returns_404(self, client):
        resp = client.put("/api/templates/nosuch/tools/x.sh",
                          json={"content": "test"})
        assert resp.status_code == 404

    def test_delete_tool_file(self, client, storage_dir):
        _make_template(storage_dir, "tool_del",
                       tools={"remove_me.sh": "echo bye"})
        resp = client.delete("/api/templates/tool_del/tools/remove_me.sh")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        assert not (storage_dir / "my_artifacts" / "tool_del" / "tools" / "remove_me.sh").exists()

    def test_delete_nonexistent_tool_returns_404(self, client, storage_dir):
        _make_template(storage_dir, "tool_del2")
        resp = client.delete("/api/templates/tool_del2/tools/nope.sh")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Weave log
# ---------------------------------------------------------------------------

class TestWeaveLog:
    def test_read_weave_log(self, client, storage_dir):
        _make_template(storage_dir, "log_test", log_content="line 1\nline 2\n")
        resp = client.get("/api/templates/log_test/weave-log")
        assert resp.status_code == 200
        data = resp.json()
        assert "line 1" in data["output"]
        assert data["offset"] > 0

    def test_read_weave_log_with_offset(self, client, storage_dir):
        content = "aaa\nbbb\nccc\n"
        _make_template(storage_dir, "log_off", log_content=content)
        # First read
        resp1 = client.get("/api/templates/log_off/weave-log?offset=0")
        offset = resp1.json()["offset"]
        # Second read at offset — nothing new
        resp2 = client.get(f"/api/templates/log_off/weave-log?offset={offset}")
        assert resp2.json()["output"] == ""

    def test_read_weave_log_missing_file(self, client, storage_dir):
        _make_template(storage_dir, "log_miss")
        resp = client.get("/api/templates/log_miss/weave-log")
        assert resp.status_code == 200
        assert resp.json()["output"] == ""
        assert resp.json()["offset"] == 0


# ---------------------------------------------------------------------------
# Background run endpoints
# ---------------------------------------------------------------------------

class TestBackgroundRuns:
    def test_list_runs_empty(self, client):
        resp = client.get("/api/templates/runs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_nonexistent_run_returns_404(self, client):
        resp = client.get("/api/templates/runs/nonexistent-id")
        assert resp.status_code == 404

    def test_get_run_output_nonexistent_returns_404(self, client):
        resp = client.get("/api/templates/runs/nonexistent-id/output")
        assert resp.status_code == 404

    def test_stop_nonexistent_run_returns_404(self, client):
        resp = client.post("/api/templates/runs/nonexistent-id/stop")
        assert resp.status_code == 404

    def test_delete_nonexistent_run_returns_404(self, client):
        resp = client.delete("/api/templates/runs/nonexistent-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Weave config reading (unit-level via import)
# ---------------------------------------------------------------------------

class TestWeaveConfig:
    def test_read_weave_config_with_json(self, storage_dir):
        tmpl_dir = _make_template(storage_dir, "cfg_test",
                                  weave_json={"run_script": "custom.sh",
                                              "log_file": "custom.log"})
        from app.routes.templates import _read_weave_config
        cfg = _read_weave_config(str(tmpl_dir))
        assert cfg is not None
        assert cfg["run_script"] == "custom.sh"
        assert cfg["log_file"] == "custom.log"

    def test_read_weave_config_auto_detect_sh(self, storage_dir):
        """If only weave.sh exists (no weave.json), auto-detect."""
        tmpl_dir = storage_dir / "my_artifacts" / "auto_detect"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "weave.sh").write_text("#!/bin/bash\necho hi")
        # Remove weave.json if exists
        wj = tmpl_dir / "weave.json"
        if wj.exists():
            wj.unlink()

        from app.routes.templates import _read_weave_config
        cfg = _read_weave_config(str(tmpl_dir))
        assert cfg is not None
        assert cfg["run_script"] == "weave.sh"

    def test_read_weave_config_none_when_no_indicator(self, storage_dir):
        empty_dir = storage_dir / "my_artifacts" / "empty_dir"
        empty_dir.mkdir(parents=True, exist_ok=True)
        from app.routes.templates import _read_weave_config
        assert _read_weave_config(str(empty_dir)) is None


# ---------------------------------------------------------------------------
# List tools helper
# ---------------------------------------------------------------------------

class TestListTools:
    def test_list_tools_returns_files(self, storage_dir):
        tmpl_dir = _make_template(storage_dir, "tools_list",
                                  tools={"a.sh": "echo a", "b.py": "print('b')"})
        from app.routes.templates import _list_tools
        tools = _list_tools(str(tmpl_dir))
        filenames = [t["filename"] for t in tools]
        assert "a.sh" in filenames
        assert "b.py" in filenames

    def test_list_tools_empty(self, storage_dir):
        tmpl_dir = _make_template(storage_dir, "tools_empty")
        from app.routes.templates import _list_tools
        assert _list_tools(str(tmpl_dir)) == []
