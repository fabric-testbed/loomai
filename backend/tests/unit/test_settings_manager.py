"""Unit tests for app.settings_manager — load/save, accessors, env vars, tool configs."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

import app.settings_manager as sm


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path):
    """Redirect settings_manager to use an isolated temp directory."""
    storage = tmp_path / "fabric_work"
    storage.mkdir()
    config_dir = storage / "fabric_config"
    config_dir.mkdir()
    # Create slice keys so get_default_slice_key_path works
    keys_dir = config_dir / "slice_keys" / "default"
    keys_dir.mkdir(parents=True)
    (keys_dir / "slice_key").write_text("fake-private-key")
    (keys_dir / "slice_key.pub").write_text("fake-public-key")

    env_vars = {
        "FABRIC_STORAGE_DIR": str(storage),
        "FABRIC_CONFIG_DIR": str(config_dir),
    }
    with patch.dict(os.environ, env_vars):
        # Patch user_registry so get_storage_dir returns flat storage
        with patch("app.user_registry.get_user_storage_dir", return_value=None):
            # Clear cached settings
            old_cache = sm._cached_settings
            sm._cached_settings = None
            yield storage
            sm._cached_settings = old_cache


# ---------------------------------------------------------------------------
# get_storage_dir / get_root_storage_dir
# ---------------------------------------------------------------------------


class TestStorageDirs:
    def test_get_storage_dir_returns_env(self, isolated_storage):
        assert sm.get_storage_dir() == str(isolated_storage)

    def test_get_root_storage_dir(self, isolated_storage):
        assert sm.get_root_storage_dir() == str(isolated_storage)


# ---------------------------------------------------------------------------
# load_settings
# ---------------------------------------------------------------------------


class TestLoadSettings:
    def test_load_no_file_returns_defaults(self, isolated_storage):
        """When no settings.json exists, defaults are returned."""
        settings = sm.load_settings()
        assert settings["schema_version"] == 1
        assert "fabric" in settings
        assert "ai" in settings
        assert "paths" in settings
        assert "chameleon" in settings

    def test_load_existing_file(self, isolated_storage):
        """When settings.json exists on disk, its values are loaded."""
        settings_dir = os.path.join(str(isolated_storage), ".loomai")
        os.makedirs(settings_dir, exist_ok=True)
        custom = {
            "schema_version": 1,
            "fabric": {"project_id": "custom-project"},
        }
        with open(os.path.join(settings_dir, "settings.json"), "w") as f:
            json.dump(custom, f)

        settings = sm.load_settings()
        assert settings["fabric"]["project_id"] == "custom-project"
        # Defaults for missing keys should still be present
        assert "ai" in settings
        assert "paths" in settings

    def test_load_corrupt_file_returns_defaults(self, isolated_storage):
        """Corrupt settings.json should fall back to defaults."""
        settings_dir = os.path.join(str(isolated_storage), ".loomai")
        os.makedirs(settings_dir, exist_ok=True)
        with open(os.path.join(settings_dir, "settings.json"), "w") as f:
            f.write("NOT VALID JSON")

        settings = sm.load_settings()
        # Should get defaults
        assert settings["schema_version"] == 1

    def test_load_caches_result(self, isolated_storage):
        """Subsequent loads return cached result."""
        s1 = sm.load_settings()
        s2 = sm._get_settings()
        assert s1 is s2


# ---------------------------------------------------------------------------
# save_settings
# ---------------------------------------------------------------------------


class TestSaveSettings:
    def test_save_and_reload(self, isolated_storage):
        settings = sm.load_settings()
        settings["fabric"]["project_id"] = "saved-project"
        sm.save_settings(settings)

        # Invalidate cache and reload
        sm.invalidate_settings_cache()
        reloaded = sm.load_settings()
        assert reloaded["fabric"]["project_id"] == "saved-project"

    def test_save_creates_settings_file(self, isolated_storage):
        settings = sm.get_default_settings()
        sm.save_settings(settings)
        path = sm.get_settings_path()
        assert os.path.isfile(path)

    def test_save_generates_fabric_rc(self, isolated_storage):
        settings = sm.load_settings()
        settings["fabric"]["project_id"] = "rc-test"
        sm.save_settings(settings)
        rc_path = os.path.join(str(isolated_storage), "fabric_config", "fabric_rc")
        assert os.path.isfile(rc_path)
        with open(rc_path) as f:
            content = f.read()
        assert "rc-test" in content

    def test_save_generates_ssh_config(self, isolated_storage):
        settings = sm.load_settings()
        settings["fabric"]["bastion_username"] = "testuser"
        sm.save_settings(settings)
        ssh_path = os.path.join(str(isolated_storage), "fabric_config", "ssh_config")
        assert os.path.isfile(ssh_path)
        with open(ssh_path) as f:
            content = f.read()
        assert "testuser" in content


# ---------------------------------------------------------------------------
# AI key accessors
# ---------------------------------------------------------------------------


class TestAIAccessors:
    def test_get_fabric_api_key(self, isolated_storage):
        settings = sm.load_settings()
        settings["ai"]["fabric_api_key"] = "test-api-key"
        sm.save_settings(settings)
        sm.invalidate_settings_cache()
        assert sm.get_fabric_api_key() == "test-api-key"

    def test_get_nrp_api_key(self, isolated_storage):
        settings = sm.load_settings()
        settings["ai"]["nrp_api_key"] = "nrp-key"
        sm.save_settings(settings)
        sm.invalidate_settings_cache()
        assert sm.get_nrp_api_key() == "nrp-key"

    def test_get_ai_server_url_default(self, isolated_storage):
        assert sm.get_ai_server_url() == "https://ai.fabric-testbed.net"

    def test_get_nrp_server_url_default(self, isolated_storage):
        assert sm.get_nrp_server_url() == "https://ellm.nrp-nautilus.io"

    def test_set_default_model(self, isolated_storage):
        sm.load_settings()
        sm.set_default_model("llama-3", source="fabric")
        sm.invalidate_settings_cache()
        assert sm.get_default_model() == "llama-3"
        assert sm.get_default_model_source() == "fabric"


# ---------------------------------------------------------------------------
# Chameleon accessors
# ---------------------------------------------------------------------------


class TestChameleonAccessors:
    def test_is_chameleon_enabled_default(self, isolated_storage):
        sm.load_settings()
        assert sm.is_chameleon_enabled() is False

    def test_is_chameleon_enabled_set(self, isolated_storage):
        settings = sm.load_settings()
        settings["chameleon"]["enabled"] = True
        sm.save_settings(settings)
        sm.invalidate_settings_cache()
        assert sm.is_chameleon_enabled() is True

    def test_get_chameleon_sites(self, isolated_storage):
        sites = sm.get_chameleon_sites()
        assert "CHI@TACC" in sites
        assert "CHI@UC" in sites

    def test_get_chameleon_ssh_key_fallback(self, isolated_storage):
        """When chameleon.ssh_key_file is empty, should fall back to FABRIC slice key."""
        sm.load_settings()
        key = sm.get_chameleon_ssh_key()
        # Should return a path to the FABRIC slice key (or empty if not found)
        assert isinstance(key, str)
        if key:
            assert "slice_key" in key

    def test_get_chameleon_ssh_key_explicit(self, isolated_storage):
        settings = sm.load_settings()
        settings["chameleon"]["ssh_key_file"] = "/custom/chi_key"
        sm.save_settings(settings)
        sm.invalidate_settings_cache()
        assert sm.get_chameleon_ssh_key() == "/custom/chi_key"

    def test_is_chameleon_site_configured(self, isolated_storage):
        """A site without credentials should not be configured."""
        assert sm.is_chameleon_site_configured("CHI@TACC") is False

    def test_is_chameleon_site_configured_with_creds(self, isolated_storage):
        settings = sm.load_settings()
        settings["chameleon"]["sites"]["CHI@TACC"]["app_credential_id"] = "cred-id"
        settings["chameleon"]["sites"]["CHI@TACC"]["app_credential_secret"] = "cred-secret"
        sm.save_settings(settings)
        sm.invalidate_settings_cache()
        assert sm.is_chameleon_site_configured("CHI@TACC") is True


# ---------------------------------------------------------------------------
# apply_env_vars
# ---------------------------------------------------------------------------


class TestApplyEnvVars:
    def test_sets_project_id(self, isolated_storage):
        settings = sm.load_settings()
        settings["fabric"]["project_id"] = "env-project"
        sm.apply_env_vars(settings)
        assert os.environ.get("FABRIC_PROJECT_ID") == "env-project"

    def test_sets_ai_api_key(self, isolated_storage):
        settings = sm.load_settings()
        settings["ai"]["fabric_api_key"] = "env-ai-key"
        sm.apply_env_vars(settings)
        assert os.environ.get("FABRIC_AI_API_KEY") == "env-ai-key"

    def test_sets_bastion_host(self, isolated_storage):
        settings = sm.load_settings()
        settings["fabric"]["hosts"]["bastion"] = "bastion.example.com"
        sm.apply_env_vars(settings)
        assert os.environ.get("FABRIC_BASTION_HOST") == "bastion.example.com"

    def test_sets_avoid_sites(self, isolated_storage):
        settings = sm.load_settings()
        settings["fabric"]["avoid_sites"] = ["SITE_A", "SITE_B"]
        sm.apply_env_vars(settings)
        assert os.environ.get("FABRIC_AVOID") == "SITE_A,SITE_B"


# ---------------------------------------------------------------------------
# seed_tool_configs
# ---------------------------------------------------------------------------


class TestSeedToolConfigs:
    def test_seed_no_docker_dir(self, isolated_storage):
        """When Docker AI tools dir doesn't exist, seeding is a no-op."""
        sm.load_settings()
        sm.seed_tool_configs()  # Should not raise

    def test_seed_copies_tool_dirs(self, isolated_storage, tmp_path):
        """Seed should copy tool directories from Docker image location."""
        # Create a fake Docker AI tools dir
        docker_tools = tmp_path / "docker_ai_tools"
        docker_tools.mkdir()
        tool_dir = docker_tools / "test-tool"
        tool_dir.mkdir()
        (tool_dir / "config.json").write_text('{"key": "value"}')

        sm.load_settings()
        with patch.object(sm, "_DOCKER_AI_TOOLS_DIR", str(docker_tools)):
            sm.seed_tool_configs()

        # Check the tool was copied
        target_dir = os.path.join(sm.get_settings_dir(), "tools", "test-tool")
        assert os.path.isdir(target_dir)
        assert os.path.isfile(os.path.join(target_dir, "config.json"))

    def test_seed_does_not_overwrite(self, isolated_storage, tmp_path):
        """Seeding should skip existing tool config directories."""
        docker_tools = tmp_path / "docker_ai_tools"
        docker_tools.mkdir()
        tool_dir = docker_tools / "existing-tool"
        tool_dir.mkdir()
        (tool_dir / "default.json").write_text('{"default": true}')

        sm.load_settings()
        # Pre-create the target directory with custom content
        target = os.path.join(sm.get_settings_dir(), "tools", "existing-tool")
        os.makedirs(target, exist_ok=True)
        with open(os.path.join(target, "custom.json"), "w") as f:
            f.write('{"custom": true}')

        with patch.object(sm, "_DOCKER_AI_TOOLS_DIR", str(docker_tools)):
            sm.seed_tool_configs()

        # Custom file should still be there, default should NOT have overwritten
        assert os.path.isfile(os.path.join(target, "custom.json"))
        assert not os.path.isfile(os.path.join(target, "default.json"))


