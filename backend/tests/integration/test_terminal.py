"""Tests for terminal REST/WebSocket endpoints.

The terminal module (app/routes/terminal.py) exposes only WebSocket endpoints:
  - /ws/terminal/{slice_name}/{node_name} — SSH terminal to a FABRIC VM
  - /ws/terminal/container — Local PTY shell
  - /ws/logs — Stream FABlib log file

These are all WebSocket endpoints which are harder to test with the synchronous
TestClient. We include basic unit-level tests for helper functions instead.
"""

import os
from unittest.mock import patch, MagicMock


class TestSSHConfigHelper:
    """Test the _get_ssh_config helper function."""

    def test_get_ssh_config_returns_expected_keys(self, mock_fablib, storage_dir):
        from app.routes.terminal import _get_ssh_config

        # Create a bastion key file
        config_dir = storage_dir / "fabric_config"
        bastion_key = config_dir / "fabric_bastion_key"
        bastion_key.write_text("fake-bastion-key")

        mock_fablib.get_bastion_username = MagicMock(return_value="testuser")

        # Must also patch get_fablib where terminal.py imports it
        with patch("app.routes.terminal.get_fablib", return_value=mock_fablib), \
             patch.dict(os.environ, {
                 "FABRIC_CONFIG_DIR": str(config_dir),
                 "FABRIC_BASTION_HOST": "bastion.test.net",
             }):
            config = _get_ssh_config()

        assert "bastion_host" in config
        assert "bastion_username" in config
        assert "bastion_key" in config
        assert "slice_key" in config
        assert config["bastion_host"] == "bastion.test.net"
        assert config["bastion_username"] == "testuser"

    def test_get_ssh_config_uses_default_slice_key(self, mock_fablib, storage_dir):
        from app.routes.terminal import _get_ssh_config

        config_dir = storage_dir / "fabric_config"
        bastion_key = config_dir / "fabric_bastion_key"
        bastion_key.write_text("fake-bastion-key")

        # The default slice key is already created by the storage_dir fixture
        mock_fablib.get_bastion_username = MagicMock(return_value="user")

        with patch("app.routes.terminal.get_fablib", return_value=mock_fablib), \
             patch.dict(os.environ, {
                 "FABRIC_CONFIG_DIR": str(config_dir),
             }):
            config = _get_ssh_config()

        # Should use the default key from slice_keys/default/
        assert "slice_key" in config
        assert "slice_key" in config["slice_key"]  # path contains "slice_key"

    def test_get_ssh_config_with_per_slice_key(self, mock_fablib, storage_dir):
        from app.routes.terminal import _get_ssh_config

        config_dir = storage_dir / "fabric_config"
        bastion_key = config_dir / "fabric_bastion_key"
        bastion_key.write_text("fake-bastion-key")

        # Create a per-slice key assignment
        slice_keys_dir = storage_dir / ".slice-keys"
        slice_keys_dir.mkdir(parents=True, exist_ok=True)
        import json
        (slice_keys_dir / "my-slice.json").write_text(json.dumps({
            "slice_key_id": "default",
        }))

        mock_fablib.get_bastion_username = MagicMock(return_value="user")

        with patch("app.routes.terminal.get_fablib", return_value=mock_fablib), \
             patch.dict(os.environ, {
                 "FABRIC_CONFIG_DIR": str(config_dir),
             }):
            config = _get_ssh_config(slice_name="my-slice")

        assert "slice_key" in config


class TestLoadPrivateKey:
    """Test the _load_private_key helper — verifies error handling."""

    def test_load_missing_key_raises(self):
        from app.routes.terminal import _load_private_key
        import paramiko

        try:
            _load_private_key("/nonexistent/path/key")
            assert False, "Should have raised"
        except paramiko.SSHException as e:
            assert "Cannot load key" in str(e)


# TODO: WebSocket tests for /ws/terminal/{slice_name}/{node_name}
#   - Would need async WebSocket test client (e.g., httpx with websockets)
#   - Would mock paramiko SSH connections end-to-end

# TODO: WebSocket tests for /ws/terminal/container
#   - Would need async WebSocket test client
#   - Would test PTY creation and input/output relay

# TODO: WebSocket tests for /ws/logs
#   - Would need async WebSocket test client
#   - Would test log file tail streaming
