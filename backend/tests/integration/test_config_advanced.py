"""Tests for config endpoints: settings test, save settings, key generation, token, login URL."""

import json
import os
import time
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


# ===========================================================================
# POST /api/settings/test/token — token validation
# ===========================================================================

class TestSettingsTestToken:
    def test_token_valid(self, client, storage_dir):
        """Valid token file should pass the test."""
        import base64
        # Create a fake JWT with future expiration
        header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b'=').decode()
        payload_data = {"exp": int(time.time()) + 3600, "uuid": "test-uuid", "name": "Test User"}
        payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b'=').decode()
        sig = base64.urlsafe_b64encode(b'fakesig').rstrip(b'=').decode()
        fake_jwt = f"{header}.{payload}.{sig}"

        token_path = os.path.join(str(storage_dir), "fabric_config", "id_token.json")
        with open(token_path, "w") as f:
            json.dump({"id_token": fake_jwt}, f)

        resp = client.post("/api/settings/test/token")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "expires_at" in data

    def test_token_missing(self, client, storage_dir):
        """Missing token file should fail."""
        # Remove the token file
        token_path = os.path.join(str(storage_dir), "fabric_config", "id_token.json")
        if os.path.exists(token_path):
            os.remove(token_path)
        # Also unset env var so _token_path() falls back
        with patch.dict(os.environ, {"FABRIC_TOKEN_FILE": "/nonexistent/token.json"}):
            resp = client.post("/api/settings/test/token")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False

    def test_token_expired(self, client, storage_dir):
        """Expired token should fail."""
        import base64
        header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b'=').decode()
        payload_data = {"exp": int(time.time()) - 3600}  # 1 hour ago
        payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b'=').decode()
        sig = base64.urlsafe_b64encode(b'fakesig').rstrip(b'=').decode()
        fake_jwt = f"{header}.{payload}.{sig}"

        token_path = os.path.join(str(storage_dir), "fabric_config", "id_token.json")
        with open(token_path, "w") as f:
            json.dump({"id_token": fake_jwt}, f)

        resp = client.post("/api/settings/test/token")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "expired" in data["message"].lower()


# ===========================================================================
# POST /api/settings/test/bastion_ssh — SSH check (mock paramiko)
# ===========================================================================

