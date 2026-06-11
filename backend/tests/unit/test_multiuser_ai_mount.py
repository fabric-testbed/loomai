"""Per-user AI-tool home mounting + multi-user K8s gating."""
import os


def test_multiuser_enabled_only_outside_k8s(monkeypatch):
    from app.routes import config
    monkeypatch.delenv("LOOMAI_BASE_PATH", raising=False)
    assert config.multiuser_enabled() is True
    monkeypatch.setenv("LOOMAI_BASE_PATH", "/user/abc")
    assert config.multiuser_enabled() is False


def test_handle_token_write_noop_in_k8s(tmp_path, monkeypatch):
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("LOOMAI_BASE_PATH", "/user/abc")
    from app.routes import config
    from app import user_registry
    # Would normally migrate/register; in K8s it must do nothing.
    config._handle_token_write({"id_token": "x.y.z"})
    assert user_registry.list_users() == []


def test_ensure_user_symlinks_mounts_ai_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    from app import user_registry
    from app.routes import config

    uuid = "aaaaaaaa-1111-1111-1111-111111111111"
    user_registry.add_user(uuid, "A", "a@x")

    # The user currently has real AI config in their home dir.
    home = tmp_path / "home"
    (home / ".claude").mkdir()
    (home / ".claude" / "creds").write_text("CLAUDE-AUTH")
    (home / ".codex").mkdir()
    (home / ".codex" / "auth.json").write_text("CODEX-AUTH")
    (home / ".claude.json").write_text("{}")

    config._ensure_user_symlinks(uuid)

    user_dir = tmp_path / ".loomai" / "users" / uuid
    # Home AI paths are now symlinks into the user's (persistent) folder, with
    # the existing content preserved there.
    for name in (".claude", ".codex", ".claude.json"):
        assert (home / name).is_symlink()
        assert os.path.realpath(home / name) == os.path.realpath(user_dir / name)
    assert (user_dir / ".claude" / "creds").read_text() == "CLAUDE-AUTH"
    assert (user_dir / ".codex" / "auth.json").read_text() == "CODEX-AUTH"


def test_switching_users_swaps_ai_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    from app import user_registry
    from app.routes import config
    home = tmp_path / "home"

    a = "aaaaaaaa-1111-1111-1111-111111111111"
    b = "bbbbbbbb-2222-2222-2222-222222222222"
    user_registry.add_user(a, "A", "a@x")
    user_registry.add_user(b, "B", "b@x")
    # Give each user a distinct stored claude cred.
    for u, val in ((a, "A-CRED"), (b, "B-CRED")):
        d = tmp_path / ".loomai" / "users" / u / ".claude"
        d.mkdir(parents=True)
        (d / "creds").write_text(val)

    config._ensure_user_symlinks(a)
    assert (home / ".claude" / "creds").read_text() == "A-CRED"
    config._ensure_user_symlinks(b)
    assert (home / ".claude" / "creds").read_text() == "B-CRED"   # swapped