# ---------------------------------------------------------------------------
# get_tool_config_status
# ---------------------------------------------------------------------------


class TestGetToolConfigStatus:
    def test_returns_list(self, isolated_storage, tmp_path):
        """Should return a list of tool dicts."""
        docker_tools = tmp_path / "docker_ai_tools"
        docker_tools.mkdir()
        (docker_tools / "aider").mkdir()

        sm.load_settings()
        with patch.object(sm, "_DOCKER_AI_TOOLS_DIR", str(docker_tools)):
            status = sm.get_tool_config_status()

        assert isinstance(status, list)
        tool_names = [t["tool"] for t in status]
        assert "aider" in tool_names

    def test_status_includes_files(self, isolated_storage, tmp_path):
        """Tools with config should list their files."""
        docker_tools = tmp_path / "docker_ai_tools"
        docker_tools.mkdir()

        sm.load_settings()
        # Create a tool config manually
        tool_cfg = os.path.join(sm.get_settings_dir(), "tools", "my-tool")
        os.makedirs(tool_cfg, exist_ok=True)
        with open(os.path.join(tool_cfg, "settings.json"), "w") as f:
            f.write("{}")

        with patch.object(sm, "_DOCKER_AI_TOOLS_DIR", str(docker_tools)):
            status = sm.get_tool_config_status()

        my_tool = [t for t in status if t["tool"] == "my-tool"]
        assert len(my_tool) == 1
        assert my_tool[0]["has_config"] is True
        assert "settings.json" in my_tool[0]["files"]


