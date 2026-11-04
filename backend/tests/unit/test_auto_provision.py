"""Startup account provisioning.

On the hosted hub the token, project and bastion login are injected at spawn,
so the bastion key, slice keys and FABRIC LLM key are the only things left
before a new user can build a slice. These cover the gap detection and the
project resolution that decide whether the startup task does anything.
"""

import os
from unittest.mock import patch

import pytest

from app.routes import config as config_routes


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    d = tmp_path / "fabric_config"
    d.mkdir()
    monkeypatch.setattr(config_routes, "_ensure_config_dir", lambda: str(d))
    return d


def _write_slice_keys(config_dir):
    priv, pub = config_routes.get_default_slice_key_path(str(config_dir))
    os.makedirs(os.path.dirname(priv), exist_ok=True)
    for p in (priv, pub):
        with open(p, "w") as f:
            f.write("key")


class TestProvisioningGaps:
    def test_reports_every_artifact_missing_on_a_fresh_container(self, config_dir):
        with patch("app.settings_manager.get_fabric_api_key", return_value=""):
            assert config_routes.provisioning_gaps() == [
                "bastion_key", "slice_keys", "llm_key",
            ]

    def test_empty_when_everything_already_exists(self, config_dir):
        (config_dir / "fabric_bastion_key").write_text("key")
        _write_slice_keys(config_dir)
        with patch("app.settings_manager.get_fabric_api_key", return_value="sk-abc"):
            assert config_routes.provisioning_gaps() == []

    def test_llm_key_alone_is_a_gap(self, config_dir):
        """A user with keys but no LLM key must still get one — otherwise
        model discovery finds no API key and the assistant is dead on arrival."""
        (config_dir / "fabric_bastion_key").write_text("key")
        _write_slice_keys(config_dir)
        with patch("app.settings_manager.get_fabric_api_key", return_value=""):
            assert config_routes.provisioning_gaps() == ["llm_key"]

    def test_half_written_slice_keypair_counts_as_missing(self, config_dir):
        """Private key without its .pub must not read as provisioned."""
        (config_dir / "fabric_bastion_key").write_text("key")
        priv, _pub = config_routes.get_default_slice_key_path(str(config_dir))
        os.makedirs(os.path.dirname(priv), exist_ok=True)
        with open(priv, "w") as f:
            f.write("key")
        with patch("app.settings_manager.get_fabric_api_key", return_value="sk-abc"):
            assert config_routes.provisioning_gaps() == ["slice_keys"]


class TestResolveProvisioningProject:
    def test_prefers_settings_over_injected_env(self, monkeypatch):
        """A user who switched project must not be pulled back to the
        hub-injected one on the next container start."""
        monkeypatch.setenv("FABRIC_PROJECT_ID", "env-project")
        with patch("app.settings_manager.load_settings",
                   return_value={"fabric": {"project_id": "chosen-project"}}):
            assert config_routes.resolve_provisioning_project() == "chosen-project"

    def test_falls_back_to_hub_injected_env(self, monkeypatch):
        monkeypatch.setenv("FABRIC_PROJECT_ID", "env-project")
        with patch("app.settings_manager.load_settings",
                   return_value={"fabric": {"project_id": ""}}):
            assert config_routes.resolve_provisioning_project() == "env-project"

    def test_empty_when_nothing_is_known(self, monkeypatch):
        monkeypatch.delenv("FABRIC_PROJECT_ID", raising=False)
        with patch("app.settings_manager.load_settings", return_value={"fabric": {}}):
            assert config_routes.resolve_provisioning_project() == ""

    def test_survives_unreadable_settings(self, monkeypatch):
        monkeypatch.setenv("FABRIC_PROJECT_ID", "env-project")
        with patch("app.settings_manager.load_settings", side_effect=OSError("boom")):
            assert config_routes.resolve_provisioning_project() == "env-project"


