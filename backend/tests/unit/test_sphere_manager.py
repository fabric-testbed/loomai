"""Unit tests for SPHERE/MergeTB payload parsing.

Exercises the parse helpers against real captured payloads from a live SPHERE
run (project ``fabricsphere``, 2026-06-26), vendored under
``tests/fixtures/sphere/``. These lock the field-name contract the manager and
graph_builder depend on (see docs/SPHERE_INTEGRATION.md).
"""

import json
from pathlib import Path

import app.sphere_manager as sm

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "sphere"


def _realization() -> dict:
    data = json.loads((FIXTURES / "realization.json").read_text())
    return data["results"][0]["realization"]


def _materialization() -> dict:
    return json.loads((FIXTURES / "materialization.json").read_text())


def test_parse_realization_nodes_extracts_names_and_addrs():
    nodes = sm.parse_realization_nodes(_realization())
    by_name = {n["name"]: n for n in nodes}
    assert set(by_name) == {"a", "b"}
    assert by_name["a"]["addrs"] == ["10.0.0.1/24"]
    assert by_name["b"]["addrs"] == ["10.0.0.2/24"]
    assert by_name["a"]["key"] == "moddeter/a"
    assert all(n["provider"] == "sphere" for n in nodes)


def test_parse_realization_links_extracts_endpoints():
    links = sm.parse_realization_links(_realization())
    dataplane = next(l for l in links if l["key"] == "a.0~b.0")
    assert dataplane["endpoints"] == ["a", "b"]
    assert dataplane["provider"] == "sphere"


def test_materialization_ready_true_on_success():
    m = _materialization()
    assert sm.materialization_ready(m) is True
    summary = sm.materialization_summary(m)
    assert summary["rid"] == "world"
    assert summary["eid"] == "hello"
    assert summary["pid"] == "fabricsphere"
    assert summary["numVirtual"] == 2
    assert summary["numLinks"] == 2


def test_materialization_ready_false_when_not_success():
    assert sm.materialization_ready({"taskSummary": {"HighestStatus": "Executing"}}) is False
    assert sm.materialization_ready({}) is False


def test_is_configured_false_without_settings(monkeypatch):
    monkeypatch.setattr(sm, "_sphere_settings", lambda: {})
    assert sm.is_configured() is False


def test_is_configured_requires_enabled_and_credentials(monkeypatch):
    monkeypatch.setattr(sm, "_sphere_settings", lambda: {"token": "t"})  # not enabled
    assert sm.is_configured() is False
    monkeypatch.setattr(sm, "_sphere_settings", lambda: {"enabled": True})  # no creds
    assert sm.is_configured() is False
    monkeypatch.setattr(sm, "_sphere_settings", lambda: {"enabled": True, "token": "t"})
    assert sm.is_configured() is True
    monkeypatch.setattr(
        sm, "_sphere_settings",
        lambda: {"enabled": True, "username": "u", "password": "p"})
    assert sm.is_configured() is True


# --- Session-level contract via the deterministic contract session ---------- #
# These exercise the same code path the gRPC session feeds the helpers (the
# fixtures share the live proto->dict json_name casing), so a regression in the
# MessageToDict casing or the session glue is caught offline.

def test_contract_session_realizations_feed_parse_helpers(monkeypatch):
    monkeypatch.setenv("LOOMAI_CONTRACT_MODE", "1")
    s = sm.get_session("fabricsphere")
    assert type(s).__name__ == "_ContractSphereSession"
    rs = s.list_realizations()
    assert len(rs) == 1
    nodes = {n["name"] for n in sm.parse_realization_nodes(rs[0])}
    assert nodes == {"a", "b"}
    assert s.list_projects() == ["fabricsphere"]


def test_contract_session_materialization_ready(monkeypatch):
    monkeypatch.setenv("LOOMAI_CONTRACT_MODE", "1")
    s = sm.get_session("fabricsphere")
    m = s.get_materialization("hello", "world")
    assert sm.materialization_ready(m) is True
    assert sm.materialization_summary(m)["numVirtual"] == 2