# ---------------------------------------------------------------------------
# Default settings schema validation
# ---------------------------------------------------------------------------


class TestDefaultSchema:
    def test_defaults_have_all_sections(self, isolated_storage):
        defaults = sm.get_default_settings()
        assert "schema_version" in defaults
        assert "paths" in defaults
        assert "fabric" in defaults
        assert "ai" in defaults
        assert "chameleon" in defaults
        assert "services" in defaults
        assert "tool_configs" in defaults

    def test_defaults_ai_tools(self, isolated_storage):
        defaults = sm.get_default_settings()
        tools = defaults["ai"]["tools"]
        assert tools["aider"] is True
        assert tools["opencode"] is True
        assert tools["crush"] is True
        assert tools["claude"] is True
        assert tools["deepagents"] is True

    def test_defaults_chameleon_sites(self, isolated_storage):
        defaults = sm.get_default_settings()
        sites = defaults["chameleon"]["sites"]
        assert "CHI@TACC" in sites
        assert "CHI@UC" in sites
        assert "CHI@Edge" in sites
        assert "KVM@TACC" in sites

    def test_defaults_fabric_hosts(self, isolated_storage):
        defaults = sm.get_default_settings()
        hosts = defaults["fabric"]["hosts"]
        assert hosts["credmgr"] == "cm.fabric-testbed.net"
        assert hosts["orchestrator"] == "orchestrator.fabric-testbed.net"
        assert hosts["bastion"] == "bastion.fabric-testbed.net"

    def test_defaults_service_ports(self, isolated_storage):
        defaults = sm.get_default_settings()
        assert defaults["services"]["jupyter_port"] == 8889
        assert defaults["services"]["model_proxy_port"] == 9199


