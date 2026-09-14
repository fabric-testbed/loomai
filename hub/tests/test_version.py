"""The hub version must be declared once and reported consistently.

main.py and tracking_headers.py each used to carry their own literal, and they
had drifted to 0.7.13 and 0.2.0 respectively — so every outgoing Core API
request advertised a version five releases stale.
"""

from __future__ import annotations

import re

from app import __version__
from app.main import app
from app.tracking_headers import get_tracking_headers


def test_version_is_a_release_number():
    assert re.fullmatch(r"\d+\.\d+\.\d+[a-z]?", __version__), __version__


def test_fastapi_metadata_matches():
    assert app.version == __version__


def test_tracking_header_matches():
    assert get_tracking_headers()["X-LoomAI-Version"] == f"hub-{__version__}"


def test_tracking_header_identifies_the_hub():
    headers = get_tracking_headers("f2b25790-b1b9-421f-a998-16fc443dc999")
    assert headers["X-LoomAI-Source"] == "loomai-hub"
    assert headers["X-LoomAI-User"] == "f2b25790-b1b9-421f-a998-16fc443dc999"


def test_tracking_header_defaults_the_user():
    assert get_tracking_headers()["X-LoomAI-User"] == "unknown"
