"""Chameleon Cloud end-to-end integration tests.

These tests hit the real Chameleon API via the LoomAI backend HTTP endpoints.
They are gated behind ``@pytest.mark.chameleon`` and excluded from default runs.

Run with::

    pytest tests/chameleon/test_chameleon_e2e.py -v -s -m chameleon --timeout=600
"""

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.chameleon

BASE_URL = os.environ.get("LOOMAI_BASE_URL", "http://localhost:8000")
PREFERRED_SITES = ["CHI@UC", "CHI@TACC", "KVM@TACC"]


@pytest.fixture(scope="session")
def api_client():
    return httpx.Client(base_url=f"{BASE_URL}/api", timeout=60.0)


@pytest.fixture(scope="session")
def chameleon_configured(api_client):
    try:
        resp = api_client.get("/chameleon/sites")
        if resp.status_code != 200:
            pytest.skip("Chameleon not configured or unreachable")
        sites = resp.json()
        if not sites:
            pytest.skip("No Chameleon sites available")
        return sites
    except Exception:
        pytest.skip("Chameleon not configured or backend not running")


@pytest.fixture(scope="session")
def test_site(chameleon_configured):
    site_names = [s.get("name", s) if isinstance(s, dict) else s for s in chameleon_configured]
    for preferred in PREFERRED_SITES:
        if preferred in site_names:
            return preferred
    return site_names[0]


# --- Tests ---

def test_list_sites(api_client, chameleon_configured):
    resp = api_client.get("/chameleon/sites")
    assert resp.status_code == 200
    sites = resp.json()
    assert len(sites) > 0


def test_list_node_types(api_client, test_site):
    resp = api_client.get(f"/chameleon/sites/{test_site}/node-types")
    assert resp.status_code == 200
    data = resp.json()
    assert "node_types" in data or isinstance(data, list)


def test_list_images(api_client, test_site):
    resp = api_client.get(f"/chameleon/sites/{test_site}/images")
    assert resp.status_code == 200
    images = resp.json()
    assert len(images) > 0


def test_list_networks(api_client, test_site):
    resp = api_client.get(f"/chameleon/networks", params={"site": test_site})
    assert resp.status_code == 200
    networks = resp.json()
    assert isinstance(networks, list)


def test_list_keypairs(api_client, test_site):
    resp = api_client.get(f"/chameleon/keypairs", params={"site": test_site})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_ensure_keypair(api_client, test_site):
    resp = api_client.post(f"/chameleon/sites/{test_site}/ensure-keypair")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") in ("exists", "created", "recreated")


def test_create_and_delete_lease(api_client, test_site):
    """Create a real Blazar lease and delete it. Uses try/finally for cleanup."""
    # Find a common node type
    resp = api_client.get(f"/chameleon/sites/{test_site}/node-types")
    assert resp.status_code == 200
    node_types_data = resp.json()
    node_types = node_types_data.get("node_types", node_types_data) if isinstance(node_types_data, dict) else node_types_data
    assert len(node_types) > 0
    # Pick first available type
    node_type_name = node_types[0]["name"] if isinstance(node_types[0], dict) else node_types[0]

    lease_name = f"loomai-e2e-test-{int(time.time())}"
    lease_body = {
        "site": test_site,
        "name": lease_name,
        "node_type": node_type_name,
        "node_count": 1,
        "duration_hours": 1,
    }

    lease_id = None
    try:
        resp = api_client.post("/chameleon/leases", json=lease_body, timeout=120.0)
        assert resp.status_code == 200
        data = resp.json()
        lease_id = data.get("id") or data.get("lease", {}).get("id")
        assert lease_id, f"No lease ID in response: {data}"
    finally:
        if lease_id:
            del_resp = api_client.delete(
                f"/chameleon/leases/{lease_id}",
                params={"site": test_site},
                timeout=60.0,
            )
            assert del_resp.status_code in (200, 204, 404)


def test_list_leases(api_client, test_site):
    resp = api_client.get("/chameleon/leases", params={"site": test_site})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_draft_lifecycle(api_client):
    """Create draft -> add node -> get graph -> delete. No real Chameleon API calls."""
    # Create
    resp = api_client.post("/chameleon/drafts", json={"name": "e2e-test-draft", "site": "CHI@UC"})
    assert resp.status_code == 200
    draft = resp.json()
    draft_id = draft.get("id")
    assert draft_id

    try:
        # Add node
        resp = api_client.post(f"/chameleon/drafts/{draft_id}/nodes", json={
            "name": "test-node-1",
            "node_type": "compute_skylake",
            "image": "CC-Ubuntu22.04",
            "site": "CHI@UC",
        })
        assert resp.status_code == 200

        # Get graph
        resp = api_client.get(f"/chameleon/drafts/{draft_id}/graph")
        assert resp.status_code == 200
        graph = resp.json()
        assert "elements" in graph or "nodes" in graph
    finally:
        api_client.delete(f"/chameleon/drafts/{draft_id}")


def test_availability_query(api_client, test_site):
    resp = api_client.get(f"/chameleon/sites/{test_site}/availability")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, (dict, list))


def test_floating_ips_list(api_client, test_site):
    resp = api_client.get("/chameleon/floating-ips", params={"site": test_site})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_security_groups_list(api_client, test_site):
    resp = api_client.get("/chameleon/security-groups", params={"site": test_site})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
