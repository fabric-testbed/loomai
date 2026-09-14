"""Tests for the CHP proxy route reconciler.

These cover the failure that took loomai.fabric-testbed.net down for users on
2026-09-14: the proxy pod restarted, CHP lost its in-memory routing table, and
users whose pods predated the restart were left running but unroutable. The
hub kept redirecting them to /user/<id>/ and the request kept falling back to
the hub, producing ERR_TOO_MANY_REDIRECTS.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.proxy import reconciler as R

ROUTED = "99aa6184-7ffc-45b3-a725-a5694efb88c1"
ORPHAN_A = "f2b25790-b1b9-421f-a998-16fc443dc999"
ORPHAN_B = "e89cc650-904d-40c0-855c-46dedc374691"
STOPPED = "11dab0f7-817d-4738-be25-9ba1ac758fd4"

# The shape CHP actually returns: the hub registers "/user/<id>/" but CHP
# reports it back without the trailing slash.
LIVE_ROUTES = {
    "/": {"target": "http://loomai-hub:8081"},
    f"/user/{ROUTED}": {"target": f"http://loomai-{ROUTED}:3000"},
}

RUNNING = {"phase": "Running", "ready": True, "message": "", "pod_ip": "10.0.0.1"}
NOT_FOUND = {"phase": "NotFound", "ready": False, "message": "", "pod_ip": None}
NOT_READY = {"phase": "Running", "ready": False, "message": "", "pod_ip": None}


def _patch(routes=LIVE_ROUTES, pod=RUNNING, add=None, routes_exc=None):
    """Patch the reconciler's three external calls."""
    get_routes = AsyncMock(side_effect=routes_exc) if routes_exc else AsyncMock(return_value=routes)
    return (
        patch.object(R, "get_routes", get_routes),
        patch.object(R, "add_route", add or AsyncMock()),
        patch.object(R, "get_pod_status", AsyncMock(return_value=pod)),
    )


class TestRouteSpecHelpers:
    def test_route_spec_has_trailing_slash(self):
        assert R.route_spec_for(ORPHAN_A) == f"/user/{ORPHAN_A}/"

    def test_target_points_at_the_user_service(self):
        assert R.target_for(ORPHAN_A) == f"http://loomai-{ORPHAN_A}:3000"

    def test_normalize_makes_chp_and_hub_specs_comparable(self):
        # The whole bug class: these must compare equal.
        assert R._normalize(f"/user/{ORPHAN_A}/") == R._normalize(f"/user/{ORPHAN_A}")


class TestEnsureRoute:
    async def test_existing_route_is_not_re_added(self):
        add = AsyncMock()
        gr, ar, gp = _patch(add=add)
        with gr, ar, gp:
            assert await R.ensure_route(ROUTED) is True
        # Re-adding every pass would spam CHP and the logs once a minute.
        assert add.await_count == 0

    async def test_missing_route_is_restored_for_a_running_pod(self):
        add = AsyncMock()
        gr, ar, gp = _patch(add=add)
        with gr, ar, gp:
            assert await R.ensure_route(ORPHAN_A) is True
        add.assert_awaited_once_with(
            f"/user/{ORPHAN_A}/", f"http://loomai-{ORPHAN_A}:3000"
        )

    async def test_dead_pod_is_not_routed(self):
        add = AsyncMock()
        gr, ar, gp = _patch(pod=NOT_FOUND, add=add)
        with gr, ar, gp:
            assert await R.ensure_route(ORPHAN_A) is False
        assert add.await_count == 0

    async def test_unready_pod_is_not_routed(self):
        # Routing to a pod that is not serving yet just turns the redirect
        # loop into a 503 loop.
        add = AsyncMock()
        gr, ar, gp = _patch(pod=NOT_READY, add=add)
        with gr, ar, gp:
            assert await R.ensure_route(ORPHAN_A) is False
        assert add.await_count == 0

    async def test_unreachable_proxy_fails_closed(self):
        # Must return False so callers do not redirect into the loop.
        add = AsyncMock()
        gr, ar, gp = _patch(add=add, routes_exc=RuntimeError("proxy down"))
        with gr, ar, gp:
            assert await R.ensure_route(ORPHAN_A) is False
        assert add.await_count == 0

    async def test_add_route_failure_is_reported_not_raised(self):
        gr, ar, gp = _patch(add=AsyncMock(side_effect=RuntimeError("CHP 500")))
        with gr, ar, gp:
            assert await R.ensure_route(ORPHAN_A) is False

    async def test_pod_status_failure_fails_closed(self):
        with patch.object(R, "get_routes", AsyncMock(return_value=LIVE_ROUTES)), \
             patch.object(R, "add_route", AsyncMock()) as add, \
             patch.object(R, "get_pod_status", AsyncMock(side_effect=RuntimeError("k8s down"))):
            assert await R.ensure_route(ORPHAN_A) is False
            assert add.await_count == 0

    async def test_known_routes_avoids_a_proxy_round_trip(self):
        # The sweep fetches the table once and passes it down.
        with patch.object(R, "get_routes", AsyncMock()) as get_routes, \
             patch.object(R, "add_route", AsyncMock()), \
             patch.object(R, "get_pod_status", AsyncMock(return_value=RUNNING)):
            await R.ensure_route(
                ORPHAN_A, known_routes={R._normalize(R.route_spec_for(ORPHAN_A))}
            )
            assert get_routes.await_count == 0


class TestReconcileSweep:
    @pytest.fixture
    async def populated(self, add_user):
        await add_user(ROUTED, "ready")
        await add_user(ORPHAN_A, "ready")
        await add_user(ORPHAN_B, "ready")
        await add_user(STOPPED, "stopped")

    async def test_restores_only_the_orphaned_routes(self, db_maker, populated):
        add = AsyncMock()
        gr, ar, gp = _patch(add=add)
        with gr, ar, gp:
            assert await R._reconcile_once(db_maker) == 2

        added = sorted(call.args[0] for call in add.await_args_list)
        assert added == sorted([f"/user/{ORPHAN_A}/", f"/user/{ORPHAN_B}/"])

    async def test_stopped_servers_are_left_alone(self, db_maker, populated):
        add = AsyncMock()
        gr, ar, gp = _patch(add=add)
        with gr, ar, gp:
            await R._reconcile_once(db_maker)
        assert all(STOPPED not in call.args[0] for call in add.await_args_list)

    async def test_sweep_is_idempotent(self, db_maker, populated):
        complete = dict(LIVE_ROUTES)
        complete[f"/user/{ORPHAN_A}"] = {}
        complete[f"/user/{ORPHAN_B}"] = {}

        add = AsyncMock()
        gr, ar, gp = _patch(routes=complete, add=add)
        with gr, ar, gp:
            assert await R._reconcile_once(db_maker) == 0
        assert add.await_count == 0

    async def test_no_routes_created_for_missing_pods(self, db_maker, populated):
        add = AsyncMock()
        gr, ar, gp = _patch(pod=NOT_FOUND, add=add)
        with gr, ar, gp:
            assert await R._reconcile_once(db_maker) == 0
        assert add.await_count == 0

    async def test_unreachable_proxy_is_survivable(self, db_maker, populated):
        add = AsyncMock()
        gr, ar, gp = _patch(add=add, routes_exc=RuntimeError("proxy down"))
        with gr, ar, gp:
            assert await R._reconcile_once(db_maker) == 0

    async def test_empty_database_is_a_no_op(self, db_maker):
        with patch.object(R, "get_routes", AsyncMock()) as get_routes:
            assert await R._reconcile_once(db_maker) == 0
            assert get_routes.await_count == 0
