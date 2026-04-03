"""Chameleon Cloud real-provisioning end-to-end tests.

These tests actually create leases, launch instances, and verify they become
ACTIVE and SSH-reachable.  They are slow (5-15 min) and require a live
Chameleon session.

Gate: ``@pytest.mark.chameleon`` — excluded from default runs.
Run::

    pytest tests/chameleon/test_chameleon_provision_e2e.py -v -s -m chameleon --timeout=900
"""

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.chameleon

BASE_URL = os.environ.get("LOOMAI_BASE_URL", "http://localhost:8000")
PREFERRED_SITES = ["CHI@UC", "CHI@TACC", "KVM@TACC"]
# Timeouts
DEPLOY_TIMEOUT = 600       # 10 min for lease + instance launch
INSTANCE_POLL = 15         # seconds between polls
ACTIVE_TIMEOUT = 600       # 10 min for instances to reach ACTIVE
READINESS_TIMEOUT = 300    # 5 min for SSH readiness


@pytest.fixture(scope="session")
def api():
    return httpx.Client(base_url=f"{BASE_URL}/api", timeout=60.0)


@pytest.fixture(scope="session")
def chameleon_ok(api):
    try:
        resp = api.get("/chameleon/sites")
        if resp.status_code != 200:
            pytest.skip("Chameleon not configured or unreachable")
        sites = resp.json()
        if not sites:
            pytest.skip("No Chameleon sites available")
        return sites
    except Exception:
        pytest.skip("Backend not running or Chameleon unavailable")


