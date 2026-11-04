"""get_cached_sites / get_fresh_sites must honor call-manager invalidation."""
from unittest.mock import patch

from app import fabric_call_manager
from app.routes import resources


def _mgr():
    fabric_call_manager.reset_call_manager()
    return fabric_call_manager.get_call_manager()


def test_cached_sites_refetches_after_invalidation():
    mgr = _mgr()
    mgr.store("sites", [{"name": "OLD"}])
    assert resources.get_cached_sites() == [{"name": "OLD"}]

    mgr.invalidate("sites")  # e.g. user/token changed
    with patch("app.routes.resources._fetch_sites_locked", return_value=[{"name": "NEW"}]) as fetch:
        assert resources.get_cached_sites() == [{"name": "NEW"}]
        assert fetch.call_count == 1
    # Stored as fresh: no further fetch.
    with patch("app.routes.resources._fetch_sites_locked") as fetch:
        assert resources.get_cached_sites() == [{"name": "NEW"}]
        fetch.assert_not_called()


def test_fresh_sites_leaves_entry_servable():
    mgr = _mgr()
    with patch("app.routes.resources._fetch_sites_locked", return_value=[{"name": "A"}]):
        assert resources.get_fresh_sites() == [{"name": "A"}]
    # The direct write used to leave the entry invalidated; store() must not.
    assert mgr.peek("sites", max_age=30) == [{"name": "A"}]
