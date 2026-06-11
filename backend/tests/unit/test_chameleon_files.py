"""Unit tests for Chameleon file path safety helpers."""

import pytest
from fastapi import HTTPException

from app.routes.chameleon_files import (
    _join_remote_under,
    _normalize_remote_path,
    _safe_upload_relative_path,
)


def test_safe_upload_relative_path_preserves_nested_path():
    assert _safe_upload_relative_path("folder/sub/file.txt") == "folder/sub/file.txt"


@pytest.mark.parametrize("name", ["../secret.txt", "/etc/passwd", "folder/../secret.txt", "C:/secret.txt", ""])
def test_safe_upload_relative_path_rejects_unsafe_names(name):
    with pytest.raises(HTTPException):
        _safe_upload_relative_path(name)


def test_join_remote_under_keeps_upload_inside_destination():
    assert _join_remote_under("/home/cc/uploads", "folder/file.txt") == "/home/cc/uploads/folder/file.txt"


def test_normalize_remote_path_rejects_parent_traversal():
    with pytest.raises(HTTPException):
        _normalize_remote_path("/home/cc/../root")
