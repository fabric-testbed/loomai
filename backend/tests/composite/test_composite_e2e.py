"""Composite slice real-provisioning end-to-end tests.

These tests create composite slices with real FABRIC and/or Chameleon members,
submit them, and verify they reach Active state.  The cross-testbed ping test
verifies that a FABRIC node on FABNetv4 can ping a Chameleon node on FABNetv4.

Gate: ``@pytest.mark.composite`` — excluded from default runs.
Run::

    pytest tests/composite/test_composite_e2e.py -v -s -m composite --timeout=1200
"""

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.composite

BASE_URL = os.environ.get("LOOMAI_BASE_URL", "http://localhost:8000")
CHI_PREFERRED_SITES = ["CHI@UC", "CHI@TACC", "KVM@TACC"]
FABRIC_PREFERRED_SITES = ["TACC", "STAR", "RENC"]

# Timeouts
COMPOSITE_TIMEOUT = 900     # 15 min for composite (both testbeds)
POLL_INTERVAL = 15           # seconds between polls
FABRIC_TIMEOUT = 600         # 10 min for FABRIC slice
CHI_TIMEOUT = 600            # 10 min for Chameleon slice
PING_TIMEOUT = 120           # 2 min for ping to succeed


@pytest.fixture(scope="session")
def api():
    return httpx.Client(base_url=f"{BASE_URL}/api", timeout=60.0)


@pytest.fixture(scope="session")
def fabric_ok(api):
    try:
        resp = api.get("/config")
        if resp.status_code != 200:
            pytest.skip("Backend not running")
        data = resp.json()
        exp = data.get("token_info", {}).get("exp", 0)
        if exp * 1000 < time.time() * 1000:
            pytest.skip("FABRIC token expired")
        return True
    except Exception:
        pytest.skip("Backend not running")


@pytest.fixture(scope="session")
def chameleon_ok(api):
    try:
        resp = api.get("/chameleon/sites")
        if resp.status_code != 200:
            pytest.skip("Chameleon not configured")
        sites = resp.json()
        if not sites:
            pytest.skip("No Chameleon sites")
        return sites
    except Exception:
        pytest.skip("Chameleon unavailable")


