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
    monkeypatch.setenv("LOOMAI_MANAGE_HOME_AI", "1")   # container-only behavior
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
    monkeypatch.setenv("LOOMAI_MANAGE_HOME_AI", "1")   # container-only behavior
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


def test_home_ai_paths_untouched_outside_container(tmp_path, monkeypatch):
    """Regression: outside the container (no LOOMAI_COMBINED_IMAGE marker),
    _ensure_user_symlinks must NOT move/symlink home AI dotfiles. It once
    moved a developer's real ~/.claude into pytest tmp storage and left a
    dangling symlink after the tmp dir was pruned."""
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("LOOMAI_MANAGE_HOME_AI", raising=False)
    monkeypatch.delenv("LOOMAI_COMBINED_IMAGE", raising=False)
    from app import user_registry
    from app.routes import config

    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    (home / ".claude" / "skills").mkdir()
    (home / ".claude" / "skills" / "SKILL.md").write_text("precious")
    (home / ".claude.json").write_text("{}")

    uuid = "aaaaaaaa-1111-1111-1111-111111111111"
    user_registry.add_user(uuid, "A", "a@x")
    config._ensure_user_symlinks(uuid)

    # Home dotfiles are still real (not symlinks) with content intact.
    assert not (home / ".claude").is_symlink()
    assert (home / ".claude" / "skills" / "SKILL.md").read_text() == "precious"
    assert not (home / ".claude.json").is_symlink()
    # And nothing was mounted into the per-user folder.
    assert not (tmp_path / ".loomai" / "users" / uuid / ".claude" / "skills").exists()


def test_restore_ai_tool_configs_noop_outside_container(tmp_path, monkeypatch):
    """Regression: restore_ai_tool_configs rmtree's ~/.claude and ~/.codex —
    it must be a no-op outside the container."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("LOOMAI_MANAGE_HOME_AI", raising=False)
    monkeypatch.delenv("LOOMAI_COMBINED_IMAGE", raising=False)
    from app.routes import ai_terminal

    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text("{}")
    (home / ".codex").mkdir()
    (home / ".codex" / "auth.json").write_text("{}")

    ai_terminal.restore_ai_tool_configs()

    assert (home / ".claude" / "settings.json").exists()
    assert (home / ".codex" / "auth.json").exists()