# ---------------------------------------------------------------------------
# invalidate_settings_cache
# ---------------------------------------------------------------------------


class TestInvalidateCache:
    def test_invalidate_clears_cache(self, isolated_storage):
        sm.load_settings()
        assert sm._cached_settings is not None
        sm.invalidate_settings_cache()
        assert sm._cached_settings is None


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_overlay_overrides_leaf(self):
        base = {"a": {"b": 1, "c": 2}}
        overlay = {"a": {"b": 10}}
        result = sm._deep_merge(base, overlay)
        assert result["a"]["b"] == 10
        assert result["a"]["c"] == 2

    def test_overlay_adds_new_keys(self):
        base = {"a": 1}
        overlay = {"b": 2}
        result = sm._deep_merge(base, overlay)
        assert result["a"] == 1
        assert result["b"] == 2

    def test_does_not_mutate_base(self):
        base = {"a": {"nested": 1}}
        overlay = {"a": {"nested": 99}}
        sm._deep_merge(base, overlay)
        assert base["a"]["nested"] == 1


# ---------------------------------------------------------------------------
# Path accessors
# ---------------------------------------------------------------------------


class TestPathAccessors:
    def test_get_config_dir(self, isolated_storage):
        config_dir = sm.get_config_dir()
        assert os.path.isdir(config_dir)

    def test_get_artifacts_dir(self, isolated_storage):
        artifacts_dir = sm.get_artifacts_dir()
        assert os.path.isdir(artifacts_dir)

    def test_get_slices_dir(self, isolated_storage):
        slices_dir = sm.get_slices_dir()
        assert os.path.isdir(slices_dir)

    def test_get_log_file(self, isolated_storage):
        log_file = sm.get_log_file()
        assert log_file == "/tmp/fablib/fablib.log"
