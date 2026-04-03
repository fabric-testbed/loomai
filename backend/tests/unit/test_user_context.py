"""Tests for app.user_context — storage paths, token resolution, callbacks."""

import os
from unittest.mock import patch, MagicMock

import pytest


class TestBaseStorage:
    def test_base_storage_uses_env_var(self, storage_dir):
        """_base_storage() should read from FABRIC_STORAGE_DIR."""
        import app.user_context as uc
        uc._BASE_STORAGE = None  # force re-read
        result = uc._base_storage()
        assert result == str(storage_dir)

    def test_base_storage_is_cached(self, storage_dir):
        """_base_storage() should cache the result after first call."""
        import app.user_context as uc
        uc._BASE_STORAGE = None
        first = uc._base_storage()
        # Set it to something else and verify it returns cached value
        second = uc._base_storage()
        assert first == second
        assert uc._BASE_STORAGE is not None

    def test_invalidate_base_storage(self, storage_dir):
        """_invalidate_base_storage() should clear the cached path."""
        import app.user_context as uc
        uc._BASE_STORAGE = "/some/cached/path"
        uc._invalidate_base_storage()
        assert uc._BASE_STORAGE is None


class TestGetTokenPath:
    def test_returns_string_path(self, storage_dir):
        """get_token_path() should return a string file path."""
        from app.user_context import get_token_path
        result = get_token_path()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_env_token_path(self, storage_dir):
        """get_token_path() should use FABRIC_TOKEN_FILE env var if set."""
        from app.user_context import get_token_path
        expected = str(storage_dir / "fabric_config" / "id_token.json")
        result = get_token_path()
        assert result == expected


class TestGetUserStorage:
    def test_returns_storage_dir(self, storage_dir):
        """get_user_storage() should return the storage directory in single-user mode."""
        from app.user_context import get_user_storage
        with patch("app.user_registry.get_user_storage_dir", return_value=None):
            result = get_user_storage()
        assert os.path.isdir(result)
        assert result == str(storage_dir)

    def test_creates_directory_if_missing(self, storage_dir):
        """get_user_storage() should create the directory if it doesn't exist."""
        import app.user_context as uc
        uc._BASE_STORAGE = None

        new_dir = str(storage_dir / "new_user_dir")
        with patch("app.user_registry.get_user_storage_dir", return_value=new_dir):
            result = uc.get_user_storage()
        assert os.path.isdir(new_dir)
        assert result == new_dir

    def test_multi_user_mode(self, storage_dir):
        """get_user_storage() should return per-user dir in multi-user mode."""
        user_dir = str(storage_dir / "users" / "user-uuid-123")
        with patch("app.user_registry.get_user_storage_dir", return_value=user_dir):
            from app.user_context import get_user_storage
            result = get_user_storage()
        assert result == user_dir
        assert os.path.isdir(user_dir)


class TestGetArtifactsDir:
    def test_returns_string_path(self, storage_dir):
        """get_artifacts_dir() should return a string path."""
        from app.user_context import get_artifacts_dir
        result = get_artifacts_dir()
        assert isinstance(result, str)
        assert "my_artifacts" in result


class TestGetSlicesDir:
    def test_returns_string_path(self, storage_dir):
        """get_slices_dir() should return a string path."""
        from app.user_context import get_slices_dir
        result = get_slices_dir()
        assert isinstance(result, str)
        assert "my_slices" in result


class TestUserChangedCallbacks:
    def test_register_and_notify(self, storage_dir):
        """register_user_changed_callback() + notify_user_changed() should call callbacks."""
        import app.user_context as uc

        called = []
        def my_callback():
            called.append(True)

        uc.register_user_changed_callback(my_callback)
        try:
            uc.notify_user_changed()
            assert len(called) == 1
        finally:
            # Clean up the callback
            uc._on_user_changed_callbacks.remove(my_callback)

    def test_notify_clears_base_storage(self, storage_dir):
        """notify_user_changed() should invalidate the cached base storage."""
        import app.user_context as uc
        uc._BASE_STORAGE = "/old/path"
        uc.notify_user_changed()
        assert uc._BASE_STORAGE is None

    def test_callback_error_does_not_propagate(self, storage_dir):
        """notify_user_changed() should catch callback exceptions."""
        import app.user_context as uc

        def bad_callback():
            raise ValueError("callback error")

        uc.register_user_changed_callback(bad_callback)
        try:
            # Should not raise
            uc.notify_user_changed()
        finally:
            uc._on_user_changed_callbacks.remove(bad_callback)
