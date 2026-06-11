"""Per-user AI-tool config swap (used on FABRIC user switch)."""
import os


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path / "storage"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    from app.routes import ai_terminal
    return ai_terminal


def test_restore_clears_stale_when_new_user_has_no_config(tmp_path, monkeypatch):
    """Switching to a user with no saved config must not inherit the previous
    user's Claude/Codex auth."""
    ai_terminal = _setup(tmp_path, monkeypatch)
    home = tmp_path / "home"
    (home / ".claude").mkdir()
    (home / ".claude" / ".credentials.json").write_text("PREV-USER-AUTH")
    (home / ".claude.json").write_text("{}")
    (home / ".codex").mkdir()
    (home / ".codex" / "auth.json").write_text("PREV-CODEX-AUTH")

    ai_terminal.restore_ai_tool_configs()        # incoming user has no backup

    assert not (home / ".claude").exists()
    assert not (home / ".claude.json").exists()
    assert not (home / ".codex").exists()


def test_backup_then_restore_round_trips(tmp_path, monkeypatch):
    ai_terminal = _setup(tmp_path, monkeypatch)
    from app.settings_manager import get_tool_config_dir
    home = tmp_path / "home"

    # User A's home config
    (home / ".claude").mkdir()
    (home / ".claude" / ".credentials.json").write_text("A-CREDS")
    (home / ".claude" / "settings.json").write_text("{}")
    (home / ".codex").mkdir()
    (home / ".codex" / "auth.json").write_text("A-CODEX")

    ai_terminal.backup_ai_tool_configs()         # → A's per-user store
    assert os.path.isfile(os.path.join(get_tool_config_dir("claude-code"), ".credentials.json"))
    assert os.path.isfile(os.path.join(get_tool_config_dir("codex"), "auth.json"))

    # Simulate the previous user's stale state lingering in home, then restore A.
    (home / ".claude" / "stale.txt").write_text("leak?")
    ai_terminal.restore_ai_tool_configs()

    assert (home / ".claude" / ".credentials.json").read_text() == "A-CREDS"
    assert (home / ".codex" / "auth.json").read_text() == "A-CODEX"
    # Stale file that wasn't in the backup is gone (home was cleared first).
    assert not (home / ".claude" / "stale.txt").exists()
