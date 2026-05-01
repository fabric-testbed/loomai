"""CILogon OIDC client using authlib."""

from __future__ import annotations

import hashlib
import logging
import secrets
from base64 import urlsafe_b64encode
from urllib.parse import urlencode

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# CILogon OIDC endpoints
CILOGON_AUTHORIZE_URL = "https://cilogon.org/authorize"
CILOGON_TOKEN_URL = "https://cilogon.org/oauth2/token"
CILOGON_USERINFO_URL = "https://cilogon.org/oauth2/userinfo"

# Module-level PKCE store: state -> code_verifier
_pkce_store: dict[str, str] = {}


def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def get_authorize_url(state: str) -> str:
    """Build the CILogon authorization URL with PKCE.

    Args:
        state: Opaque state token for CSRF protection.

    Returns:
        Full CILogon authorize URL to redirect the user to.
    """
    code_verifier, code_challenge = _generate_pkce()
    _pkce_store[state] = code_verifier

    params = {
        "response_type": "code",
        "client_id": settings.CILOGON_CLIENT_ID,
        "redirect_uri": settings.cilogon_callback_url,
        "scope": settings.CILOGON_SCOPES,
        "state": state,
        "skin": settings.CILOGON_SKIN,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    url = f"{CILOGON_AUTHORIZE_URL}?{urlencode(params)}"
    logger.debug("CILogon authorize URL: %s", url)
    return url


async def exchange_code(code: str, state: str) -> dict:
    """Exchange the authorization code for tokens.

    Args:
        code: Authorization code from CILogon callback.
        state: State parameter to look up the PKCE verifier.

    Returns:
        Dict with id_token, access_token, refresh_token, etc.

    Raises:
        ValueError: If state is unknown or token request fails.
    """
    code_verifier = _pkce_store.pop(state, None)
    if not code_verifier:
        raise ValueError(f"Unknown or expired PKCE state: {state}")

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.cilogon_callback_url,
        "client_id": settings.CILOGON_CLIENT_ID,
        "client_secret": settings.CILOGON_CLIENT_SECRET,
        "code_verifier": code_verifier,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(CILOGON_TOKEN_URL, data=data)
        if resp.status_code != 200:
            logger.error("CILogon token exchange failed: %s %s", resp.status_code, resp.text)
            raise ValueError(f"CILogon token exchange failed: {resp.status_code}")
        tokens = resp.json()

    logger.info("CILogon token exchange successful")
    return tokens


async def get_userinfo(access_token: str) -> dict:
    """Fetch user info from CILogon.

    Args:
        access_token: OAuth2 access token.

    Returns:
        Dict with sub, email, name, etc.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            CILOGON_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code != 200:
            logger.error("CILogon userinfo failed: %s %s", resp.status_code, resp.text)
            raise ValueError(f"CILogon userinfo failed: {resp.status_code}")
        return resp.json()