@pytest.fixture(scope="session")
def chi_site(chameleon_ok):
    names = [s.get("name", s) if isinstance(s, dict) else s for s in chameleon_ok]
    for pref in CHI_PREFERRED_SITES:
        if pref in names:
            return pref
    return names[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cleanup_composite(api: httpx.Client, comp_id: str):
    try:
        api.delete(f"/composite/slices/{comp_id}", timeout=30.0)
    except Exception:
        pass


def _cleanup_fabric_slice(api: httpx.Client, name: str):
    try:
        api.delete(f"/slices/{name}", timeout=60.0)
    except Exception:
        pass


def _cleanup_chi_slice(api: httpx.Client, slice_id: str):
    try:
        api.delete(f"/chameleon/slices/{slice_id}", params={"delete_resources": True}, timeout=120.0)
    except Exception:
        pass


def _wait_composite_state(api: httpx.Client, comp_id: str, target: str, timeout: int = COMPOSITE_TIMEOUT) -> dict:
    """Poll composite until it reaches target state. Returns composite data."""
    start = time.time()
    while time.time() - start < timeout:
        resp = api.get(f"/composite/slices/{comp_id}")
        if resp.status_code == 200:
            data = resp.json()
            state = data.get("state", "")
            if state == target:
                return data
            if state == "Degraded":
                pytest.fail(f"Composite entered Degraded state: {data}")
        time.sleep(POLL_INTERVAL)
    pytest.fail(f"Composite did not reach '{target}' within {timeout}s")


def _wait_fabric_slice_ok(api: httpx.Client, name: str, timeout: int = FABRIC_TIMEOUT) -> dict:
    """Poll FABRIC slice until StableOK."""
    start = time.time()
    while time.time() - start < timeout:
        resp = api.get(f"/slices/{name}")
        if resp.status_code == 200:
            data = resp.json()
            state = data.get("state", "")
            if state == "StableOK":
                return data
            if state in ("StableError", "Dead"):
                pytest.fail(f"FABRIC slice entered {state}: {data.get('error_messages', [])}")
        time.sleep(POLL_INTERVAL)
    pytest.fail(f"FABRIC slice '{name}' did not reach StableOK within {timeout}s")


def _wait_chi_instances_active(api: httpx.Client, slice_id: str, timeout: int = CHI_TIMEOUT) -> list:
    """Poll Chameleon slice until all instances ACTIVE."""
    start = time.time()
    while time.time() - start < timeout:
        resp = api.get(f"/chameleon/slices/{slice_id}")
        if resp.status_code == 200:
            resources = resp.json().get("resources", [])
            instances = [r for r in resources if r.get("type") == "instance"]
            if instances and all(i.get("status") == "ACTIVE" for i in instances):
                return instances
            if any(i.get("status") == "ERROR" for i in instances):
                pytest.fail(f"Chameleon instance ERROR: {instances}")
        time.sleep(POLL_INTERVAL)
    pytest.fail(f"Chameleon instances did not reach ACTIVE within {timeout}s")


def _find_chi_node_type(api: httpx.Client, site: str) -> str:
    resp = api.get(f"/chameleon/sites/{site}/node-types")
    if resp.status_code == 200:
        data = resp.json()
        types = data.get("node_types", data) if isinstance(data, dict) else data
        if types:
            return types[0]["name"] if isinstance(types[0], dict) else types[0]
    return "compute_skylake"


def _create_fabric_draft_with_node(api: httpx.Client, name: str, add_nic: bool = False) -> str:
    """Create a FABRIC draft slice with one node. Returns slice name."""
    resp = api.post(f"/slices?name={name}")
    assert resp.status_code == 200, f"Create FABRIC draft failed: {resp.text}"

    # Add a node with a NIC (needed for FABNetv4)
    node_body: dict = {
        "name": "fab-node1",
        "site": "auto",
        "cores": 2,
        "ram": 8,
        "disk": 10,
        "image": "default_ubuntu_22",
    }
    if add_nic:
        node_body["components"] = [{"model": "NIC_Basic", "name": "nic1"}]

    resp = api.post(f"/slices/{name}/nodes", json=node_body)
    assert resp.status_code == 200, f"Add FABRIC node failed: {resp.text}"
    return name


def _create_chi_draft_with_node(api: httpx.Client, name: str, site: str) -> str:
    """Create a Chameleon draft with one node. Returns slice ID."""
    node_type = _find_chi_node_type(api, site)

    resp = api.post("/chameleon/slices", json={"name": name, "site": site})
    assert resp.status_code == 200, f"Create Chameleon slice failed: {resp.text}"
    slice_id = resp.json()["id"]

    resp = api.post(f"/chameleon/drafts/{slice_id}/nodes", json={
        "name": "chi-node1",
        "node_type": node_type,
        "image": "CC-Ubuntu22.04",
        "site": site,
    })
    assert resp.status_code == 200, f"Add Chameleon node failed: {resp.text}"
    return slice_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCompositeProvision:
    """Real provisioning tests for composite slices."""

    def test_composite_fabric_only(self, api, fabric_ok):
        """Composite with one FABRIC member — submit and wait for Active."""
        slug = f"e2e-comp-fab-{int(time.time())}"
        comp_id = None
        fab_name = f"e2e-fab-comp-{int(time.time())}"

        try:
            # Create FABRIC draft
            _create_fabric_draft_with_node(api, fab_name)

            # Create composite
            resp = api.post("/composite/slices", json={"name": slug})
            assert resp.status_code == 200
            comp_id = resp.json()["id"]

            # Add FABRIC member
            resp = api.put(f"/composite/slices/{comp_id}/members", json={
                "fabric_slices": [fab_name],
                "chameleon_slices": [],
            })
            assert resp.status_code == 200

            # Submit composite
            resp = api.post(f"/composite/slices/{comp_id}/submit", json={}, timeout=120.0)
            assert resp.status_code == 200

            # Wait for Active
            data = _wait_composite_state(api, comp_id, "Active")
            assert data["state"] == "Active"

            # Verify FABRIC member is StableOK
            fab_summaries = data.get("fabric_member_summaries", [])
            assert len(fab_summaries) >= 1
            assert fab_summaries[0]["state"] == "StableOK"

        finally:
            if comp_id:
                _cleanup_composite(api, comp_id)
            _cleanup_fabric_slice(api, fab_name)

    def test_composite_chameleon_only(self, api, chameleon_ok, chi_site):
        """Composite with one Chameleon member — submit and wait for Active."""
        slug = f"e2e-comp-chi-{int(time.time())}"
        comp_id = None
        chi_id = None

        try:
            # Create Chameleon draft
            chi_name = f"e2e-chi-comp-{int(time.time())}"
            chi_id = _create_chi_draft_with_node(api, chi_name, chi_site)

            # Create composite
            resp = api.post("/composite/slices", json={"name": slug})
            assert resp.status_code == 200
            comp_id = resp.json()["id"]

            # Add Chameleon member
            resp = api.put(f"/composite/slices/{comp_id}/members", json={
                "fabric_slices": [],
                "chameleon_slices": [chi_id],
            })
            assert resp.status_code == 200

            # Submit composite
            resp = api.post(f"/composite/slices/{comp_id}/submit", json={}, timeout=300.0)
            assert resp.status_code == 200

            # Wait for Active
            data = _wait_composite_state(api, comp_id, "Active")
            assert data["state"] == "Active"

        finally:
            if comp_id:
                _cleanup_composite(api, comp_id)
            if chi_id:
                _cleanup_chi_slice(api, chi_id)

    def test_composite_state_transitions(self, api, fabric_ok):
        """Verify composite state: Draft -> Provisioning -> Active."""
        slug = f"e2e-comp-trans-{int(time.time())}"
        comp_id = None
        fab_name = f"e2e-fab-trans-{int(time.time())}"

        try:
            _create_fabric_draft_with_node(api, fab_name)

            resp = api.post("/composite/slices", json={"name": slug})
            assert resp.status_code == 200
            comp_id = resp.json()["id"]

            # Initial state: Draft
            resp = api.get(f"/composite/slices/{comp_id}")
            assert resp.json()["state"] == "Draft"

            # Add member
            api.put(f"/composite/slices/{comp_id}/members", json={
                "fabric_slices": [fab_name], "chameleon_slices": [],
            })

            # Submit
            api.post(f"/composite/slices/{comp_id}/submit", json={}, timeout=120.0)

            # Should transition through Provisioning
            # (check immediately — FABRIC takes time to provision)
            resp = api.get(f"/composite/slices/{comp_id}")
            state = resp.json()["state"]
            assert state in ("Provisioning", "Active"), f"Expected Provisioning/Active, got {state}"

            # Wait for Active
            data = _wait_composite_state(api, comp_id, "Active")
            assert data["state"] == "Active"

        finally:
            if comp_id:
                _cleanup_composite(api, comp_id)
            _cleanup_fabric_slice(api, fab_name)

    def test_composite_cross_testbed_with_ping(self, api, fabric_ok, chameleon_ok, chi_site):
        """Cross-testbed test: FABRIC node + Chameleon node, both on FABNetv4, ping each other.

        This is the key integration test: a composite slice with one FABRIC node
        on a FABNetv4 network and one Chameleon node connected via FABNetv4,
        verifying end-to-end L3 reachability.
        """
        slug = f"e2e-comp-ping-{int(time.time())}"
        comp_id = None
        fab_name = f"e2e-fab-ping-{int(time.time())}"
        chi_id = None

        try:
            # --- FABRIC side: create draft with node + NIC + FABNetv4 ---
            _create_fabric_draft_with_node(api, fab_name, add_nic=True)

            # Get the NIC interface name to attach to the network
            resp = api.get(f"/slices/{fab_name}")
            assert resp.status_code == 200
            fab_data = resp.json()
            fab_nodes = fab_data.get("nodes", [])
            assert len(fab_nodes) >= 1

            # Find the NIC interface
            iface_name = None
            for node in fab_nodes:
                for comp in node.get("components", []):
                    for iface in comp.get("interfaces", []):
                        iface_name = iface.get("name")
                        if iface_name:
                            break
                    if iface_name:
                        break

            assert iface_name, "No NIC interface found on FABRIC node"

            # Add FABNetv4 network attached to the NIC
            resp = api.post(f"/slices/{fab_name}/networks", json={
                "name": "fabnet",
                "type": "FABNetv4",
                "interfaces": [iface_name],
            })
            assert resp.status_code == 200, f"Add FABNetv4 network failed: {resp.text}"

            # --- Chameleon side: create draft with node ---
            chi_name = f"e2e-chi-ping-{int(time.time())}"
            chi_id = _create_chi_draft_with_node(api, chi_name, chi_site)

            # --- Composite: link them ---
            resp = api.post("/composite/slices", json={"name": slug})
            assert resp.status_code == 200
            comp_id = resp.json()["id"]

            resp = api.put(f"/composite/slices/{comp_id}/members", json={
                "fabric_slices": [fab_name],
                "chameleon_slices": [chi_id],
            })
            assert resp.status_code == 200

            # Set cross-connection
            resp = api.put(f"/composite/slices/{comp_id}/cross-connections", json=[{
                "type": "fabnetv4",
                "fabric_slice": fab_name,
                "fabric_node": "fab-node1",
                "chameleon_slice": chi_id,
                "chameleon_node": "chi-node1",
            }])
            assert resp.status_code == 200

            # --- Submit composite (deploys both in parallel) ---
            resp = api.post(f"/composite/slices/{comp_id}/submit", json={}, timeout=300.0)
            assert resp.status_code == 200
            submit_result = resp.json()

            # Check no errors in submit
            fab_results = submit_result.get("fabric_results", [])
            chi_results = submit_result.get("chameleon_results", [])
            for r in fab_results:
                assert r.get("status") != "error", f"FABRIC submit error: {r}"
            for r in chi_results:
                assert r.get("status") != "error", f"Chameleon submit error: {r}"

            # Update fab_name if the draft was replaced with a new UUID
            if fab_results and fab_results[0].get("new_id"):
                new_fab_id = fab_results[0]["new_id"]
                fab_name_resolved = fab_results[0].get("name", fab_name)
            else:
                fab_name_resolved = fab_name

            # --- Wait for both sides to be active ---
            # Wait for FABRIC StableOK
            fab_data = _wait_fabric_slice_ok(api, fab_name_resolved)

            # Wait for Chameleon instances ACTIVE
            _wait_chi_instances_active(api, chi_id)

            # Auto-network-setup on Chameleon side
            resp = api.post(f"/chameleon/slices/{chi_id}/auto-network-setup", timeout=120.0)
            assert resp.status_code == 200

            # Composite should now be Active
            comp_data = _wait_composite_state(api, comp_id, "Active")
            assert comp_data["state"] == "Active"

            # --- Ping test: FABRIC node pings Chameleon node ---
            # Get Chameleon node's IP from auto-network-setup or check-readiness
            resp = api.post(f"/chameleon/slices/{chi_id}/check-readiness", timeout=60.0)
            chi_results = resp.json().get("results", [])
            chi_ip = None
            for r in chi_results:
                if r.get("ip"):
                    chi_ip = r["ip"]
                    break

            if chi_ip:
                # Execute ping from FABRIC node to Chameleon node
                start = time.time()
                ping_ok = False
                while time.time() - start < PING_TIMEOUT:
                    try:
                        resp = api.post(
                            f"/api/files/vm/{fab_name_resolved}/fab-node1/execute",
                            json={"command": f"ping -c 3 -W 5 {chi_ip}"},
                            timeout=30.0,
                        )
                        if resp.status_code == 200:
                            result = resp.json()
                            stdout = result.get("stdout", "")
                            if "bytes from" in stdout and "0% packet loss" in stdout:
                                ping_ok = True
                                break
                    except Exception:
                        pass
                    time.sleep(10)

                assert ping_ok, (
                    f"FABRIC node could not ping Chameleon node at {chi_ip} "
                    f"within {PING_TIMEOUT}s"
                )
            else:
                pytest.skip("Could not determine Chameleon node IP for ping test")

        finally:
            if comp_id:
                _cleanup_composite(api, comp_id)
            _cleanup_fabric_slice(api, fab_name)
            if chi_id:
                _cleanup_chi_slice(api, chi_id)

    def test_composite_graph_has_merged_topology(self, api, fabric_ok, chameleon_ok, chi_site):
        """After submit, composite graph should contain nodes from both testbeds."""
        slug = f"e2e-comp-graph-{int(time.time())}"
        comp_id = None
        fab_name = f"e2e-fab-graph-{int(time.time())}"
        chi_id = None

        try:
            _create_fabric_draft_with_node(api, fab_name)
            chi_name = f"e2e-chi-graph-{int(time.time())}"
            chi_id = _create_chi_draft_with_node(api, chi_name, chi_site)

            resp = api.post("/composite/slices", json={"name": slug})
            assert resp.status_code == 200
            comp_id = resp.json()["id"]

            api.put(f"/composite/slices/{comp_id}/members", json={
                "fabric_slices": [fab_name],
                "chameleon_slices": [chi_id],
            })

            # Submit
            api.post(f"/composite/slices/{comp_id}/submit", json={}, timeout=300.0)

            # Wait for Active
            _wait_composite_state(api, comp_id, "Active")

            # Get composite graph
            resp = api.get(f"/composite/slices/{comp_id}/graph")
            assert resp.status_code == 200
            graph = resp.json()

            # Graph should have nodes from both testbeds
            nodes = graph.get("nodes", [])
            if isinstance(nodes, list) and len(nodes) > 0:
                # Check for at least 2 nodes (one from each testbed)
                node_labels = [n.get("data", {}).get("label", "") for n in nodes]
                assert len(nodes) >= 2, f"Expected at least 2 nodes, got {len(nodes)}: {node_labels}"
            elif "elements" in graph:
                elements = graph["elements"]
                graph_nodes = elements.get("nodes", [])
                assert len(graph_nodes) >= 2

        finally:
            if comp_id:
                _cleanup_composite(api, comp_id)
            _cleanup_fabric_slice(api, fab_name)
            if chi_id:
                _cleanup_chi_slice(api, chi_id)
