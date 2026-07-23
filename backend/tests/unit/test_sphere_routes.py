"""Offline tests for the SPHERE routes + graph serializer (contract mode).

Uses the deterministic contract session (fixtures) so no live portal is needed.
Covers the disabled->404 gate, status, projects, realizations, the Cytoscape
graph endpoint, and materialization status.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("grpc")

from app import settings_manager as sm  # noqa: E402
from app.graph_builder import build_sphere_realization_graph  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "sphere"


def _realization() -> dict:
    return json.loads((FIXTURES / "realization.json").read_text())["results"][0]["realization"]


# --- graph serializer ------------------------------------------------------- #
def test_build_sphere_graph_shape():
    g = build_sphere_realization_graph(_realization())
    assert set(g) == {"nodes", "edges"}
    names = {n["data"].get("name") for n in g["nodes"]}
    assert {"a", "b"} <= names
    # two instance nodes + two network nodes (dataplane + mgmt) + 1 slice box
    types = [n["data"]["element_type"] for n in g["nodes"]]
    assert types.count("node") == 2
    assert types.count("network") == 2
    assert types.count("slice") == 1
    # instance nodes carry the dedicated SPHERE class (brand colours + readable
    # label), not the FABRIC ".vm" class.
    inst_classes = {n["classes"] for n in g["nodes"] if n["data"]["element_type"] == "node"}
    assert inst_classes == {"sphere-instance"}
    # all resources are enclosed in the slice container (FABRIC-style box).
    slice_id = next(n["data"]["id"] for n in g["nodes"] if n["data"]["element_type"] == "slice")
    assert all(n["data"].get("parent") == slice_id
               for n in g["nodes"] if n["data"]["element_type"] in ("node", "network"))
    # dataplane link a.0~b.0 wires both endpoints
    assert len(g["edges"]) == 2
    assert all(e["data"]["element_type"] == "interface" for e in g["edges"])


# --- routes (contract mode) ------------------------------------------------- #
@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("LOOMAI_CONTRACT_MODE", "1")
    monkeypatch.setattr(sm, "is_sphere_enabled", lambda: True)
    monkeypatch.setattr(sm, "is_sphere_configured", lambda: True)
    monkeypatch.setattr(sm, "get_sphere_default_project", lambda: "fabricsphere")
    monkeypatch.setattr(sm, "get_sphere_settings",
                        lambda: {"enabled": True, "grpc_endpoint": "grpc.sphere-testbed.net",
                                 "default_project": "fabricsphere"})
    from fastapi.testclient import TestClient
    import app.main as m
    return TestClient(m.app)


def test_status_and_projects(client):
    s = client.get("/api/sphere/status").json()
    assert s["enabled"] is True and s["default_project"] == "fabricsphere"
    assert client.get("/api/sphere/projects").json() == ["fabricsphere"]


def test_realizations_and_graph(client):
    rs = client.get("/api/sphere/realizations").json()
    assert isinstance(rs, list) and rs[0]["id"] == "world"
    g = client.get("/api/sphere/realizations/hello/world/graph").json()
    # flat topology: 2 instance nodes + 2 network nodes, 2 edges
    # 2 instance + 2 network + 1 slice container
    assert len(g["nodes"]) == 5 and len(g["edges"]) == 2


def test_materialization_status(client):
    m = client.get("/api/sphere/materializations/hello/world").json()
    assert m["taskSummary"]["HighestStatus"] == "Success"


def test_xdc_lifecycle_and_jump_hosts(client):
    # list
    xdcs = client.get("/api/sphere/xdcs").json()
    assert isinstance(xdcs, list) and xdcs[0]["name"] == "x0"
    # create / attach / detach / delete all succeed (contract no-ops -> 200)
    assert client.post("/api/sphere/xdcs", json={"xdc": "x1", "type": "shared"}).status_code == 200
    assert client.post("/api/sphere/xdcs/x1/attach",
                       json={"experiment": "hello", "realization": "world"}).status_code == 200
    assert client.post("/api/sphere/xdcs/x1/detach",
                       json={"experiment": "hello", "realization": "world"}).status_code == 200
    assert client.delete("/api/sphere/xdcs/x1").status_code == 200
    # jump hosts
    jh = client.get("/api/sphere/jump-hosts").json()
    assert isinstance(jh, list) and jh[0]["fqdn"]


def test_xdc_routes_gated_when_disabled(storage_dir):
    from fastapi.testclient import TestClient
    import app.main as m
    c = TestClient(m.app)
    assert c.get("/api/sphere/xdcs").status_code == 404
    assert c.get("/api/sphere/jump-hosts").status_code == 404


def test_experiments_list_and_create_validation(client):
    exps = client.get("/api/sphere/experiments").json()
    assert isinstance(exps, list) and exps[0]["name"] == "hello"
    # valid name -> 200
    assert client.post("/api/sphere/experiments", json={"experiment": "myexp"}).status_code == 200
    # invalid names (hyphen / uppercase / leading digit) -> 400 with guidance
    for bad in ("test-experiment", "Komal", "2exp", "has space"):
        r = client.post("/api/sphere/experiments", json={"experiment": bad})
        assert r.status_code == 400, bad
    assert client.delete("/api/sphere/experiments/myexp").status_code == 200


def test_sphere_ssh_argv_config(monkeypatch):
    # The ssh config must relax host-key checking for EVERY hop (a `Host *`
    # block) and chain jump -> xdc -> node, else jump hops fail with
    # "Host key verification failed".
    from app.routes.terminal import _build_sphere_ssh_argv
    argv = _build_sphere_ssh_argv({
        "username": "u", "private_key": "KEY", "cert": "CERT",
        "jump_hosts": [{"name": "j", "port": 2202, "fqdn": "jump.example.net"}],
        "xdc_fqdn": "x0.proj", "node_dns": "b.infra.world.hello.proj",
    })
    # Wrapped in bash so the resolved plan prints before exec'ing ssh.
    assert argv[0] == "/bin/bash" and argv[1] == "-lc"
    cmd = argv[2]
    assert "exec ssh -F" in cmd and "sphere-node" in cmd
    import re as _re
    m = _re.search(r"-F '([^']+)'|-F (\S+)", cmd)
    assert m, cmd
    cfg = open(m.group(1) or m.group(2)).read()
    assert "Host *" in cfg
    assert "StrictHostKeyChecking no" in cfg and "UserKnownHostsFile /dev/null" in cfg
    assert "CertificateFile" in cfg
    assert "ControlMaster auto" in cfg  # connection multiplexing (perf)
    # chain: node -> xdc -> jump
    assert "Host sphere-node" in cfg and "ProxyJump sphere-xdc" in cfg


def test_sphere_ssh_config_rejects_injection():
    # A newline (or shell/config metachar) in a value that lands in the ssh
    # config must be rejected, not written — else it injects ssh directives
    # (e.g. a local ProxyCommand). write_sphere_ssh_config returns (None, msg).
    from app.routes.terminal import write_sphere_ssh_config
    base = {"username": "u", "private_key": "KEY", "cert": "CERT", "jump_hosts": [],
            "xdc_fqdn": "x0.proj"}
    bad_node = {**base, "node_dns": "b.infra\n  ProxyCommand touch /tmp/pwned"}
    cfg, err = write_sphere_ssh_config(bad_node)
    assert cfg is None and err
    bad_user = {**base, "node_dns": "b.infra.world.hello.proj", "username": "u\n  ProxyCommand x"}
    cfg2, err2 = write_sphere_ssh_config(bad_user)
    assert cfg2 is None and err2


def test_sphere_ssh_argv_missing_user():
    from app.routes.terminal import _build_sphere_ssh_argv
    argv = _build_sphere_ssh_argv({"username": "", "private_key": "K", "node_dns": "n"})
    assert argv[0] == "/bin/bash"  # informative error shell, not a broken ssh


def test_realization_state_helper():
    from app.sphere_manager import _realization_state
    failed = {"diagnostics": {"value": [{"level": "Error", "message": "no suitable resource found"}]}}
    assert _realization_state(failed, False) == ("failed", "no suitable resource found")
    assert _realization_state({"diagnostics": {"value": []}}, True) == ("complete", "")
    assert _realization_state({}, False) == ("pending", "")


def test_realizations_state_param(client):
    rs = client.get("/api/sphere/realizations?state=true").json()
    assert rs and all("state" in r for r in rs)


def test_experiment_model(client):
    m = client.get("/api/sphere/experiments/hello/model").json()
    assert m["found"] is True
    assert {n["name"] for n in m["nodes"]} == {"a", "b"}
    assert m["links"] and set(m["links"][0]["members"]) == {"a", "b"}


def test_inventory(client):
    inv = client.get("/api/sphere/inventory").json()
    assert set(inv) >= {"facilities", "resources", "pools"}
    assert isinstance(inv["facilities"], list) and isinstance(inv["resources"], list)


def test_seed_sphere_from_env(monkeypatch):
    from app import settings_manager as sm
    monkeypatch.setenv("SPHERE_ENABLED", "true")
    monkeypatch.setenv("SPHERE_USERNAME", "euser")
    monkeypatch.setenv("SPHERE_PASSWORD", "epass")
    monkeypatch.setenv("SPHERE_DEFAULT_PROJECT", "eproj")
    s = {"sphere": {"enabled": False, "username": "old", "password": ""}}
    sm._seed_sphere_from_env(s)
    assert s["sphere"]["enabled"] is True
    assert s["sphere"]["username"] == "euser" and s["sphere"]["password"] == "epass"
    assert s["sphere"]["default_project"] == "eproj"


def test_sphere_secret_mask_and_restore():
    from app.routes.config import _mask_secrets, _restore_masked_secrets, _SECRET_MASK
    stored = {"sphere": {"password": "pw", "token": "tk", "username": "u"}}
    masked = _mask_secrets(stored)
    assert masked["sphere"]["password"] == _SECRET_MASK
    assert masked["sphere"]["token"] == _SECRET_MASK
    assert masked["sphere"]["username"] == "u"  # non-secret untouched
    # Client sends the mask back unchanged -> stored secrets are preserved.
    restored = _restore_masked_secrets(
        {"sphere": {"password": _SECRET_MASK, "token": _SECRET_MASK, "username": "u"}}, stored)
    assert restored["sphere"]["password"] == "pw" and restored["sphere"]["token"] == "tk"


def test_model_compile_and_push(client):
    src = "from mergexp import *\nnet = Network('hello')\nexperiment(net)\n"
    c = client.post("/api/sphere/models/compile", json={"model": src}).json()
    assert c["success"] is True
    r = client.post("/api/sphere/models", json={"model": src, "experiment": "hello", "tag": "v1"}).json()
    assert r["revision"] and r["experiment"] == "hello"


def test_gen_mergexp_roundtrip():
    from app.sphere_weave import gen_mergexp
    src = gen_mergexp("edgeids",
                      [{"name": "edge", "facility": "moddeter"}, {"name": "gw"}],
                      [{"members": ["edge", "gw"],
                        "addrs": {"edge": "10.0.1.10/24", "gw": "10.0.1.1/24"}}])
    assert "from mergexp import *" in src
    assert "net = Network('edgeids')" in src
    assert "edge = net.node('edge', facility == 'moddeter')" in src
    assert "gw = net.node('gw')" in src  # no facility -> unconstrained
    assert "link0 = net.connect([edge, gw])" in src
    assert "link0[edge].socket.addrs = ip4('10.0.1.10/24')" in src
    assert src.rstrip().endswith("experiment(net)")


def test_gen_mergexp_rejects_bad_identifier():
    from app.sphere_weave import gen_mergexp
    import pytest as _pytest
    with _pytest.raises(ValueError):
        gen_mergexp("x", [{"name": "bad name"}], [])


def test_package_experiment_route(client, storage_dir):
    from app.user_context import get_artifacts_dir
    r = client.post("/api/sphere/experiments/hello/package", json={
        "name": "hello-weave",
        "description": "demo",
        "realization": "world",
        "scripts": [{"name": "setup.sh", "content": "#!/bin/bash\necho hi\n", "target": "a"}],
        "include_notebook": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "sphere-experiment-v1"
    assert body["dir_name"] == "hello-weave"
    d = Path(get_artifacts_dir()) / "hello-weave"
    assert (d / "model.py").exists()
    assert (d / "experiment.py").exists()
    assert (d / "weave.sh").exists()
    assert (d / "scripts" / "setup.sh").exists()
    assert (d / "analysis.ipynb").exists()
    wj = json.loads((d / "weave.json").read_text())
    assert wj["format"] == "sphere-experiment-v1"
    assert wj["sphere"]["experiment"] == "hello"
    assert wj["sphere"]["realization"] == "world"
    assert wj["sphere"]["scripts"][0]["name"] == "setup.sh"
    model = (d / "model.py").read_text()
    assert "net.node('a'" in model and "net.node('b'" in model
    # bundled notebook is valid JSON with nbformat
    nb = json.loads((d / "analysis.ipynb").read_text())
    assert nb["nbformat"] == 4 and nb["cells"]


def test_package_experiment_custom_notebook(client, storage_dir):
    """A caller-supplied notebook (list of cells) overrides the auto-generated one."""
    from app.user_context import get_artifacts_dir
    r = client.post("/api/sphere/experiments/hello/package", json={
        "name": "hello-nb",
        "realization": "world",
        "notebook": [
            {"cell_type": "markdown", "source": "# My custom analysis"},
            {"cell_type": "code", "source": "import json  # load alerts.jsonl"},
        ],
    })
    assert r.status_code == 200, r.text
    d = Path(get_artifacts_dir()) / "hello-nb"
    nb = json.loads((d / "analysis.ipynb").read_text())
    assert nb["nbformat"] == 4
    assert nb["cells"][0]["cell_type"] == "markdown"
    assert nb["cells"][0]["source"] == "# My custom analysis"
    assert nb["cells"][1]["cell_type"] == "code"
    assert nb["cells"][1]["outputs"] == []  # code cells get the nbformat scaffold


def test_package_rejects_bad_script_name(client, storage_dir):
    r = client.post("/api/sphere/experiments/hello/package", json={
        "name": "x", "realization": "world",
        "scripts": [{"name": "../evil.sh", "content": "x"}],
    })
    assert r.status_code == 400


def test_resolve_xdc_ssh_contract():
    from app.sphere_manager import _ContractSphereSession
    d = _ContractSphereSession().resolve_xdc_ssh("x0")
    assert d["ssh_target"] == "sphere-xdc"
    assert d["node_dns"] == ""  # XDC target needs no node DNS
    assert d["xdc_fqdn"] and d["private_key"]


def test_ssh_config_xdc_only_no_node_block():
    # An XDC target (empty node_dns, present xdc_fqdn) must still produce a valid
    # config: a sphere-xdc Host, but NO sphere-node block.
    from app.routes.terminal import write_sphere_ssh_config
    cfg_path, err = write_sphere_ssh_config({
        "username": "u", "private_key": "KEY", "cert": "CERT",
        "jump_hosts": [{"name": "j", "port": 2202, "fqdn": "jump.example.net"}],
        "xdc_fqdn": "x0.proj", "node_dns": "",
    })
    assert cfg_path, err
    cfg = open(cfg_path).read()
    assert "Host sphere-xdc" in cfg
    assert "Host sphere-node" not in cfg


def test_ssh_config_requires_some_target():
    from app.routes.terminal import write_sphere_ssh_config
    cfg, err = write_sphere_ssh_config({"username": "u", "private_key": "K",
                                        "node_dns": "", "xdc_fqdn": ""})
    assert cfg is None and err


def test_seed_weave_not_found(client, storage_dir):
    r = client.post("/api/sphere/xdcs/x0/seed-weave", json={"weave": "nope"})
    assert r.status_code == 404


def test_seed_weave_rejects_bad_dest(client, storage_dir):
    # Package a weave first so the dir exists, then a traversal dest must 400
    # before any ssh happens.
    assert client.post("/api/sphere/experiments/hello/package",
                       json={"name": "hw", "realization": "world"}).status_code == 200
    r = client.post("/api/sphere/xdcs/x0/seed-weave",
                    json={"weave": "hw", "dest": "../escape"})
    assert r.status_code == 400


def test_disabled_returns_404(storage_dir):
    # storage_dir isolates settings to a tmp dir; default sphere.enabled is False.
    from fastapi.testclient import TestClient
    import app.main as m
    c = TestClient(m.app)
    assert c.get("/api/sphere/projects").status_code == 404
    # status is always reachable so the UI can read the toggle
    assert c.get("/api/sphere/status").status_code == 200
