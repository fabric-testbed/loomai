"""Tests for masking/preserving secrets on the settings API."""
from app.routes import config


def _settings():
    return {
        "ai": {
            "fabric_api_key": "FAB-REAL",
            "nrp_api_key": "",
            "custom_providers": [
                {"name": "p1", "base_url": "http://x", "api_key": "CP-REAL"},
            ],
        },
        "chameleon": {
            "password_auth": {"username": "u", "password": "CHM-REAL"},
            "sites": {"CHI@TACC": {"app_credential_secret": "ACS-REAL", "password": ""}},
        },
    }


def test_mask_hides_nonempty_secrets():
    masked = config._mask_secrets(_settings())
    assert masked["ai"]["fabric_api_key"] == config._SECRET_MASK
    assert masked["ai"]["nrp_api_key"] == ""          # empty stays empty
    assert masked["ai"]["custom_providers"][0]["api_key"] == config._SECRET_MASK
    assert masked["chameleon"]["password_auth"]["password"] == config._SECRET_MASK
    assert masked["chameleon"]["sites"]["CHI@TACC"]["app_credential_secret"] == config._SECRET_MASK
    # Non-secret fields untouched; original object not mutated.
    assert masked["chameleon"]["password_auth"]["username"] == "u"
    assert _settings()["ai"]["fabric_api_key"] == "FAB-REAL"


def test_restore_keeps_stored_when_mask_sent_back():
    old = _settings()
    incoming = config._mask_secrets(old)               # what the client received
    restored = config._restore_masked_secrets(incoming, old)
    assert restored["ai"]["fabric_api_key"] == "FAB-REAL"
    assert restored["ai"]["custom_providers"][0]["api_key"] == "CP-REAL"
    assert restored["chameleon"]["password_auth"]["password"] == "CHM-REAL"
    assert restored["chameleon"]["sites"]["CHI@TACC"]["app_credential_secret"] == "ACS-REAL"


def test_restore_accepts_changed_secret():
    old = _settings()
    incoming = config._mask_secrets(old)
    incoming["ai"]["fabric_api_key"] = "FAB-NEW"        # user typed a new key
    restored = config._restore_masked_secrets(incoming, old)
    assert restored["ai"]["fabric_api_key"] == "FAB-NEW"


def test_restore_allows_clearing_secret():
    old = _settings()
    incoming = config._mask_secrets(old)
    incoming["ai"]["fabric_api_key"] = ""              # user cleared it
    restored = config._restore_masked_secrets(incoming, old)
    assert restored["ai"]["fabric_api_key"] == ""
