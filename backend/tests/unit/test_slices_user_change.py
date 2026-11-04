"""Switching user/token must forget in-memory drafts and cached results."""
from app import fabric_call_manager
from app.routes import slices
from app.user_context import notify_user_changed


def test_user_change_clears_drafts_and_cache():
    fabric_call_manager.reset_call_manager()
    mgr = fabric_call_manager.get_call_manager()
    mgr.store("slices:list", [{"name": "prev-user-slice"}])
    with slices._draft_lock:
        slices._draft_slices["prev-draft"] = object()
        slices._draft_is_new["prev-draft"] = True
        slices._draft_project_id["prev-draft"] = "p1"
        slices._draft_site_groups["prev-draft"] = {"n1": "@a"}

    notify_user_changed()

    assert not slices._draft_slices and not slices._draft_is_new
    assert not slices._draft_project_id and not slices._draft_site_groups
    assert mgr.peek("slices:list") is None
