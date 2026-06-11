"""Per-user storage now lives under .loomai/users/, with a one-time relocation."""
import os


def test_user_storage_dir_is_under_loomai(tmp_path, monkeypatch):
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
    from app import user_registry
    assert user_registry.users_base_dir() == str(tmp_path / ".loomai" / "users")
    assert user_registry.get_user_storage_dir("abc") == str(tmp_path / ".loomai" / "users" / "abc")


def test_relocation_moves_data_and_repoints_symlinks(tmp_path, monkeypatch):
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
    from app import user_registry
    from app.routes import config

    uuid = "12345678-1111-2222-3333-444455556666"
    # Old layout: {storage}/users/{uuid}/fabric_config/id_token.json
    old_cfg = tmp_path / "users" / uuid / "fabric_config"
    old_cfg.mkdir(parents=True)
    (old_cfg / "id_token.json").write_text("TOKEN")
    # Registry points at the user but the new-location folder doesn't exist yet
    # (write it directly so add_user doesn't pre-create the new dir).
    import json
    (tmp_path / ".loomai").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".loomai" / "user_registry.json").write_text(
        json.dumps({"schema_version": 1, "active_user": uuid,
                    "users": [{"uuid": uuid, "name": "Name", "email": "e@x"}]}))

    config.relocate_users_to_loomai()

    new_dir = tmp_path / ".loomai" / "users" / uuid
    assert (new_dir / "fabric_config" / "id_token.json").read_text() == "TOKEN"
    assert not (tmp_path / "users").exists()          # old base removed

    # Active user's root symlink now points into .loomai/users/
    link = tmp_path / "fabric_config"
    assert link.is_symlink()
    assert os.path.realpath(link) == os.path.realpath(new_dir / "fabric_config")


def test_relocation_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
    from app.routes import config
    # No old dir → no-op, no error.
    config.relocate_users_to_loomai()
    config.relocate_users_to_loomai()


def test_folders_are_ground_truth(tmp_path, monkeypatch):
    """A UUID-named folder under .loomai/users/ IS a user; deleting it removes them."""
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
    import shutil
    from app import user_registry

    assert user_registry.list_users() == []          # nothing yet → no users

    u1 = "aaaaaaaa-1111-1111-1111-111111111111"
    u2 = "bbbbbbbb-2222-2222-2222-222222222222"
    user_registry.add_user(u1, "Alice", "a@x")
    user_registry.add_user(u2, "Bob", "b@x")
    uuids = {u["uuid"] for u in user_registry.list_users()}
    assert uuids == {u1, u2}

    # Manually delete u2's folder → it disappears from the list (ground truth).
    shutil.rmtree(tmp_path / ".loomai" / "users" / u2)
    assert {u["uuid"] for u in user_registry.list_users()} == {u1}

    # A non-UUID folder is ignored.
    (tmp_path / ".loomai" / "users" / "not-a-user").mkdir()
    assert {u["uuid"] for u in user_registry.list_users()} == {u1}


def test_active_falls_back_when_folder_deleted(tmp_path, monkeypatch):
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
    import shutil
    from app import user_registry
    u1 = "aaaaaaaa-1111-1111-1111-111111111111"
    u2 = "bbbbbbbb-2222-2222-2222-222222222222"
    user_registry.add_user(u1, "Alice", "a@x")       # becomes active
    user_registry.add_user(u2, "Bob", "b@x")
    user_registry.set_active_user(u2)
    assert user_registry.get_active_user_uuid() == u2
    shutil.rmtree(tmp_path / ".loomai" / "users" / u2)   # delete the active user's folder
    assert user_registry.get_active_user_uuid() == u1    # falls back