@pytest.fixture(scope="session")
def site(chameleon_ok):
    names = [s.get("name", s) if isinstance(s, dict) else s for s in chameleon_ok]
    for pref in PREFERRED_SITES:
        if pref in names:
            return pref
    return names[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _poll_instances_active(api: httpx.Client, slice_id: str, timeout: int = ACTIVE_TIMEOUT) -> list[dict]:
    """Poll until all instances in a Chameleon slice are ACTIVE. Returns instance list."""
    start = time.time()
    while time.time() - start < timeout:
        resp = api.get(f"/chameleon/slices/{slice_id}")
        if resp.status_code == 200:
            data = resp.json()
            resources = data.get("resources", [])
            instances = [r for r in resources if r.get("type") == "instance"]
            if instances:
                if all(i.get("status") == "ACTIVE" for i in instances):
                    return instances
                if any(i.get("status") == "ERROR" for i in instances):
                    pytest.fail(f"Instance(s) entered ERROR state: {instances}")
        time.sleep(INSTANCE_POLL)
    pytest.fail(f"Instances did not reach ACTIVE within {timeout}s")


def _cleanup_slice(api: httpx.Client, slice_id: str):
    """Best-effort delete a Chameleon slice and its resources."""
    try:
        api.delete(f"/chameleon/slices/{slice_id}", params={"delete_resources": True}, timeout=120.0)
    except Exception:
        pass


def _find_image(api: httpx.Client, site: str) -> str:
    """Find a usable Ubuntu image at the site."""
    resp = api.get(f"/chameleon/sites/{site}/images")
    if resp.status_code == 200:
        images = resp.json()
        for img in images:
            name = img.get("name", "") if isinstance(img, dict) else img
            if "Ubuntu" in name and "22" in name:
                return name
        if images:
            name = images[0].get("name", images[0]) if isinstance(images[0], dict) else images[0]
            return name
    return "CC-Ubuntu22.04"


def _find_node_type(api: httpx.Client, site: str) -> str:
    """Find a usable node type at the site."""
    resp = api.get(f"/chameleon/sites/{site}/node-types")
    if resp.status_code == 200:
        data = resp.json()
        types = data.get("node_types", data) if isinstance(data, dict) else data
        if types:
            return types[0]["name"] if isinstance(types[0], dict) else types[0]
    return "compute_skylake"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestChameleonProvision:
    """Real provisioning tests — create, deploy, verify, cleanup."""

    def test_create_deploy_single_node(self, api, site, chameleon_ok):
        """Create a slice with one node, deploy it, wait for ACTIVE, then cleanup."""
        slug = f"e2e-chi-prov-{int(time.time())}"
        node_type = _find_node_type(api, site)
        image = _find_image(api, site)
        slice_id = None

        try:
            # 1. Create slice
            resp = api.post("/chameleon/slices", json={"name": slug, "site": site})
            assert resp.status_code == 200, f"Create slice failed: {resp.text}"
            slice_data = resp.json()
            slice_id = slice_data["id"]

            # 2. Add a node
            resp = api.post(f"/chameleon/drafts/{slice_id}/nodes", json={
                "name": "node1",
                "node_type": node_type,
                "image": image,
                "site": site,
            })
            assert resp.status_code == 200, f"Add node failed: {resp.text}"

            # 3. Deploy (full_deploy: lease + instance launch)
            resp = api.post(f"/chameleon/drafts/{slice_id}/deploy", json={
                "lease_name": slug,
                "duration_hours": 1,
                "full_deploy": True,
            }, timeout=DEPLOY_TIMEOUT)
            assert resp.status_code == 200, f"Deploy failed: {resp.text}"

            # 4. Wait for instance ACTIVE
            instances = _poll_instances_active(api, slice_id)
            assert len(instances) >= 1
            assert instances[0]["status"] == "ACTIVE"

            # 5. Auto-network-setup (security group + floating IP)
            resp = api.post(f"/chameleon/slices/{slice_id}/auto-network-setup", timeout=120.0)
            assert resp.status_code == 200, f"Auto-network-setup failed: {resp.text}"

            # 6. Check readiness (SSH port reachability)
            start = time.time()
            ready = False
            while time.time() - start < READINESS_TIMEOUT:
                resp = api.post(f"/chameleon/slices/{slice_id}/check-readiness", timeout=60.0)
                if resp.status_code == 200:
                    results = resp.json().get("results", [])
                    if results and all(r.get("ssh_ready") for r in results):
                        ready = True
                        break
                time.sleep(15)
            assert ready, "Instance(s) did not become SSH-ready"

        finally:
            if slice_id:
                _cleanup_slice(api, slice_id)

    def test_deploy_multi_node(self, api, site, chameleon_ok):
        """Deploy a slice with 2 nodes, verify both reach ACTIVE."""
        slug = f"e2e-chi-multi-{int(time.time())}"
        node_type = _find_node_type(api, site)
        image = _find_image(api, site)
        slice_id = None

        try:
            resp = api.post("/chameleon/slices", json={"name": slug, "site": site})
            assert resp.status_code == 200
            slice_id = resp.json()["id"]

            # Add two nodes
            for i in range(2):
                resp = api.post(f"/chameleon/drafts/{slice_id}/nodes", json={
                    "name": f"node{i+1}",
                    "node_type": node_type,
                    "image": image,
                    "site": site,
                })
                assert resp.status_code == 200

            # Deploy
            resp = api.post(f"/chameleon/drafts/{slice_id}/deploy", json={
                "lease_name": slug,
                "duration_hours": 1,
                "full_deploy": True,
            }, timeout=DEPLOY_TIMEOUT)
            assert resp.status_code == 200

            # Wait for both instances ACTIVE
            instances = _poll_instances_active(api, slice_id)
            assert len(instances) >= 2
            assert all(i["status"] == "ACTIVE" for i in instances)

        finally:
            if slice_id:
                _cleanup_slice(api, slice_id)

    def test_slice_state_after_deploy(self, api, site, chameleon_ok):
        """Verify slice state transitions: Configuring -> Active after deploy."""
        slug = f"e2e-chi-state-{int(time.time())}"
        node_type = _find_node_type(api, site)
        image = _find_image(api, site)
        slice_id = None

        try:
            resp = api.post("/chameleon/slices", json={"name": slug, "site": site})
            assert resp.status_code == 200
            slice_data = resp.json()
            slice_id = slice_data["id"]
            # Initial state should be Configuring
            assert slice_data.get("state") in ("Configuring", "Draft"), \
                f"Expected Configuring/Draft, got {slice_data.get('state')}"

            # Add node and deploy
            api.post(f"/chameleon/drafts/{slice_id}/nodes", json={
                "name": "node1", "node_type": node_type, "image": image, "site": site,
            })
            api.post(f"/chameleon/drafts/{slice_id}/deploy", json={
                "lease_name": slug, "duration_hours": 1, "full_deploy": True,
            }, timeout=DEPLOY_TIMEOUT)

            # After deploy, state should be Active
            _poll_instances_active(api, slice_id)
            resp = api.get(f"/chameleon/slices/{slice_id}")
            assert resp.status_code == 200
            assert resp.json().get("state") == "Active"

        finally:
            if slice_id:
                _cleanup_slice(api, slice_id)
