"""Unit tests for slice network placement validation helpers."""

from __future__ import annotations

from app.slice_validation import append_network_placement_issues


def _nodes(*pairs: tuple[str, str]) -> list[dict]:
    return [{"name": name, "site": site} for name, site in pairs]


def _iface(node: str, suffix: str = "nic1-p1") -> dict:
    return {"name": f"{node}-{suffix}", "node_name": node}


def _issues_for(nodes: list[dict], network: dict) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    append_network_placement_issues(issues, nodes, [network])
    return issues


def test_fabnet_cross_site_network_reports_sites_and_remedy() -> None:
    issues = _issues_for(
        _nodes(("vm1", "DALL"), ("vm2", "WASH")),
        {"name": "fabnet", "type": "FABNetv4", "interfaces": [_iface("vm1"), _iface("vm2")]},
    )

    assert len(issues) == 1
    assert issues[0]["severity"] == "error"
    assert "fabnet" in issues[0]["message"]
    assert "DALL" in issues[0]["message"]
    assert "WASH" in issues[0]["message"]
    assert "one-site only" in issues[0]["message"]
    assert "one FABNet service per site" in issues[0]["remedy"]
    assert "add_fabnet" in issues[0]["remedy"]


def test_fabnet_more_than_255_vms_reports_capacity_error() -> None:
    nodes = _nodes(*[(f"vm{i}", "DALL") for i in range(256)])
    issues = _issues_for(
        nodes,
        {
            "name": "fabnet-big",
            "type": "FABNetv4",
            "interfaces": [_iface(f"vm{i}") for i in range(256)],
        },
    )

    assert len(issues) == 1
    assert "256 VM" in issues[0]["message"]
    assert "at most 255 VMs" in issues[0]["message"]


def test_l2bridge_cross_site_reports_error() -> None:
    issues = _issues_for(
        _nodes(("vm1", "DALL"), ("vm2", "WASH")),
        {"name": "lan", "type": "L2Bridge", "interfaces": [_iface("vm1"), _iface("vm2")]},
    )

    assert len(issues) == 1
    assert "L2Bridge" in issues[0]["message"]
    assert "DALL" in issues[0]["message"]
    assert "WASH" in issues[0]["message"]
    assert "to one site" in issues[0]["remedy"]


def test_l2sts_requires_exactly_two_sites() -> None:
    one_site = _issues_for(
        _nodes(("vm1", "DALL"), ("vm2", "DALL")),
        {"name": "wan", "type": "L2STS", "interfaces": [_iface("vm1"), _iface("vm2")]},
    )
    three_sites = _issues_for(
        _nodes(("vm1", "DALL"), ("vm2", "WASH"), ("vm3", "STAR")),
        {"name": "wan", "type": "L2STS", "interfaces": [_iface("vm1"), _iface("vm2"), _iface("vm3")]},
    )

    assert "exactly 2 sites" in one_site[0]["message"]
    assert "exactly 2 sites" in three_sites[0]["message"]


def test_valid_per_site_fabnet_and_two_site_l2sts_are_clean() -> None:
    issues: list[dict[str, str]] = []
    append_network_placement_issues(
        issues,
        _nodes(("vm1", "DALL"), ("vm2", "WASH")),
        [
            {"name": "fabnet-dall", "type": "FABNetv4", "interfaces": [_iface("vm1")]},
            {"name": "fabnet-wash", "type": "FABNetv4", "interfaces": [_iface("vm2")]},
            {"name": "wan", "type": "L2STS", "interfaces": [_iface("vm1"), _iface("vm2")]},
        ],
    )

    assert issues == []