class TestAutoSetupUnavailable:
    def test_is_not_an_http_exception(self):
        """The startup task must be able to retry on "no token yet" rather
        than translate a web error."""
        from fastapi import HTTPException
        assert issubclass(config_routes.AutoSetupUnavailable, RuntimeError)
        assert not issubclass(config_routes.AutoSetupUnavailable, HTTPException)

    @pytest.mark.asyncio
    async def test_run_auto_setup_raises_it_without_a_token(self):
        with patch.object(config_routes, "_read_token", return_value=None):
            with pytest.raises(config_routes.AutoSetupUnavailable):
                await config_routes.run_auto_setup("some-project")

    @pytest.mark.asyncio
    async def test_route_translates_it_to_http_400(self):
        from fastapi import HTTPException
        with patch.object(config_routes, "_read_token", return_value=None):
            with pytest.raises(HTTPException) as exc:
                await config_routes.auto_setup(
                    config_routes.AutoSetupRequest(project_id="p"))
        assert exc.value.status_code == 400


class TestExistingPrivateKeyIsNeverOverwritten:
    """A slice private key may already be authorized on running VMs.

    Regenerating it silently locks the user out of their own live slices with
    no way back, so a missing .pub must be rederived from the private key
    rather than triggering a fresh keypair.
    """

    @pytest.mark.asyncio
    async def test_missing_pub_is_derived_not_regenerated(self, config_dir, monkeypatch):
        import paramiko
        from app.routes import config as cfg

        priv_path, pub_path = cfg.get_default_slice_key_path(str(config_dir))
        os.makedirs(os.path.dirname(priv_path), exist_ok=True)

        original = paramiko.RSAKey.generate(2048)
        original.write_private_key_file(priv_path)
        original_bytes = open(priv_path, "rb").read()
        assert not os.path.isfile(pub_path)

        # Only the slice-key stretch matters here; stub the rest of auto-setup.
        (config_dir / "fabric_bastion_key").write_text("key")
        monkeypatch.setattr(cfg, "_read_token",
                            lambda: {"id_token": "t", "refresh_token": "r"})
        monkeypatch.setattr(cfg, "_decode_jwt_payload",
                            lambda _t: {"email": "u@example.org", "uuid": "u-1"})
        monkeypatch.setattr(cfg, "reset_fablib", lambda: None)
        monkeypatch.setattr(cfg, "get_fablib", lambda: (_ for _ in ()).throw(RuntimeError("no fablib")))
        monkeypatch.setattr(cfg, "_invalidate_tracking_cache", lambda: None)
        monkeypatch.setenv("FABRIC_BASTION_LOGIN", "bastion-user")
        with patch("app.settings_manager.load_settings",
                   return_value={"fabric": {}, "ai": {}}), \
             patch("app.settings_manager.save_settings"), \
             patch("app.settings_manager.apply_env_vars"), \
             patch("app.settings_manager.get_fabric_api_key", return_value="sk-present"):
            result = await cfg.run_auto_setup("project-1")

        assert open(priv_path, "rb").read() == original_bytes, \
            "auto-setup overwrote an existing slice private key"
        assert result["slice_keys_generated"] is False, \
            "deriving a missing .pub must not be reported as a new keypair"
        assert os.path.isfile(pub_path)
        derived = open(pub_path).read().split()[1]
        assert derived == original.get_base64(), \
            ".pub must be derived from the existing private key"

    def test_unreadable_private_key_is_left_alone(self, config_dir):
        """A passphrase-protected or corrupt key must not be replaced."""
        from app.routes import config as cfg
        priv_path, _pub = cfg.get_default_slice_key_path(str(config_dir))
        os.makedirs(os.path.dirname(priv_path), exist_ok=True)
        with open(priv_path, "w") as f:
            f.write("-----BEGIN OPENSSH PRIVATE KEY-----\nnot-parseable\n")
        assert cfg._load_any_private_key(priv_path) is None

    def test_loader_reads_an_rsa_key(self, tmp_path):
        import paramiko
        from app.routes import config as cfg
        p = tmp_path / "id_rsa"
        key = paramiko.RSAKey.generate(2048)
        key.write_private_key_file(str(p))
        loaded = cfg._load_any_private_key(str(p))
        assert loaded is not None and loaded.get_base64() == key.get_base64()