class TestSettingsTestBastionSSH:
    def test_bastion_ssh_no_username(self, client, storage_dir):
        """Missing bastion username should fail gracefully."""
        # Ensure settings have no bastion_username
        from app import settings_manager
        settings = settings_manager.load_settings()
        settings["fabric"]["bastion_username"] = ""
        settings_manager.save_settings(settings)

        resp = client.post("/api/settings/test/bastion_ssh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "username" in data["message"].lower() or "not configured" in data["message"].lower()

    def test_bastion_ssh_no_key_file(self, client, storage_dir):
        """Missing bastion key file should fail."""
        from app import settings_manager
        settings = settings_manager.load_settings()
        settings["fabric"]["bastion_username"] = "testuser"
        settings["paths"]["bastion_key_file"] = "/nonexistent/key"
        settings_manager.save_settings(settings)

        resp = client.post("/api/settings/test/bastion_ssh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "key" in data["message"].lower() or "not found" in data["message"].lower()

    def test_bastion_ssh_connection_success(self, client, storage_dir):
        """Successful SSH connection should return ok=True."""
        from app import settings_manager

        # Set up settings with valid-looking config
        bastion_key = os.path.join(str(storage_dir), "fabric_config", "fabric_bastion_key")
        with open(bastion_key, "w") as f:
            f.write("fake-key")

        settings = settings_manager.load_settings()
        settings["fabric"]["bastion_username"] = "testuser"
        settings["paths"]["bastion_key_file"] = bastion_key
        settings_manager.save_settings(settings)

        # Mock paramiko to succeed
        mock_client = MagicMock()
        with patch("app.routes.config.paramiko.SSHClient", return_value=mock_client):
            resp = client.post("/api/settings/test/bastion_ssh")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "latency_ms" in data


# ===========================================================================
# POST /api/settings/test/fablib — FABlib check
# ===========================================================================

class TestSettingsTestFablib:
    def test_fablib_configured(self, client):
        """When FABlib is configured and get_fablib() works, ok=True."""
        resp = client.post("/api/settings/test/fablib")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_fablib_not_configured(self, client):
        """When is_configured() returns False, ok=False."""
        with patch("app.routes.config.is_configured", return_value=False):
            resp = client.post("/api/settings/test/fablib")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False


# ===========================================================================
# POST /api/settings/test/ai_server — AI server ping (mock httpx)
# ===========================================================================

class TestSettingsTestAIServer:
    def test_ai_server_reachable(self, client):
        """Mock a successful /v1/models response."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "model-1"}, {"id": "model-2"}]}

        mock_get = AsyncMock(return_value=mock_resp)
        with patch("app.routes.config.fabric_client") as mock_client:
            mock_client.get = mock_get
            resp = client.post("/api/settings/test/ai_server")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["model_count"] == 2

    def test_ai_server_unreachable(self, client):
        """Mock a connection error."""
        import httpx
        mock_get = AsyncMock(side_effect=httpx.ConnectError("no network"))
        with patch("app.routes.config.fabric_client") as mock_client:
            mock_client.get = mock_get
            resp = client.post("/api/settings/test/ai_server")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False

    def test_ai_server_no_url(self, client):
        """Empty AI server URL should fail."""
        with patch("app.settings_manager.get_ai_server_url", return_value=""):
            resp = client.post("/api/settings/test/ai_server")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False


# ===========================================================================
# POST /api/settings/test/project — project validation (mock UIS)
# ===========================================================================

class TestSettingsTestProject:
    def test_project_valid(self, client, storage_dir):
        """Mock a successful project lookup."""
        import base64
        # Create a valid JWT
        header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b'=').decode()
        payload_data = {"exp": int(time.time()) + 3600, "uuid": "user-uuid"}
        payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b'=').decode()
        sig = base64.urlsafe_b64encode(b'fakesig').rstrip(b'=').decode()
        fake_jwt = f"{header}.{payload}.{sig}"

        token_path = os.path.join(str(storage_dir), "fabric_config", "id_token.json")
        with open(token_path, "w") as f:
            json.dump({"id_token": fake_jwt}, f)

        # Set project_id in settings
        from app import settings_manager
        settings = settings_manager.load_settings()
        settings["fabric"]["project_id"] = "proj-123"
        settings_manager.save_settings(settings)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"results": [{"name": "My Project", "uuid": "proj-123"}]}

        mock_get = AsyncMock(return_value=mock_resp)
        with patch("app.routes.config.fabric_client") as mock_client:
            mock_client.get = mock_get
            resp = client.post("/api/settings/test/project")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["project_name"] == "My Project"

    def test_project_not_configured(self, client, storage_dir):
        """No project_id should fail."""
        from app import settings_manager
        settings = settings_manager.load_settings()
        settings["fabric"]["project_id"] = ""
        settings_manager.save_settings(settings)

        resp = client.post("/api/settings/test/project")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False


# ===========================================================================
# POST /api/settings/test-all — run all checks
# ===========================================================================

class TestSettingsTestAll:
    def test_all_returns_all_keys(self, client):
        """test-all should return a result for each registered test."""
        # Mock external calls so they don't fail on network
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": [], "results": []}

        mock_get = AsyncMock(return_value=mock_resp)
        with patch("app.routes.config.fabric_client") as mock_client:
            mock_client.get = mock_get
            resp = client.post("/api/settings/test-all")

        assert resp.status_code == 200
        data = resp.json()
        # Should have entries for each registered test
        expected_keys = {"token", "bastion_ssh", "fablib", "ai_server", "nrp_server", "project"}
        assert expected_keys.issubset(set(data.keys()))
        # Each entry should have at least "ok" and "message"
        for key in expected_keys:
            assert "ok" in data[key] or "message" in data[key]

    def test_unknown_setting_returns_404(self, client):
        """A non-existent setting name should return 404."""
        resp = client.post("/api/settings/test/nonexistent_setting")
        assert resp.status_code == 404


# ===========================================================================
# PUT /api/settings — save settings
# ===========================================================================

class TestPutSettings:
    def test_save_and_reload(self, client, storage_dir):
        """Save settings and verify they're returned."""
        from app import settings_manager
        settings = settings_manager.load_settings()
        settings["fabric"]["project_id"] = "new-project-id"

        resp = client.put("/api/settings", json=settings)
        assert resp.status_code == 200
        data = resp.json()
        assert data["fabric"]["project_id"] == "new-project-id"

    def test_save_updates_env(self, client, storage_dir):
        """Saving settings should propagate to env vars."""
        from app import settings_manager
        settings = settings_manager.load_settings()
        settings["fabric"]["project_id"] = "env-test-pid"

        resp = client.put("/api/settings", json=settings)
        assert resp.status_code == 200
        # The env var should be updated
        assert os.environ.get("FABRIC_PROJECT_ID") == "env-test-pid"


# ===========================================================================
# POST /api/config/keys/generate — key generation
# ===========================================================================

class TestGenerateKeys:
    def test_generate_default_keys(self, client, storage_dir):
        """Generate slice keys in the default key set."""
        resp = client.post("/api/config/keys/slice/generate?key_name=test-keyset")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "public_key" in data
        assert "ssh-rsa" in data["public_key"]

    def test_generate_creates_files(self, client, storage_dir):
        """Generated keys should exist on disk."""
        resp = client.post("/api/config/keys/slice/generate?key_name=disk-check")
        assert resp.status_code == 200
        keys_dir = os.path.join(str(storage_dir), "fabric_config", "slice_keys", "disk-check")
        assert os.path.isfile(os.path.join(keys_dir, "slice_key"))
        assert os.path.isfile(os.path.join(keys_dir, "slice_key.pub"))


# ===========================================================================
# POST /api/config/token — token upload
# ===========================================================================

class TestTokenUpload:
    def test_upload_valid_token(self, client, storage_dir):
        """Upload a valid token JSON file."""
        import io
        token_data = json.dumps({"id_token": "fake.jwt.token"})
        # Use files parameter for file upload
        resp = client.post(
            "/api/config/token",
            files={"file": ("id_token.json", io.BytesIO(token_data.encode()), "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_upload_invalid_json(self, client, storage_dir):
        """Upload non-JSON should fail."""
        import io
        resp = client.post(
            "/api/config/token",
            files={"file": ("bad.json", io.BytesIO(b"not json"), "application/json")},
        )
        assert resp.status_code == 400

    def test_upload_missing_id_token(self, client, storage_dir):
        """Upload JSON without id_token field should fail."""
        import io
        token_data = json.dumps({"refresh_token": "only-refresh"})
        resp = client.post(
            "/api/config/token",
            files={"file": ("token.json", io.BytesIO(token_data.encode()), "application/json")},
        )
        assert resp.status_code == 400


# ===========================================================================
# GET /api/config/login-url
# ===========================================================================

class TestGetLoginUrl:
    def test_login_url_contains_cm(self, client):
        resp = client.get("/api/config/login")
        assert resp.status_code == 200
        data = resp.json()
        assert "login_url" in data
        assert "cm.fabric-testbed.net" in data["login_url"]

    def test_login_url_includes_project_id(self, client):
        """When FABRIC_PROJECT_ID is set, the URL should include it."""
        resp = client.get("/api/config/login")
        data = resp.json()
        assert "project_id" in data["login_url"]
