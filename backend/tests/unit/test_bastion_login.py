"""Tests that bastion_login is always fetched from UIS API, never derived from JWT.

Validates that oauth_callback, get_projects, and auto_setup all call
_fetch_uis_person for bastion_login and never construct it from email+sub.
"""

import ast
import inspect
import os
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Static analysis: ensure no JWT-based bastion_username construction exists
# ---------------------------------------------------------------------------

def _read_config_source() -> str:
    """Read the raw source of config.py."""
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "routes", "config.py"
    )
    with open(config_path) as f:
        return f.read()


class TestNoBastionJWTDerivation:
    """Ensure the codebase never builds bastion_login from email+sub JWT fields."""

    def test_no_cilogon_id_construction(self):
        """config.py must not contain cilogon_id-based bastion_login derivation."""
        source = _read_config_source()
        assert "cilogon_id" not in source, (
            "Found 'cilogon_id' in config.py — bastion_login must come from UIS API, "
            "not be derived from JWT email+sub"
        )

    def test_no_email_split_replace_pattern(self):
        """config.py must not derive username from email.split('@')[0].replace('.', '_')."""
        source = _read_config_source()
        # This pattern was the old JWT fallback
        assert 'split("@")[0].replace(".", "_")' not in source, (
            "Found email-to-username derivation in config.py — "
            "bastion_login must come from UIS API"
        )
        assert "split('@')[0].replace('.', '_')" not in source, (
            "Found email-to-username derivation in config.py — "
            "bastion_login must come from UIS API"
        )

    def test_no_zfill_bastion_pattern(self):
        """config.py must not use zfill to zero-pad a CILogon ID for bastion_login."""
        source = _read_config_source()
        assert "zfill" not in source, (
            "Found 'zfill' in config.py — this was part of the old JWT-based "
            "bastion_login derivation and should be removed"
        )


# ---------------------------------------------------------------------------
# Verify each endpoint fetches bastion_login from UIS
# ---------------------------------------------------------------------------

class TestBastionLoginFromUIS:
    """Verify that all bastion_login resolution paths call _fetch_uis_person."""

    def _get_function_source(self, func_name: str) -> str:
        """Extract source of a function from config.py by name."""
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "app", "routes", "config.py"
        )
        with open(config_path) as f:
            source = f.read()

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == func_name:
                    lines = source.splitlines()
                    return "\n".join(lines[node.lineno - 1 : node.end_lineno])
        raise ValueError(f"Function {func_name!r} not found in config.py")

    def test_oauth_callback_uses_uis(self):
        """_process_oauth_callback must call _fetch_uis_person for bastion_login."""
        source = self._get_function_source("_process_oauth_callback")
        assert "_fetch_uis_person" in source, (
            "_process_oauth_callback does not call _fetch_uis_person — "
            "bastion_login must be fetched from UIS API"
        )

    def test_get_projects_uses_uis(self):
        """get_projects must call _fetch_uis_person for bastion_login."""
        source = self._get_function_source("get_projects")
        assert "_fetch_uis_person" in source, (
            "get_projects does not call _fetch_uis_person — "
            "bastion_login must be fetched from UIS API"
        )

    def test_auto_setup_uses_uis(self):
        """auto_setup must call _fetch_uis_person for bastion_login."""
        source = self._get_function_source("auto_setup")
        assert "_fetch_uis_person" in source, (
            "auto_setup does not call _fetch_uis_person — "
            "bastion_login must be fetched from UIS API"
        )

    def test_no_jwt_fallback_in_get_projects(self):
        """get_projects must NOT have a JWT fallback for bastion_login."""
        source = self._get_function_source("get_projects")
        assert "cilogon_id" not in source
        assert "zfill" not in source

    def test_no_jwt_fallback_in_auto_setup(self):
        """auto_setup must NOT have a JWT fallback for bastion_login."""
        source = self._get_function_source("auto_setup")
        assert "cilogon_id" not in source
        assert "zfill" not in source

    def test_no_jwt_fallback_in_oauth_callback(self):
        """_process_oauth_callback must NOT have a JWT fallback for bastion_login."""
        source = self._get_function_source("_process_oauth_callback")
        assert "cilogon_id" not in source
        assert "zfill" not in source
