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

    def test_get_notebooks_dir_does_not_create_folder(self, isolated_storage):
        notebooks_dir = os.path.join(str(isolated_storage), "notebooks")
        assert sm.get_notebooks_dir() == notebooks_dir
        assert not os.path.exists(notebooks_dir)


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
        assert settings["ai"]["harnesses"]["mcp_metatools"] is False
        assert sm.get_mcp_metatools_enabled() is False

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

    def test_legacy_zero_lease_policy_is_seeded_to_default_once(self, isolated_storage):
        settings_dir = os.path.join(str(isolated_storage), ".loomai")
        os.makedirs(settings_dir, exist_ok=True)
        path = os.path.join(settings_dir, "settings.json")
        with open(path, "w") as f:
            json.dump({
                "schema_version": 1,
                "fabric": {"slice_policy": {"max_lease_hours": 0}},
            }, f)

        settings = sm.load_settings()

        assert settings["fabric"]["slice_policy"]["max_lease_hours"] == 6
        assert settings["migrations"][sm._MIGRATION_SLICE_POLICY_DEFAULT] is True
        with open(path) as f:
            persisted = json.load(f)
        assert persisted["fabric"]["slice_policy"]["max_lease_hours"] == 6
        assert persisted["migrations"][sm._MIGRATION_SLICE_POLICY_DEFAULT] is True

    def test_lease_policy_migration_preserves_nonzero_override(self, isolated_storage):
        settings_dir = os.path.join(str(isolated_storage), ".loomai")
        os.makedirs(settings_dir, exist_ok=True)
        with open(os.path.join(settings_dir, "settings.json"), "w") as f:
            json.dump({
                "schema_version": 1,
                "fabric": {"slice_policy": {"max_lease_hours": 4}},
            }, f)

        settings = sm.load_settings()

        assert settings["fabric"]["slice_policy"]["max_lease_hours"] == 4
        assert settings["migrations"][sm._MIGRATION_SLICE_POLICY_DEFAULT] is True
        assert sm.get_max_slice_lease_hours() == 4

    def test_post_migration_zero_lease_policy_disables_cap(self, isolated_storage):
        settings_dir = os.path.join(str(isolated_storage), ".loomai")
        os.makedirs(settings_dir, exist_ok=True)
        with open(os.path.join(settings_dir, "settings.json"), "w") as f:
            json.dump({
                "schema_version": 1,
                "migrations": {sm._MIGRATION_SLICE_POLICY_DEFAULT: True},
                "fabric": {"slice_policy": {"max_lease_hours": 0}},
            }, f)

        settings = sm.load_settings()

        assert settings["fabric"]["slice_policy"]["max_lease_hours"] == 0
        assert sm.get_max_slice_lease_hours() is None

    def test_load_seeds_custom_provider_from_env_when_empty(self, isolated_storage, monkeypatch):
        monkeypatch.setenv("LOOMAI_CUSTOM_PROVIDER_AI_RENCI_BASE_URL", "https://ai-renci.example/v1/")
        monkeypatch.setenv("LOOMAI_CUSTOM_PROVIDER_AI_RENCI_API_KEY", "env-ai-renci-key")

        settings = sm.load_settings()

        providers = settings["ai"]["custom_providers"]
        ai_renci = next(p for p in providers if p["name"] == "ai-renci")
        assert ai_renci == {
            "name": "ai-renci",
            "base_url": "https://ai-renci.example/v1",
            "api_key": "env-ai-renci-key",
            "endpoint_style": "auto",
        }
        with open(sm.get_settings_path()) as f:
            persisted = json.load(f)
        assert any(p.get("name") == "ai-renci" for p in persisted["ai"]["custom_providers"])

    def test_load_preserves_persisted_custom_providers_over_env(self, isolated_storage, monkeypatch):
        monkeypatch.setenv("LOOMAI_CUSTOM_PROVIDER_AI_RENCI_BASE_URL", "https://ai-renci.example/v1")
        monkeypatch.setenv("LOOMAI_CUSTOM_PROVIDER_AI_RENCI_API_KEY", "env-ai-renci-key")
        settings_dir = os.path.join(str(isolated_storage), ".loomai")
        os.makedirs(settings_dir, exist_ok=True)
        with open(os.path.join(settings_dir, "settings.json"), "w") as f:
            json.dump({
                "schema_version": 1,
                "ai": {
                    "custom_providers": [{
                        "name": "manual",
                        "base_url": "https://manual.example/v1",
                        "api_key": "manual-key",
                        "endpoint_style": "chat",
                    }],
                },
            }, f)

        settings = sm.load_settings()

        assert settings["ai"]["custom_providers"] == [{
            "name": "manual",
            "base_url": "https://manual.example/v1",
            "api_key": "manual-key",
            "endpoint_style": "chat",
        }]

    def test_load_corrupt_file_returns_defaults(self, isolated_storage):
        """Corrupt settings.json should fall back to defaults."""
        settings_dir = os.path.join(str(isolated_storage), ".loomai")
        os.makedirs(settings_dir, exist_ok=True)
        with open(os.path.join(settings_dir, "settings.json"), "w") as f:
            f.write("NOT VALID JSON")

        settings = sm.load_settings()
        # Should get defaults
        assert settings["schema_version"] == 1

    def test_load_heals_empty_root_fallback_from_user_settings(self, isolated_storage):
        settings_dir = isolated_storage / ".loomai"
        settings_dir.mkdir(exist_ok=True)
        root_settings_path = settings_dir / "settings.json"
        root_settings_path.write_text(json.dumps({
            "schema_version": 1,
            "fabric": {"slice_policy": {"max_lease_hours": 6}},
        }))

        uuid = "aaaaaaaa-1111-1111-1111-111111111111"
        user_settings_dir = settings_dir / "users" / uuid / ".loomai"
        user_settings_dir.mkdir(parents=True)
        (user_settings_dir / "settings.json").write_text(json.dumps({
            "schema_version": 1,
            "fabric": {
                "bastion_username": "user-bastion",
                "project_id": "user-project",
            },
            "ai": {
                "fabric_api_key": "fabric-key",
                "nrp_api_key": "nrp-key",
                "custom_providers": [{
                    "name": "fabric",
                    "base_url": "https://ai.fabric-testbed.net",
                    "api_key": "provider-key",
                    "endpoint_style": "chat",
                }],
                "discovered_models": {"fabric": [{"id": "qwen3-coder-30b"}]},
            },
        }))

        settings = sm.load_settings()

        assert settings["fabric"]["bastion_username"] == "user-bastion"
        assert settings["fabric"]["project_id"] == "user-project"
        assert settings["ai"]["fabric_api_key"] == "fabric-key"
        assert settings["ai"]["nrp_api_key"] == "nrp-key"
        assert settings["ai"]["custom_providers"][0]["api_key"] == "provider-key"
        healed = json.loads(root_settings_path.read_text())
        assert healed["fabric"]["bastion_username"] == "user-bastion"
        assert healed["fabric"]["project_id"] == "user-project"

    def test_load_caches_result(self, isolated_storage):
        """Subsequent loads return cached result."""
        s1 = sm.load_settings()
        s2 = sm._get_settings()
        assert s1 is s2

    def test_mcp_metatools_setting_can_be_enabled(self, isolated_storage):
        settings = sm.load_settings()
        settings["ai"]["harnesses"]["mcp_metatools"] = True
        sm.save_settings(settings)
        sm.invalidate_settings_cache()

        assert sm.get_mcp_metatools_enabled() is True


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

    def test_save_seeds_missing_assistant_defaults(self, isolated_storage):
        sm.save_settings({"schema_version": 1, "ai": {"tools": {"aider": False}}})

        with open(sm.get_settings_path()) as f:
            on_disk = json.load(f)

        assistant = on_disk["ai"]["assistant"]
        assert assistant["strict_fabric_query_contract"] is True
        assert assistant["final_answer_retry"] is True
        assert assistant["compact_fabric_resource_tools"] is True
        assert assistant["resource_query_generation_defaults"] is True
        assert assistant["capability_profiles_enabled"] is True
        assert on_disk["ai"]["tools"]["aider"] is False

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

    def test_save_partial_update_preserves_manual_config(self, isolated_storage):
        settings = sm.load_settings()
        settings["fabric"]["bastion_username"] = "persisted-user"
        settings["fabric"]["project_id"] = "persisted-project"
        settings["fabric"]["slice_policy"]["max_lease_hours"] = 12
        settings["ai"]["fabric_api_key"] = "fabric-key"
        settings["ai"]["nrp_api_key"] = "nrp-key"
        settings["ai"]["custom_providers"] = [{
            "name": "fabric",
            "base_url": "https://ai.fabric-testbed.net",
            "api_key": "provider-key",
            "endpoint_style": "chat",
        }]
        settings["ai"]["discovered_models"] = {"fabric": [{"id": "qwen3-coder-30b"}]}
        sm.save_settings(settings)

        sm.save_settings({"fabric": {"slice_policy": {"max_lease_hours": 6}}})
        sm.invalidate_settings_cache()
        raw = sm.load_settings()

        assert raw["fabric"]["bastion_username"] == "persisted-user"
        assert raw["fabric"]["project_id"] == "persisted-project"
        assert raw["fabric"]["slice_policy"]["max_lease_hours"] == 6
        assert raw["ai"]["fabric_api_key"] == "fabric-key"
        assert raw["ai"]["nrp_api_key"] == "nrp-key"
        assert raw["ai"]["custom_providers"][0]["api_key"] == "provider-key"
        assert raw["ai"]["discovered_models"]["fabric"][0]["id"] == "qwen3-coder-30b"

    def test_save_refuses_empty_manual_fabric_identity_overwrite(self, isolated_storage):
        settings = sm.load_settings()
        settings["fabric"]["bastion_username"] = "persisted-user"
        settings["fabric"]["project_id"] = "persisted-project"
        sm.save_settings(settings)

        sm.save_settings({"fabric": {"bastion_username": "", "project_id": ""}})
        sm.invalidate_settings_cache()
        raw = sm.load_settings()

        assert raw["fabric"]["bastion_username"] == "persisted-user"
        assert raw["fabric"]["project_id"] == "persisted-project"
        rc = (isolated_storage / "fabric_config" / "fabric_rc").read_text()
        ssh = (isolated_storage / "fabric_config" / "ssh_config").read_text()
        assert "FABRIC_BASTION_USERNAME=persisted-user" in rc
        assert "FABRIC_PROJECT_ID=persisted-project" in rc
        assert "    User persisted-user" in ssh


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

    def test_resolve_chameleon_key_name_uses_node_site_then_fallback(self, isolated_storage):
        settings = sm.load_settings()
        settings["chameleon"]["sites"]["CHI@TACC"]["default_key_name"] = "site-key"
        sm.save_settings(settings)
        sm.invalidate_settings_cache()

        assert sm.resolve_chameleon_key_name("CHI@TACC", {"key_name": "node-key"}) == "node-key"
        assert sm.resolve_chameleon_key_name("CHI@TACC", {}) == "site-key"
        assert sm.resolve_chameleon_key_name("CHI@UC", {}) == "loomai-key"

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

    def test_is_chameleon_site_configured_with_password_auth(self, isolated_storage):
        settings = sm.load_settings()
        settings["chameleon"]["password_auth"]["username"] = "user@example.org"
        settings["chameleon"]["password_auth"]["password"] = "secret"
        site = settings["chameleon"]["sites"]["CHI@UC"]
        site["auth_type"] = "password"
        site["project_id"] = "project-id"
        site["client_id"] = "keystone-uc-prod"
        sm.save_settings(settings)
        sm.invalidate_settings_cache()
        assert sm.is_chameleon_site_configured("CHI@UC") is True

    def test_inactive_chameleon_password_auth_does_not_replace_app_creds(self, isolated_storage):
        settings = sm.load_settings()
        site = settings["chameleon"]["sites"]["CHI@TACC"]
        site["auth_type"] = "application_credential"
        site["app_credential_id"] = "cred-id"
        site["app_credential_secret"] = "cred-secret"
        settings["chameleon"]["password_auth"]["username"] = "user@example.org"
        settings["chameleon"]["password_auth"]["password"] = ""
        site["project_id"] = "project-id"
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

    def test_ai_renci_key_uses_custom_provider_secret(self, isolated_storage):
        settings = sm.load_settings()
        settings["ai"]["fabric_api_key"] = "stale-fabric-key"
        settings["ai"]["custom_providers"] = [{
            "name": "ai-renci",
            "base_url": "https://ai-renci.example/v1",
            "api_key": "valid-ai-renci-key",
            "endpoint_style": "auto",
        }]

        sm.apply_env_vars(settings)
        sm.generate_fabric_rc(settings)

        assert os.environ.get("FABRIC_AI_API_KEY") == "stale-fabric-key"
        assert os.environ.get("LOOMAI_CUSTOM_PROVIDER_AI_RENCI_API_KEY") == "valid-ai-renci-key"
        assert os.environ.get("AI_RENCI_API_KEY") == "valid-ai-renci-key"
        with open(os.path.join(str(isolated_storage), "fabric_config", "fabric_rc")) as f:
            content = f.read()
        assert "export FABRIC_AI_API_KEY=stale-fabric-key" in content
        assert "export AI_RENCI_API_KEY=valid-ai-renci-key" in content

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
        assert tools["goose"] is True
        assert tools["crush"] is True
        assert tools["claude"] is True
        assert tools["deepagents"] is True

    def test_defaults_assistant_flags_on(self, isolated_storage):
        defaults = sm.get_default_settings()
        assistant = defaults["ai"]["assistant"]
        assert assistant["strict_fabric_query_contract"] is True
        assert assistant["final_answer_retry"] is True
        assert assistant["final_answer_retry_scope"] == "all"
        assert assistant["compact_fabric_resource_tools"] is True
        assert assistant["resource_query_generation_defaults"] is True
        assert assistant["resource_query_generation"] == {"default": {}, "models": {}}
        assert assistant["weak_model_context_management"] is False
        assert assistant["capability_profiles_enabled"] is True
        assert assistant["capability_profile_path"].endswith(
            "runs/model-capabilities/current/model_capabilities.json"
        )
        assert assistant["tool_loop"]["no_progress_limit"] == 3
        assert assistant["turn_budget"]["default"]["max_tokens"] == 0
        assert assistant["turn_budget"]["default"]["max_cost_usd"] == 0
        assert assistant["turn_budget"]["default"]["cost_per_1k_tokens_usd"] == 0

    def test_assistant_flags_can_be_explicitly_disabled(self, isolated_storage):
        settings = sm.load_settings()
        assistant = settings["ai"]["assistant"]
        assistant["strict_fabric_query_contract"] = False
        assistant["final_answer_retry"] = False
        assistant["compact_fabric_resource_tools"] = False
        assistant["resource_query_generation_defaults"] = False
        assistant["capability_profiles_enabled"] = False
        sm.save_settings(settings)

        assert sm.is_strict_fabric_query_contract_enabled() is False
        assert sm.is_final_answer_retry_enabled() is False
        assert sm.is_compact_fabric_resource_tools_enabled() is False
        assert sm.is_resource_query_generation_defaults_enabled() is False
        assert sm.is_capability_profiles_enabled() is False

        assistant["weak_model_context_management"] = True
        sm.save_settings(settings)
        assert sm.is_weak_model_context_management_enabled() is True

    def test_mcp_evidence_closure_hints_gating(self, isolated_storage):
        # Global flag off (default): disabled even for weak-profile models.
        assert sm.get_mcp_evidence_closure_hints_enabled("fabric:qwen3-coder-30b") is False

        settings = sm.load_settings()
        settings["ai"]["assistant"]["weak_model_context_management"] = True
        sm.save_settings(settings)

        # Flag on: weak-profile models opt in via capability profile.
        assert sm.get_mcp_evidence_closure_hints_enabled("fabric:qwen3-coder-30b") is True
        assert sm.get_mcp_evidence_closure_hints_enabled("nrp:qwen3") is True
        assert sm.get_mcp_evidence_closure_hints_enabled("nrp:minimax-m2") is True
        # Strong profiles and missing model keys stay off.
        assert sm.get_mcp_evidence_closure_hints_enabled("ai-renci:gpt-5.5") is False
        assert sm.get_mcp_evidence_closure_hints_enabled("") is False

    def test_assistant_turn_budget_resolves_provider_and_model_overrides(self, isolated_storage):
        settings = sm.load_settings()
        assistant = settings["ai"]["assistant"]
        assistant["turn_budget"] = {
            "default": {
                "max_tokens": 20000,
                "max_cost_usd": 0,
                "cost_per_1k_tokens_usd": 0,
            },
            "providers": {
                "fabric": {
                    "max_tokens": 40000,
                    "cost_per_1k_tokens_usd": 0.05,
                },
                "nrp": {
                    "max_tokens": 12000,
                },
            },
            "models": {
                "fabric:qwen3-coder-30b": {
                    "max_tokens": 80000,
                    "max_cost_usd": 2.5,
                },
            },
        }
        sm.save_settings(settings)

        fabric_budget = sm.get_assistant_turn_budget("fabric:qwen3-coder-30b")
        assert fabric_budget["max_tokens"] == 80000
        assert fabric_budget["max_cost_usd"] == 2.5
        assert fabric_budget["cost_per_1k_tokens_usd"] == 0.05

        nrp_budget = sm.get_assistant_turn_budget("nrp:glm-5")
        assert nrp_budget["max_tokens"] == 12000
        assert nrp_budget["max_cost_usd"] == 0

    def test_max_slice_lease_policy_default_six_hours(self, isolated_storage):
        defaults = sm.get_default_settings()
        assert defaults["fabric"]["slice_policy"]["max_lease_hours"] == 6
        assert sm.get_max_slice_lease_hours() == 6

        settings = sm.load_settings()
        settings["fabric"]["slice_policy"]["max_lease_hours"] = 4
        sm.save_settings(settings)

        assert sm.get_max_slice_lease_hours() == 4

    def test_resource_query_generation_defaults_model_override(self, isolated_storage):
        settings = sm.load_settings()
        assistant = settings["ai"]["assistant"]
        assistant["resource_query_generation"] = {
            "default": {
                "temperature": 0.1,
                "top_p": 0.95,
                "max_output_tokens": 4096,
            },
            "models": {
                "qwen3-coder-30b": {
                    "temperature": 0.0,
                    "max_output_tokens": 8192,
                    "reasoning_effort": "HIGH",
                },
            },
        }
        sm.save_settings(settings)

        defaults = sm.get_resource_query_generation_defaults("fabric:qwen3-coder-30b")

        assert defaults == {
            "temperature": 0.0,
            "top_p": 0.95,
            "max_output_tokens": 8192,
            "reasoning_effort": "high",
        }

    def test_model_capability_profile_loader(self, isolated_storage):
        profile_path = isolated_storage / "model_capabilities.json"
        profile_path.write_text(json.dumps({
            "schema_version": 1,
            "profiles": [{
                "model_key": "fabric:test-profile-model",
                "provider": "fabric",
                "capabilities": {
                    "endpoint_style": "responses",
                    "context_window_tokens": {"value": 65536, "source": "probe"},
                    "max_output_tokens": {"value": 8192, "source": "probe"},
                    "reasoning_model": {"supported": True, "source": "probe"},
                    "interaction_features": {
                        "tool_calling": {"supported": False, "source": "probe"},
                    },
                },
                "evaluation": {
                    "confidence": "high",
                    "status": "profiled",
                },
                "recommended_configuration": {
                    "config_id": "test-profile",
                    "context_window_tokens": 65536,
                    "max_input_tokens": 32768,
                    "max_output_tokens": 4096,
                    "temperature": 0.0,
                    "top_p": 0.9,
                    "reasoning_effort": "high",
                    "context_truncation_policy": "preserve current task",
                },
            }],
        }))
        settings = sm.load_settings()
        assistant = settings["ai"]["assistant"]
        assistant["capability_profiles_enabled"] = True
        assistant["capability_profile_path"] = str(profile_path)
        sm.save_settings(settings)

        profile = sm.get_model_capability_profile("test-profile-model")

        assert profile["model_key"] == "fabric:test-profile-model"
        assert profile["endpoint_style"] == "responses"
        assert profile["context_window_tokens"] == 65536
        assert profile["max_input_tokens"] == 32768
        assert profile["max_output_tokens"] == 4096
        assert profile["temperature"] == 0.0
        assert profile["top_p"] == 0.9
        assert profile["reasoning_effort"] == "high"
        assert profile["supports_tools"] is False
        assert profile["reasoning_model"] is True
        assert profile["config_id"] == "test-profile"

    def test_builtin_model_capability_profiles_are_default_fallback(self, isolated_storage):
        settings = sm.load_settings()
        assistant = settings["ai"]["assistant"]
        assistant["capability_profiles_enabled"] = True
        assistant["capability_profile_path"] = str(isolated_storage / "missing-capabilities.json")
        sm.save_settings(settings)
        sm.invalidate_settings_cache()

        qwen = sm.get_model_capability_profile("fabric:qwen3-coder-30b")
        assert qwen["context_window_tokens"] == 262144
        assert qwen["temperature"] == 0.3
        assert qwen["max_output_tokens"] == 32768
        assert qwen["weak_model_context_management"] is True
        assert qwen["context_compaction_enabled"] is True
        assert qwen["context_compaction_trigger_messages"] == 18

        nrp_qwen = sm.get_model_capability_profile("nrp:qwen3")
        assert nrp_qwen["context_window_tokens"] == 32768
        assert nrp_qwen["weak_model_context_management"] is True
        assert nrp_qwen["context_compaction_enabled"] is True
        assert nrp_qwen["context_compaction_trigger_tokens"] == 12000

        minimax = sm.get_model_capability_profile("nrp:minimax-m2")
        assert minimax["context_window_tokens"] == 131072
        assert minimax["weak_model_context_management"] is True
        assert minimax["context_compaction_enabled"] is True
        assert minimax["context_compaction_trigger_tokens"] == 16000

        gpt55 = sm.get_model_capability_profile("ai-renci:gpt-5.5")
        assert gpt55["endpoint_style"] == "responses"
        assert gpt55["reasoning_effort"] == "medium"
        assert gpt55["strip_temperature"] is True
        assert "weak_model_context_management" not in gpt55

    def test_known_model_ideal_overrides_runtime_profile_values(self, isolated_storage):
        profile_path = isolated_storage / "model_capabilities.json"
        profile_path.write_text(json.dumps({
            "schema_version": 1,
            "profiles": [
                {
                    "model_key": "qwen3-coder-30b",
                    "provider": "fabric",
                    "capabilities": {
                        "endpoint_style": "chat-completions",
                        "context_window_tokens": {"value": 32768, "source": "stale"},
                    },
                    "recommended_configuration": {
                        "context_window_tokens": 32768,
                        "max_output_tokens": 4096,
                        "temperature": 0.0,
                    },
                },
                {
                    "model_key": "gemma-4-27b",
                    "provider": "fabric",
                    "recommended_configuration": {
                        "context_window_tokens": 32768,
                        "max_input_tokens": 28672,
                    },
                },
            ],
        }))
        settings = sm.load_settings()
        assistant = settings["ai"]["assistant"]
        assistant["capability_profiles_enabled"] = True
        assistant["capability_profile_path"] = str(profile_path)
        sm.save_settings(settings)
        sm.invalidate_settings_cache()

        qwen = sm.get_model_capability_profile("fabric:qwen3-coder-30b")
        assert qwen["context_window_tokens"] == 262144
        assert qwen["max_input_tokens"] == 229376
        assert qwen["max_output_tokens"] == 32768
        assert qwen["temperature"] == 0.3
        assert qwen["weak_model_context_management"] is True
        assert qwen["context_compaction_enabled"] is True

        gemma = sm.get_model_capability_profile("fabric:gemma-4-27b")
        assert gemma["context_window_tokens"] == 262144
        assert gemma["max_input_tokens"] == 258048

    def test_model_capability_profile_excludes_nonbenchmarkable(self, isolated_storage):
        profile_path = isolated_storage / "model_capabilities.json"
        profile_path.write_text(json.dumps({
            "schema_version": 1,
            "profiles": [{
                "model_key": "nrp:qwen3-embedding",
                "provider": "nrp",
                "benchmarkable": False,
                "capabilities": {
                    "endpoint_style": "non-chat",
                },
                "recommended_configuration": {
                    "max_output_tokens": 1024,
                },
            }],
        }))
        settings = sm.load_settings()
        assistant = settings["ai"]["assistant"]
        assistant["capability_profiles_enabled"] = True
        assistant["capability_profile_path"] = str(profile_path)
        sm.save_settings(settings)

        assert sm.get_model_capability_profile("nrp:qwen3-embedding") == {}

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


class TestConfigPathsIgnoreStaleStoredPaths:
    """Config-derived paths must come from the live root ``fabric_config``
    symlink, not the per-user absolute paths frozen in settings.json — those
    go stale across user switches and the users/ -> .loomai/users/ relocation
    (regression: SSH terminal used a stale ``work/users/<uuid>/...`` bastion key).
    """

    def _save_stale(self, storage):
        settings = sm.load_settings()
        stale = "/home/fabric/work/users/deadbeef/fabric_config"
        settings["paths"]["config_dir"] = stale
        settings["paths"]["bastion_key_file"] = os.path.join(stale, "fabric_bastion_key")
        settings["paths"]["token_file"] = os.path.join(stale, "id_token.json")
        settings["paths"]["ssh_config_file"] = os.path.join(stale, "ssh_config")
        settings["paths"]["slice_keys_dir"] = os.path.join(stale, "slice_keys")
        sm.save_settings(settings)
        return str(storage / "fabric_config")

    def test_getters_ignore_stale_stored_config_paths(self, isolated_storage):
        live = self._save_stale(isolated_storage)
        assert sm.get_config_dir() == live
        assert sm.get_bastion_key_path() == os.path.join(live, "fabric_bastion_key")
        assert sm.get_ssh_config_path() == os.path.join(live, "ssh_config")
        assert sm.get_slice_keys_dir() == os.path.join(live, "slice_keys")
        # No stale "users/deadbeef" leaks through any config path.
        for p in (sm.get_config_dir(), sm.get_bastion_key_path(),
                  sm.get_ssh_config_path(), sm.get_slice_keys_dir()):
            assert "users/deadbeef" not in p

    def test_apply_env_vars_uses_live_config_paths(self, isolated_storage):
        live = self._save_stale(isolated_storage)
        sm.apply_env_vars(sm.load_settings())
        assert os.environ["FABRIC_CONFIG_DIR"] == live
        assert os.environ["FABRIC_BASTION_KEY_LOCATION"] == os.path.join(live, "fabric_bastion_key")
        assert os.environ["FABRIC_TOKEN_LOCATION"] == os.path.join(live, "id_token.json")
        assert "users/deadbeef" not in os.environ["FABRIC_BASTION_KEY_LOCATION"]

    def test_generated_fabric_rc_has_live_bastion_key(self, isolated_storage):
        live = self._save_stale(isolated_storage)
        sm.generate_fabric_rc(sm.load_settings())
        rc = (isolated_storage / "fabric_config" / "fabric_rc").read_text()
        assert f"FABRIC_BASTION_KEY_LOCATION={os.path.join(live, 'fabric_bastion_key')}" in rc
        assert "users/deadbeef" not in rc

    def test_generated_ssh_config_has_live_bastion_key(self, isolated_storage):
        live = self._save_stale(isolated_storage)
        sm.generate_ssh_config(sm.load_settings())
        cfg = (isolated_storage / "fabric_config" / "ssh_config").read_text()
        assert os.path.join(live, "fabric_bastion_key") in cfg
        assert "users/deadbeef" not in cfg
