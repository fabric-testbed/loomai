"""Central settings management for Loomai / fabric-webgui.

All application settings are stored in a single ``settings.json`` file
inside ``{FABRIC_STORAGE_DIR}/.loomai/``.  Legacy ``fabric_rc`` and
``.ai_tools.json`` files are migrated automatically on first load.

Public API
----------
- ``load_settings()`` / ``save_settings(settings)`` — read/write the full dict
- ``get_*`` / ``set_*`` accessors — typed convenience for individual settings
- ``generate_fabric_rc(settings)`` / ``generate_ssh_config(settings)`` — derived files
- ``migrate_from_legacy()`` — one-time import of fabric_rc + .ai_tools.json
- Tool-config helpers: ``seed_tool_configs``, ``reset_tool_config``, ``get_tool_config_status``
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SETTINGS_SUBDIR = ".loomai"
_SETTINGS_FILE = "settings.json"
_TOOLS_SUBDIR = "tools"
_DOCKER_AI_TOOLS_DIR = "/app/ai-tools"
_MIGRATION_SLICE_POLICY_DEFAULT = "slice_policy_default_seeded"
_AI_RENCI_CUSTOM_API_ENV = "LOOMAI_CUSTOM_PROVIDER_AI_RENCI_API_KEY"

# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_cached_settings: Optional[dict] = None
_capability_profile_cache: dict[str, Any] = {
    "path": None,
    "mtime": None,
    "profiles": {},
}


def custom_provider_env_key(name: str) -> str:
    """Return the environment variable used for a custom provider API key."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(name or "custom").strip()).strip("_").upper()
    return f"LOOMAI_CUSTOM_PROVIDER_{slug or 'CUSTOM'}_API_KEY"


def custom_provider_base_url_env_key(name: str) -> str:
    """Return the environment variable used for a custom provider base URL."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(name or "custom").strip()).strip("_").upper()
    return f"LOOMAI_CUSTOM_PROVIDER_{slug or 'CUSTOM'}_BASE_URL"


def _resolve_ai_renci_api_key(ai: dict) -> str:
    """Return the canonical ai-renci key, falling back to legacy FABRIC key."""
    for provider in ai.get("custom_providers") or []:
        if not isinstance(provider, dict):
            continue
        name = str(provider.get("name") or "").strip()
        if custom_provider_env_key(name) == _AI_RENCI_CUSTOM_API_ENV and provider.get("api_key"):
            return str(provider.get("api_key") or "")
    return os.environ.get(_AI_RENCI_CUSTOM_API_ENV, "") or str(ai.get("fabric_api_key", "") or "")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge *overlay* into a copy of *base*.

    Keys present in *base* but missing from *overlay* are preserved.
    Keys in *overlay* override *base* at the leaf level.
    """
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _atomic_write_json(path: str, data: dict) -> None:
    """Write *data* as JSON to *path* atomically (tmp + os.replace)."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)


def _atomic_write_text(path: str, text: str) -> None:
    """Write *text* to *path* atomically (tmp + os.replace)."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        f.write(text)
    os.replace(tmp_path, path)


def _read_settings_json(path: str) -> dict | None:
    """Best-effort read of a settings JSON object from *path*."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        logger.warning("Failed to read %s", path, exc_info=True)
        return None


def _has_value(value: Any) -> bool:
    """Return True when a persisted setting carries non-empty user data."""
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return value is not None


def _settings_has_more_config(candidate: dict, current: dict | None) -> bool:
    """Return True if *candidate* has important config missing from *current*."""
    current = current or {}
    checks = [
        ("fabric", "bastion_username"),
        ("fabric", "project_id"),
        ("ai", "fabric_api_key"),
        ("ai", "nrp_api_key"),
        ("ai", "custom_providers"),
        ("ai", "discovered_models"),
    ]
    for section, key in checks:
        candidate_value = (candidate.get(section) or {}).get(key)
        current_value = (current.get(section) or {}).get(key)
        if _has_value(candidate_value) and not _has_value(current_value):
            return True
    return False


def _portable_config_overlay(settings: dict) -> dict:
    """Return settings sections safe to copy across root/per-user fallbacks."""
    overlay: dict[str, Any] = {}
    for section in ("fabric", "ai"):
        value = settings.get(section)
        if isinstance(value, dict):
            overlay[section] = copy.deepcopy(value)
    return overlay


def _iter_user_settings_paths() -> list[str]:
    """Return candidate per-user settings paths, active user first when known."""
    try:
        from app import user_registry
    except Exception:
        return []

    uuids: list[str] = []
    try:
        active = user_registry.get_active_user_uuid()
        if active:
            uuids.append(active)
    except Exception:
        pass
    try:
        for user in user_registry.list_users():
            uuid = user.get("uuid") if isinstance(user, dict) else None
            if uuid and uuid not in uuids:
                uuids.append(uuid)
    except Exception:
        pass
    try:
        base = user_registry.users_base_dir()
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                if name not in uuids and os.path.isdir(os.path.join(base, name)):
                    uuids.append(name)
    except Exception:
        return []

    paths: list[str] = []
    try:
        base = user_registry.users_base_dir()
    except Exception:
        return []
    for uuid in uuids:
        paths.append(os.path.join(base, uuid, _SETTINGS_SUBDIR, _SETTINGS_FILE))
    return paths


def _is_root_settings_path(path: str) -> bool:
    root_path = os.path.join(get_root_storage_dir(), _SETTINGS_SUBDIR, _SETTINGS_FILE)
    return os.path.abspath(path) == os.path.abspath(root_path)


def _heal_root_settings_from_user(path: str, on_disk: dict | None) -> dict | None:
    """Heal an empty root fallback settings file from per-user settings.

    If active-user resolution briefly fails, callers can fall back to the root
    settings.json. That file may be stale or empty while a real per-user
    settings file has manually entered FABRIC/AI config. Copy only portable
    config sections so root fallback does not serve empty credentials.
    """
    if not _is_root_settings_path(path):
        return on_disk

    for user_path in _iter_user_settings_paths():
        user_settings = _read_settings_json(user_path)
        if not user_settings or not _settings_has_more_config(user_settings, on_disk):
            continue
        healed = _deep_merge(on_disk or {}, _portable_config_overlay(user_settings))
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _atomic_write_json(path, healed)
            logger.warning("Healed stale root settings fallback from %s", user_path)
        except Exception:
            logger.warning("Failed to heal stale root settings fallback", exc_info=True)
        return healed
    return on_disk


# ---------------------------------------------------------------------------
# Core directory / path helpers
# ---------------------------------------------------------------------------


def get_storage_dir() -> str:
    """Return the effective storage directory.

    When a user registry exists and an active user is set, returns the
    per-user directory ``.loomai/users/{uuid}/``. Otherwise returns the flat
    ``FABRIC_STORAGE_DIR`` root (legacy single-user mode).
    """
    from app.user_registry import get_user_storage_dir
    user_dir = get_user_storage_dir()
    if user_dir is not None:
        return user_dir
    return get_root_storage_dir()


def get_root_storage_dir() -> str:
    """Return the raw FABRIC_STORAGE_DIR (never user-scoped)."""
    from app.user_registry import get_storage_root_dir
    return get_storage_root_dir()


def manage_home_ai_paths() -> bool:
    """Whether LoomAI may create/replace/remove AI-tool config paths in the
    HOME directory (~/.claude, ~/.claude.json, ~/.codex, ~/.crush, ...).

    This is only safe inside the LoomAI container, where HOME is the
    container user's home on the work volume. Anywhere else — a developer
    machine running the backend or the test suite — the same code would
    hijack the developer's REAL dotfiles: ``_ensure_user_symlinks`` moves
    ``~/.claude`` into per-user storage and leaves a symlink, and
    ``restore_ai_tool_configs`` rmtree's ``~/.claude`` outright.

    Defaults to the container marker (LOOMAI_COMBINED_IMAGE, set in the
    Dockerfile); LOOMAI_MANAGE_HOME_AI=1/0 overrides in either direction.
    """
    v = os.environ.get("LOOMAI_MANAGE_HOME_AI", "").strip().lower()
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    return bool(os.environ.get("LOOMAI_COMBINED_IMAGE", "").strip())


def get_settings_dir() -> str:
    """Return the ``.loomai/`` directory, creating it if necessary."""
    d = os.path.join(get_storage_dir(), _SETTINGS_SUBDIR)
    os.makedirs(d, exist_ok=True)
    return d


def get_settings_path() -> str:
    """Return the full path to ``settings.json``."""
    return os.path.join(get_settings_dir(), _SETTINGS_FILE)


# ---------------------------------------------------------------------------
# Default settings schema
# ---------------------------------------------------------------------------


def get_default_settings() -> dict:
    """Return a fresh copy of the full default settings dict."""
    storage_dir = get_storage_dir()
    config_dir = os.path.join(storage_dir, "fabric_config")
    return {
        "schema_version": 1,
        "paths": {
            "storage_dir": storage_dir,
            "config_dir": config_dir,
            "artifacts_dir": os.path.join(storage_dir, "my_artifacts"),
            "slices_dir": os.path.join(storage_dir, "my_slices"),
            "notebooks_dir": os.path.join(storage_dir, "notebooks"),
            "ai_tools_dir": os.path.join(storage_dir, ".ai-tools"),
            "token_file": os.path.join(config_dir, "id_token.json"),
            "bastion_key_file": os.path.join(config_dir, "fabric_bastion_key"),
            "slice_keys_dir": os.path.join(config_dir, "slice_keys"),
            "ssh_config_file": os.path.join(config_dir, "ssh_config"),
            "log_file": "/tmp/fablib/fablib.log",
        },
        "fabric": {
            "project_id": "",
            "bastion_username": "",
            "slice_policy": {
                # Container-default resource rail: cap live FABRIC leases at
                # six hours unless an operator explicitly changes settings.
                # After the one-time legacy seeding migration, set this to 0
                # to intentionally disable the backend cap.
                "max_lease_hours": 6,
            },
            "hosts": {
                "credmgr": "cm.fabric-testbed.net",
                "orchestrator": "orchestrator.fabric-testbed.net",
                "core_api": "uis.fabric-testbed.net",
                "bastion": "bastion.fabric-testbed.net",
                "artifact_manager": "artifacts.fabric-testbed.net",
            },
            "logging": {"level": "INFO"},
            "avoid_sites": [],
            "ssh_command_line": (
                "ssh -i {{ _self_.private_ssh_key_file }} "
                "-F {config_dir}/ssh_config "
                "{{ _self_.username }}@{{ _self_.management_ip }}"
            ),
        },
        "ai": {
            "fabric_api_key": "",
            "fabric_api_key_name": "",     # CM key name of the stored key (loomai-*)
            "fabric_api_key_expires": "",  # ISO-8601 expiry of the stored key
            "nrp_api_key": "",
            "ai_server_url": "https://ai.fabric-testbed.net",
            "nrp_server_url": "https://ellm.nrp-nautilus.io",
            # List of {"name": str, "base_url": str, "api_key": str,
            # "endpoint_style": "auto"|"chat"|"responses"|"non-chat"}.
            "custom_providers": [],
            "default_model": "",        # Auto-discovered or user-set default LLM
            "default_model_source": "", # "fabric", "nrp", "custom:<name>", or ""
            "discovered_models": {},    # Persisted model list from last discovery
            "tools": {
                "aider": True,
                "opencode": True,
                "goose": True,
                "crush": True,
                "pi": True,
                "claude": True,
                "deepagents": True,
            },
            "harnesses": {
                # Supported opt-in for local MCP API self-description tools.
                # When false, the loomai-harness MCP tool surface must remain
                # identical to the normal operational surface.
                "mcp_metatools": False,
            },
            "assistant": {
                # Deployment-plan feature flags. These are now default-on for
                # the assistant parity build; explicit saved False overrides
                # remain authoritative.
                "strict_fabric_query_contract": True,
                "final_answer_retry": True,
                "final_answer_retry_scope": "all",  # "all" or "useful_tier"
                "compact_fabric_resource_tools": True,
                "resource_query_generation_defaults": True,
                # Default-off A/B gate for weak-model state injection and
                # active context compaction. Capability profiles decide which
                # models are weak enough to use it.
                "weak_model_context_management": False,
                "resource_query_generation": {
                    # Optional D3 defaults applied only when
                    # resource_query_generation_defaults is enabled.
                    "default": {},
                    "models": {},
                },
                "capability_profiles_enabled": True,
                "capability_profile_path": (
                    "/home/fabric/work/Projects/LoomAI_LLM_Benchmark/"
                    "runs/model-capabilities/current/model_capabilities.json"
                ),
                "tool_loop": {
                    # Last-resort emergency cap. Normal stopping should come
                    # from no-progress detection or budget guards.
                    "no_progress_limit": 3,
                },
                "turn_budget": {
                    # 0 disables a limit. Cost budgets require a non-zero
                    # cost_per_1k_tokens_usd estimate at default/provider/model
                    # scope because providers expose no uniform live pricing API.
                    "default": {
                        "max_tokens": 0,
                        "max_cost_usd": 0,
                        "cost_per_1k_tokens_usd": 0,
                    },
                    "providers": {},
                    "models": {},
                },
            },
        },
        "chameleon": {
            "enabled": False,
            "default_site": "CHI@TACC",
            "ssh_key_file": "",  # Chameleon SSH key; falls back to FABRIC slice key if empty
            "password_auth": {
                "username": "",
                "password": "",
            },
            "sites": {
                "CHI@TACC": {
                    "auth_type": "application_credential",
                    "auth_url": "https://chi.tacc.chameleoncloud.org:5000/v3",
                    "default_key_name": "",
                    "app_credential_id": "",
                    "app_credential_secret": "",
                    "project_id": "",
                    "identity_provider": "chameleon",
                    "protocol": "openid",
                    "discovery_endpoint": "https://auth.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration",
                    "client_id": "keystone-tacc-prod",
                    "client_secret": "none",
                    "access_token_type": "access_token",
                    "openid_scope": "openid profile",
                },
                "CHI@UC": {
                    "auth_type": "application_credential",
                    "auth_url": "https://chi.uc.chameleoncloud.org:5000/v3",
                    "default_key_name": "",
                    "app_credential_id": "",
                    "app_credential_secret": "",
                    "project_id": "",
                    "identity_provider": "chameleon",
                    "protocol": "openid",
                    "discovery_endpoint": "https://auth.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration",
                    "client_id": "keystone-uc-prod",
                    "client_secret": "none",
                    "access_token_type": "access_token",
                    "openid_scope": "openid profile",
                },
                "CHI@Edge": {
                    "auth_type": "application_credential",
                    "auth_url": "https://chi.edge.chameleoncloud.org:5000/v3",
                    "default_key_name": "",
                    "app_credential_id": "",
                    "app_credential_secret": "",
                    "project_id": "",
                    "identity_provider": "chameleon",
                    "protocol": "openid",
                    "discovery_endpoint": "https://auth.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration",
                    "client_id": "keystone-edge-prod",
                    "client_secret": "none",
                    "access_token_type": "access_token",
                    "openid_scope": "openid profile",
                },
                "KVM@TACC": {
                    "auth_type": "application_credential",
                    "auth_url": "https://kvm.tacc.chameleoncloud.org:5000/v3",
                    "default_key_name": "",
                    "app_credential_id": "",
                    "app_credential_secret": "",
                    "project_id": "",
                    "identity_provider": "chameleon",
                    "protocol": "openid",
                    "discovery_endpoint": "https://auth.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration",
                    "client_id": "keystone-tacc-prod",
                    "client_secret": "none",
                    "access_token_type": "access_token",
                    "openid_scope": "openid profile",
                },
            },
        },
        "sphere": {
            "enabled": False,
            "grpc_endpoint": "grpc.sphere-testbed.net",
            "grpc_port": 443,
            "api_endpoint": "https://api.sphere-testbed.net",
            "username": "",
            "password": "",  # optional; enables Identity.Login + token refresh
            "token": "",  # bearer from `mrg whoami -t`; preferred when present
            "default_project": "",  # e.g. "fabricsphere"
        },
        "services": {
            "jupyter_port": 8889,
            "model_proxy_port": 9199,
        },
        "tool_configs": {},
    }


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------


def load_settings() -> dict:
    """Load settings from disk, deep-merging with defaults for any missing keys.

    The result is cached in ``_cached_settings`` for subsequent accessor calls.
    """
    global _cached_settings

    defaults = get_default_settings()
    path = get_settings_path()

    on_disk: dict | None = None
    if os.path.isfile(path):
        on_disk = _read_settings_json(path)
        if on_disk is not None:
            on_disk = _heal_root_settings_from_user(path, on_disk)
            settings = _deep_merge(defaults, on_disk)
        else:
            settings = defaults
    else:
        on_disk = _heal_root_settings_from_user(path, None)
        if on_disk is not None:
            settings = _deep_merge(defaults, on_disk)
        else:
            settings = defaults

    if on_disk is None:
        settings = defaults

    should_persist = False
    if _seed_slice_policy_default(settings, on_disk, defaults):
        should_persist = True
    if _seed_custom_providers_from_env(settings):
        should_persist = True
    if should_persist:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _atomic_write_json(path, settings)
        except Exception:
            logger.warning("Failed to persist settings migration/env seeding", exc_info=True)

    _seed_sphere_from_env(settings)

    _cached_settings = settings
    return settings


def _seed_slice_policy_default(settings: dict, on_disk: dict | None, defaults: dict) -> bool:
    """Seed legacy zero/missing lease caps to the default once.

    `max_lease_hours=0` remains the persisted way to disable the cap after
    this migration marker has been written.
    """
    if not isinstance(on_disk, dict):
        return False
    migrations = on_disk.get("migrations", {})
    if isinstance(migrations, dict) and migrations.get(_MIGRATION_SLICE_POLICY_DEFAULT):
        return False

    default_max = (
        defaults.get("fabric", {})
        .get("slice_policy", {})
        .get("max_lease_hours", 6)
    )
    raw_value = (
        on_disk.get("fabric", {})
        .get("slice_policy", {})
        .get("max_lease_hours")
    )
    try:
        persisted_hours = int(raw_value or 0)
    except (TypeError, ValueError):
        persisted_hours = 0

    policy = settings.setdefault("fabric", {}).setdefault("slice_policy", {})
    if persisted_hours <= 0:
        policy["max_lease_hours"] = default_max
    settings.setdefault("migrations", {})[_MIGRATION_SLICE_POLICY_DEFAULT] = True
    return True


def _seed_sphere_from_env(settings: dict) -> None:
    """Overlay SPHERE config from environment variables when provided.

    Lets a deployment inject SPHERE credentials/config (e.g. in docker-compose)
    so they survive a fresh container/volume — environment wins over on-disk for
    any field that is set. Recognised vars: ``SPHERE_ENABLED``,
    ``SPHERE_USERNAME``, ``SPHERE_PASSWORD``, ``SPHERE_TOKEN``,
    ``SPHERE_DEFAULT_PROJECT``, ``SPHERE_GRPC_ENDPOINT``, ``SPHERE_GRPC_PORT``.
    """
    sphere = settings.setdefault("sphere", {})
    env = os.environ
    if env.get("SPHERE_ENABLED") is not None:
        sphere["enabled"] = env["SPHERE_ENABLED"].strip().lower() in ("1", "true", "yes", "on")
    for var, key in (
        ("SPHERE_USERNAME", "username"),
        ("SPHERE_PASSWORD", "password"),
        ("SPHERE_TOKEN", "token"),
        ("SPHERE_DEFAULT_PROJECT", "default_project"),
        ("SPHERE_GRPC_ENDPOINT", "grpc_endpoint"),
    ):
        if env.get(var):
            sphere[key] = env[var]
    if env.get("SPHERE_GRPC_PORT"):
        try:
            sphere["grpc_port"] = int(env["SPHERE_GRPC_PORT"])
        except ValueError:
            pass


def _custom_provider_name_from_env_slug(slug: str) -> str:
    """Return a stable provider name from a LOOMAI_CUSTOM_PROVIDER slug."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(slug or "custom")).strip("_")
    return cleaned.lower().replace("_", "-") or "custom"


def _seed_custom_providers_from_env(settings: dict) -> bool:
    """Seed custom providers from LOOMAI_CUSTOM_PROVIDER_* env vars.

    Deployment secrets are the source of truth for fresh/migrated containers.
    Only seed when the persisted provider list is empty so user-configured
    providers remain authoritative.
    """
    ai = settings.setdefault("ai", {})
    providers = ai.get("custom_providers")
    if isinstance(providers, list) and providers:
        return False

    prefix = "LOOMAI_CUSTOM_PROVIDER_"
    suffix = "_BASE_URL"
    seeded: list[dict[str, Any]] = []
    for key, base_url in sorted(os.environ.items()):
        if not key.startswith(prefix) or not key.endswith(suffix) or not base_url:
            continue
        slug = key[len(prefix):-len(suffix)]
        api_key = os.environ.get(f"{prefix}{slug}_API_KEY", "")
        endpoint_style = normalize_ai_endpoint_style(
            os.environ.get(f"{prefix}{slug}_ENDPOINT_STYLE", "auto")
        )
        seeded.append({
            "name": _custom_provider_name_from_env_slug(slug),
            "base_url": str(base_url).rstrip("/"),
            "api_key": api_key,
            "endpoint_style": endpoint_style,
        })

    if not seeded:
        return False
    ai["custom_providers"] = seeded
    return True


def merge_settings_update(existing: dict, update: dict) -> dict:
    """Return *update* merged over a full existing settings dict."""
    base = existing if isinstance(existing, dict) else get_default_settings()
    overlay = update if isinstance(update, dict) else {}
    return _deep_merge(base, overlay)


def _preserve_non_empty_fabric_identity(settings: dict, existing: dict | None) -> dict:
    """Refuse empty overwrites of manually entered FABRIC identity fields."""
    if not existing:
        return settings
    fabric = settings.setdefault("fabric", {})
    old_fabric = existing.get("fabric") or {}
    for key in ("bastion_username", "project_id"):
        old_value = old_fabric.get(key, "")
        new_value = fabric.get(key, "")
        if _has_value(old_value) and not _has_value(new_value):
            fabric[key] = old_value
            logger.warning("Preserved non-empty fabric.%s during empty settings overwrite", key)
    return settings


def save_settings(settings: dict) -> None:
    """Persist *settings* to disk (atomic write), regenerate derived files, and invalidate cache."""
    global _cached_settings

    path = get_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing_on_disk = _read_settings_json(path)
    existing_settings = (
        _deep_merge(get_default_settings(), existing_on_disk)
        if isinstance(existing_on_disk, dict)
        else None
    )
    base = existing_settings or get_default_settings()
    settings = _deep_merge(base, settings or {})
    settings = _preserve_non_empty_fabric_identity(settings, existing_settings)
    # Don't persist SPHERE secrets that were injected via environment — they are
    # the deployment's source of truth and shouldn't be written to disk (where
    # they'd survive past the env and widen exposure). Strip them from the
    # on-disk copy while keeping them in the in-memory cache for this process.
    to_write = settings
    env_secret_fields = [v for v, k in (("SPHERE_PASSWORD", "password"), ("SPHERE_TOKEN", "token")) if os.environ.get(v)]
    if env_secret_fields and isinstance(settings.get("sphere"), dict):
        to_write = copy.deepcopy(settings)
        for var, key in (("SPHERE_PASSWORD", "password"), ("SPHERE_TOKEN", "token")):
            if os.environ.get(var):
                to_write["sphere"][key] = ""
    _atomic_write_json(path, to_write)

    _cached_settings = settings

    # Regenerate derived config files
    try:
        generate_fabric_rc(settings)
    except Exception:
        logger.warning("Failed to regenerate fabric_rc", exc_info=True)
    try:
        generate_ssh_config(settings)
    except Exception:
        logger.warning("Failed to regenerate ssh_config", exc_info=True)


def _get_settings() -> dict:
    """Return cached settings, loading from disk if necessary."""
    global _cached_settings
    if _cached_settings is None:
        return load_settings()
    return _cached_settings


def invalidate_settings_cache() -> None:
    """Clear the cached settings so the next access reloads from disk."""
    global _cached_settings
    _cached_settings = None


# ---------------------------------------------------------------------------
# Path accessors
# ---------------------------------------------------------------------------


def _live_config_dir() -> str:
    """The active FABRIC config dir.

    Always the flat root ``/home/fabric/work/fabric_config`` — a symlink to the
    active user's folder in multi-user mode, a real directory otherwise. Computed
    fresh (like ``get_artifacts_dir``) rather than read from ``settings.json`` so
    it stays correct across user switches and the ``users/`` → ``.loomai/users/``
    relocation, instead of pinning a stale per-user absolute path.
    """
    return os.path.join(get_root_storage_dir(), "fabric_config")


def get_config_dir() -> str:
    """Return the active config dir (root ``fabric_config`` symlink), creating it if needed."""
    d = _live_config_dir()
    os.makedirs(d, exist_ok=True)
    return d


def get_artifacts_dir() -> str:
    """Artifacts live at the flat ``/home/fabric/work/my_artifacts`` — a symlink
    to the active user's folder. Computed fresh (not the saved settings path) so
    it's stable across user switches and the storage relocation."""
    d = os.path.join(get_root_storage_dir(), "my_artifacts")
    os.makedirs(d, exist_ok=True)
    return d


def get_slices_dir() -> str:
    """Slices live in the active user's per-user folder (no root mount)."""
    d = os.path.join(get_storage_dir(), "my_slices")
    os.makedirs(d, exist_ok=True)
    return d


def get_notebooks_dir() -> str:
    """Return the shared JupyterLab notebook workspace path.

    The directory is created on demand when a notebook artifact is launched,
    not during settings reads or app startup.
    """
    return os.path.join(get_root_storage_dir(), "notebooks")


def get_ai_tools_dir() -> str:
    """Return ``paths.ai_tools_dir``."""
    return _get_settings()["paths"]["ai_tools_dir"]


def get_token_path() -> str:
    """Return the path to the FABRIC id_token JSON file.

    Resolution order:
    1. ``FABRIC_TOKEN_FILE`` env var (explicit override)
    2. ``~/.tokens.json`` if it exists (JupyterHub convention)
    3. ``paths.token_file`` from settings (config_dir/id_token.json)
    """
    explicit = os.environ.get("FABRIC_TOKEN_FILE")
    if explicit:
        return explicit

    home_tokens = os.path.join(os.path.expanduser("~"), ".tokens.json")
    if os.path.isfile(home_tokens):
        return home_tokens

    return os.path.join(_live_config_dir(), "id_token.json")


def get_bastion_key_path() -> str:
    """Return the active bastion key path (under the root ``fabric_config`` symlink)."""
    return os.path.join(_live_config_dir(), "fabric_bastion_key")


def get_slice_keys_dir() -> str:
    """Return the active slice-keys dir (under the root ``fabric_config`` symlink)."""
    return os.path.join(_live_config_dir(), "slice_keys")


def get_ssh_config_path() -> str:
    """Return the active ssh_config path (under the root ``fabric_config`` symlink)."""
    return os.path.join(_live_config_dir(), "ssh_config")


def get_log_file() -> str:
    """Return ``paths.log_file``."""
    return _get_settings()["paths"]["log_file"]


# ---------------------------------------------------------------------------
# Setting accessors
# ---------------------------------------------------------------------------


def get_fabric_api_key() -> str:
    """Return ``ai.fabric_api_key``."""
    return _get_settings()["ai"]["fabric_api_key"]


def get_fabric_api_key_meta() -> tuple[str, str]:
    """Return (``ai.fabric_api_key_name``, ``ai.fabric_api_key_expires``)."""
    ai = _get_settings()["ai"]
    return ai.get("fabric_api_key_name", ""), ai.get("fabric_api_key_expires", "")


def get_nrp_api_key() -> str:
    """Return ``ai.nrp_api_key``."""
    return _get_settings()["ai"]["nrp_api_key"]


def get_project_id() -> str:
    """Return ``fabric.project_id``."""
    return _get_settings()["fabric"]["project_id"]


def get_bastion_username() -> str:
    """Return ``fabric.bastion_username``."""
    return _get_settings()["fabric"]["bastion_username"]


def get_avoid_sites() -> List[str]:
    """Return ``fabric.avoid_sites`` (list of site name strings)."""
    return _get_settings()["fabric"]["avoid_sites"]


def get_host(name: str) -> str:
    """Return ``fabric.hosts.{name}``."""
    return _get_settings()["fabric"]["hosts"].get(name, "")


def get_log_level() -> str:
    """Return ``fabric.logging.level``."""
    return _get_settings()["fabric"]["logging"]["level"]


def get_max_slice_lease_hours() -> int | None:
    """Return backend-enforced max slice lease hours, or None when disabled."""
    value = (
        _get_settings()
        .get("fabric", {})
        .get("slice_policy", {})
        .get("max_lease_hours", 0)
    )
    try:
        hours = int(value or 0)
    except (TypeError, ValueError):
        return None
    return hours if hours > 0 else None


def get_ai_tools() -> Dict[str, bool]:
    """Return ``ai.tools`` (dict of tool name to enabled bool)."""
    return _get_settings()["ai"]["tools"]


def get_mcp_metatools_enabled() -> bool:
    """Return whether loomai-harness exposes OpenAPI metatools."""
    return bool(
        _get_settings()
        .get("ai", {})
        .get("harnesses", {})
        .get("mcp_metatools", False)
    )


def set_ai_tools(tools: dict) -> None:
    """Update ``ai.tools`` in settings and persist to disk."""
    settings = _get_settings()
    current_tools = settings["ai"]["tools"]
    for k in current_tools:
        if k in tools:
            current_tools[k] = bool(tools[k])
    save_settings(settings)


def get_ai_server_url() -> str:
    """Return ``ai.ai_server_url``."""
    return _get_settings()["ai"]["ai_server_url"]


def get_nrp_server_url() -> str:
    """Return ``ai.nrp_server_url``."""
    return _get_settings()["ai"]["nrp_server_url"]


def get_custom_providers() -> list:
    """Return ``ai.custom_providers`` list."""
    return _get_settings()["ai"].get("custom_providers", [])


def get_ai_renci_api_key() -> str:
    """Return the canonical ai-renci API key for generated harness envs."""
    return _resolve_ai_renci_api_key(_get_settings().get("ai", {}))


def get_default_model() -> str:
    """Return ``ai.default_model``."""
    return _get_settings()["ai"].get("default_model", "")


def get_default_model_source() -> str:
    """Return ``ai.default_model_source``."""
    return _get_settings()["ai"].get("default_model_source", "")


def get_assistant_settings() -> dict:
    """Return ``ai.assistant`` feature flags/settings."""
    return _get_settings().get("ai", {}).get("assistant", {})


def normalize_ai_endpoint_style(value: Any) -> str:
    """Normalize OpenAI-compatible endpoint style labels."""
    if isinstance(value, dict):
        value = value.get("value", value.get("default", value.get("style")))
    lowered = str(value or "auto").strip().lower().replace("_", "-")
    aliases = {
        "": "auto",
        "default": "auto",
        "detect": "auto",
        "chat-completions": "chat",
        "chat-completion": "chat",
        "chat_completion": "chat",
        "responses-api": "responses",
        "response": "responses",
        "nonchat": "non-chat",
        "none": "non-chat",
    }
    lowered = aliases.get(lowered, lowered)
    if lowered in {"auto", "chat", "responses", "non-chat"}:
        return lowered
    return "auto"


def get_assistant_tool_loop_settings() -> dict:
    """Return normalized assistant tool-loop controls."""
    raw = get_assistant_settings().get("tool_loop", {})
    if not isinstance(raw, dict):
        raw = {}
    no_progress_limit = _coerce_int(
        raw.get("no_progress_limit"),
        minimum=2,
        maximum=20,
    )
    return {
        "no_progress_limit": no_progress_limit or 3,
    }


def _clean_turn_budget(config: Any) -> dict:
    """Normalize per-turn budget config fields."""
    if not isinstance(config, dict):
        return {}
    max_tokens = _coerce_int(
        _first_present(
            config.get("max_tokens"),
            config.get("token_budget"),
            config.get("turn_token_budget"),
        ),
        minimum=0,
        maximum=10_000_000,
    )
    max_cost = _coerce_float(
        _first_present(
            config.get("max_cost_usd"),
            config.get("cost_budget_usd"),
            config.get("turn_cost_budget_usd"),
        ),
        minimum=0.0,
        maximum=1_000_000.0,
    )
    cost_rate = _coerce_float(
        _first_present(
            config.get("cost_per_1k_tokens_usd"),
            config.get("estimated_cost_per_1k_tokens_usd"),
        ),
        minimum=0.0,
        maximum=1_000.0,
    )
    cleaned: dict[str, Any] = {}
    if max_tokens is not None:
        cleaned["max_tokens"] = max_tokens
    if max_cost is not None:
        cleaned["max_cost_usd"] = max_cost
    if cost_rate is not None:
        cleaned["cost_per_1k_tokens_usd"] = cost_rate
    return cleaned


def _assistant_provider_from_model_key(model_key: str) -> str:
    """Infer the assistant provider key from a full model key."""
    key = str(model_key or "").strip()
    if ":" in key:
        return key.split(":", 1)[0].strip().lower()
    return "fabric"


def get_assistant_turn_budget(model_key: str = "", provider: str = "") -> dict:
    """Resolve per-turn token/cost budget for a provider/model.

    Configuration lives under ``ai.assistant.turn_budget``:

    - ``default`` applies to every model.
    - ``providers`` may override by provider key (``fabric``, ``nrp``, custom).
    - ``models`` may override by full key (``fabric:qwen3-coder-30b``) or bare
      model id. Matching is case-insensitive.
    """
    raw = get_assistant_settings().get("turn_budget", {})
    if not isinstance(raw, dict):
        return {}

    merged = _clean_turn_budget(raw)
    merged.update(_clean_turn_budget(raw.get("default")))

    provider_key = str(provider or _assistant_provider_from_model_key(model_key)).strip()
    providers = raw.get("providers", {})
    if isinstance(providers, dict):
        for key in (provider_key, provider_key.lower()):
            if key and key in providers:
                merged.update(_clean_turn_budget(providers[key]))
                break

    models = raw.get("models", {})
    if isinstance(models, dict):
        full_key = str(model_key or "").strip()
        bare_key = full_key.split(":", 1)[-1] if ":" in full_key else full_key
        lookup_keys = [
            full_key,
            bare_key,
            full_key.lower(),
            bare_key.lower(),
        ]
        for key in lookup_keys:
            if key and key in models:
                merged.update(_clean_turn_budget(models[key]))
                break
    return merged


def is_strict_fabric_query_contract_enabled() -> bool:
    """Return whether FABRIC information queries auto-use the strict contract."""
    return bool(get_assistant_settings().get("strict_fabric_query_contract", True))


def is_final_answer_retry_enabled() -> bool:
    """Return whether incomplete FABRIC query final answers retry once."""
    return bool(get_assistant_settings().get("final_answer_retry", True))


def get_final_answer_retry_scope() -> str:
    """Return the configured final-answer retry scope."""
    scope = str(get_assistant_settings().get("final_answer_retry_scope", "all") or "all")
    return scope if scope in {"all", "useful_tier"} else "all"


def is_compact_fabric_resource_tools_enabled() -> bool:
    """Return whether assistant FABRIC resource tools use compact envelopes."""
    return bool(get_assistant_settings().get("compact_fabric_resource_tools", True))


def is_resource_query_generation_defaults_enabled() -> bool:
    """Return whether FABRIC resource queries use configured generation defaults."""
    return bool(get_assistant_settings().get("resource_query_generation_defaults", True))


def is_weak_model_context_management_enabled() -> bool:
    """Return whether weak-model state injection/compaction is enabled."""
    return bool(get_assistant_settings().get("weak_model_context_management", False))


def get_mcp_evidence_closure_hints_enabled(model_key: str = "") -> bool:
    """Return whether MCP tool results should carry evidence-closure hints.

    FC18-1 mirrors the assistant weak-model gating: the global
    ``ai.assistant.weak_model_context_management`` flag must be on AND the
    model-key capability profile must opt into weak-model context
    management. Strong profiles and the flag-off state keep the MCP tool
    result surface byte-identical.
    """
    if not is_weak_model_context_management_enabled():
        return False
    key = str(model_key or "").strip()
    if not key:
        return False
    profile = get_model_capability_profile(key)
    if bool(profile.get("weak_model_context_management")):
        return True
    # Compatibility fallback matching the assistant-path gating for stale
    # profile files that predate the explicit field.
    return "qwen3-coder-30b" in key.lower()


def _clean_generation_defaults(config: Any) -> dict:
    """Keep only supported D3 generation-default fields with non-empty values."""
    if not isinstance(config, dict):
        return {}
    cleaned = {}
    for key in ("temperature", "top_p", "max_output_tokens"):
        value = config.get(key)
        if value is not None and value != "":
            cleaned[key] = value
    reasoning_effort = _normalize_reasoning_effort(config.get("reasoning_effort"))
    if reasoning_effort:
        cleaned["reasoning_effort"] = reasoning_effort
    return cleaned


def get_resource_query_generation_defaults(model_key: str = "") -> dict:
    """Return configured generation defaults for a FABRIC resource query.

    Configuration lives under ``ai.assistant.resource_query_generation``:

    - ``default`` applies to every model.
    - ``models`` may override by full key (``fabric:qwen3-coder-30b``) or
      bare model id (``qwen3-coder-30b``). Matching is case-insensitive.
    """
    assistant = get_assistant_settings()
    raw = assistant.get("resource_query_generation", {})
    if not isinstance(raw, dict):
        return {}

    merged = _clean_generation_defaults(raw.get("default"))
    models = raw.get("models", {})
    if not isinstance(models, dict):
        return merged

    full_key = str(model_key or "")
    bare_key = full_key.split(":", 1)[-1] if ":" in full_key else full_key
    lookup_keys = [
        full_key,
        bare_key,
        full_key.lower(),
        bare_key.lower(),
    ]
    for key in lookup_keys:
        if key and key in models:
            merged.update(_clean_generation_defaults(models[key]))
            break
    return merged


def is_capability_profiles_enabled() -> bool:
    """Return whether model capability profiles may tune assistant defaults."""
    return bool(get_assistant_settings().get("capability_profiles_enabled", True))


def get_capability_profile_path() -> str:
    """Return the configured model capability profile JSON path."""
    return str(get_assistant_settings().get("capability_profile_path", "") or "")


def _coerce_int(value: Any, *, minimum: int = 1, maximum: int = 1_000_000) -> int | None:
    """Return an int within bounds, or None for unavailable values."""
    if isinstance(value, dict):
        value = value.get("value", value.get("default"))
    if value is None or value == "":
        return None
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    if coerced < minimum:
        return minimum
    if coerced > maximum:
        return maximum
    return coerced


def _coerce_float(value: Any, *, minimum: float, maximum: float) -> float | None:
    """Return a float within bounds, or None for unavailable values."""
    if isinstance(value, dict):
        value = value.get("value", value.get("default"))
    if value is None or value == "":
        return None
    try:
        coerced = float(value)
    except (TypeError, ValueError):
        return None
    if coerced < minimum:
        return minimum
    if coerced > maximum:
        return maximum
    return coerced


def _capability_bool(value: Any) -> bool | None:
    """Normalize capability support fields that may be bool/string/dict."""
    if isinstance(value, dict):
        value = value.get("supported")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "supported"}:
            return True
        if lowered in {"false", "no", "unsupported"}:
            return False
    return None


def _normalize_endpoint_style(value: Any) -> str | None:
    """Map benchmark/provider endpoint labels to LoomAI internal values."""
    if not value:
        return None
    lowered = str(value).strip().lower().replace("_", "-")
    if "responses" in lowered:
        return "responses"
    if lowered in {"chat", "chat-completions", "chat-completion", "openai-chat"}:
        return "chat"
    if lowered in {"non-chat", "completion", "completions"}:
        return "non-chat"
    return None


def _normalize_reasoning_effort(value: Any) -> str | None:
    """Normalize OpenAI-compatible reasoning-effort labels."""
    if isinstance(value, dict):
        value = value.get("value", value.get("default", value.get("effort")))
    if value is None or value == "":
        return None
    lowered = str(value).strip().lower().replace("_", "-")
    aliases = {
        "minimum": "minimal",
        "maximum": "max",
    }
    lowered = aliases.get(lowered, lowered)
    if lowered in {"minimal", "low", "medium", "high", "max"}:
        return lowered
    return None


def _first_present(*values: Any) -> Any:
    """Return the first value that is not None, preserving numeric zero."""
    for value in values:
        if value is not None:
            return value
    return None


def _normalize_capability_profile(raw_profile: dict, source_path: str) -> dict:
    """Extract the stable LoomAI-relevant subset from a benchmark profile."""
    if not isinstance(raw_profile, dict):
        return {}
    capabilities = raw_profile.get("capabilities") or {}
    recommended = raw_profile.get("recommended_configuration") or {}
    evaluation = raw_profile.get("evaluation") or {}
    model_info = raw_profile.get("model") or {}
    generation = capabilities.get("generation_parameters") or {}
    interaction = capabilities.get("interaction_features") or {}

    context_window = _first_present(
        _coerce_int(recommended.get("context_window_tokens")),
        _coerce_int(capabilities.get("context_window_tokens")),
        _coerce_int(capabilities.get("advertised_context_window_tokens")),
        _coerce_int(model_info.get("context_length")),
    )
    max_output = _first_present(
        _coerce_int(recommended.get("max_output_tokens"), maximum=32768),
        _coerce_int(capabilities.get("max_output_tokens"), maximum=32768),
        _coerce_int(capabilities.get("provider_output_cap_tokens"), maximum=32768),
    )
    max_input = _first_present(
        _coerce_int(recommended.get("max_input_tokens")),
        _coerce_int(capabilities.get("max_input_tokens")),
        _coerce_int(capabilities.get("input_context_tokens")),
    )
    temperature = _first_present(
        _coerce_float(recommended.get("temperature"), minimum=0.0, maximum=2.0),
        _coerce_float(generation.get("temperature"), minimum=0.0, maximum=2.0),
    )
    top_p = _first_present(
        _coerce_float(recommended.get("top_p"), minimum=0.0, maximum=1.0),
        _coerce_float(generation.get("top_p"), minimum=0.0, maximum=1.0),
    )
    reasoning_effort = _first_present(
        _normalize_reasoning_effort(recommended.get("reasoning_effort")),
        _normalize_reasoning_effort(generation.get("reasoning_effort")),
        _normalize_reasoning_effort(capabilities.get("reasoning_effort")),
    )
    endpoint_style = _normalize_endpoint_style(
        recommended.get("endpoint_style")
        or capabilities.get("endpoint_style")
        or model_info.get("model_type")
        or model_info.get("type")
    )
    supports_tools = _capability_bool(interaction.get("tool_calling"))
    reasoning_model = _first_present(
        _capability_bool(recommended.get("reasoning_model")),
        _capability_bool(capabilities.get("reasoning_model")),
        _capability_bool(interaction.get("reasoning")),
        _capability_bool(capabilities.get("reasoning_tokens_count_against_output")),
    )

    normalized = {
        "source_path": source_path,
        "model_key": raw_profile.get("model_key") or model_info.get("id") or model_info.get("name"),
        "provider": raw_profile.get("provider"),
        "config_id": recommended.get("config_id"),
        "evaluation_confidence": evaluation.get("confidence"),
        "evaluation_status": evaluation.get("status"),
        "context_truncation_policy": recommended.get("context_truncation_policy"),
        "orchestration_tier": (
            recommended.get("orchestration_tier")
            or capabilities.get("orchestration_tier")
            or capabilities.get("tier")
        ),
    }
    optional_fields = {
        "context_window_tokens": context_window,
        "max_input_tokens": max_input,
        "max_output_tokens": max_output,
        "temperature": temperature,
        "top_p": top_p,
        "endpoint_style": endpoint_style,
        "supports_tools": supports_tools,
        "reasoning_model": reasoning_model,
        "reasoning_effort": reasoning_effort,
        "strip_temperature": bool(recommended.get("strip_temperature")),
        "omit_tool_choice": bool(recommended.get("omit_tool_choice")),
        "weak_model_context_management": _capability_bool(_first_present(
            recommended.get("weak_model_context_management"),
            capabilities.get("weak_model_context_management"),
        )),
        "context_compaction_enabled": _capability_bool(_first_present(
            recommended.get("context_compaction_enabled"),
            capabilities.get("context_compaction_enabled"),
            recommended.get("compaction_enabled"),
            capabilities.get("compaction_enabled"),
        )),
        "context_compaction_trigger_tokens": _coerce_int(_first_present(
            recommended.get("context_compaction_trigger_tokens"),
            capabilities.get("context_compaction_trigger_tokens"),
            recommended.get("compaction_trigger_tokens"),
            capabilities.get("compaction_trigger_tokens"),
        ), minimum=0),
        "context_compaction_trigger_messages": _coerce_int(_first_present(
            recommended.get("context_compaction_trigger_messages"),
            capabilities.get("context_compaction_trigger_messages"),
            recommended.get("compaction_trigger_messages"),
            capabilities.get("compaction_trigger_messages"),
        ), minimum=0, maximum=1000),
        "context_compaction_preserve_last_tool_outputs": _coerce_int(_first_present(
            recommended.get("context_compaction_preserve_last_tool_outputs"),
            capabilities.get("context_compaction_preserve_last_tool_outputs"),
            recommended.get("compaction_preserve_last_tool_outputs"),
            capabilities.get("compaction_preserve_last_tool_outputs"),
        ), minimum=0, maximum=20),
    }
    for key, value in optional_fields.items():
        if value is None:
            continue
        if key in {"strip_temperature", "omit_tool_choice"} and value is False:
            continue
        else:
            normalized[key] = value
    from app.model_capability_defaults import apply_known_model_ideal_overrides

    normalized = {k: v for k, v in normalized.items() if v is not None and v != ""}
    return apply_known_model_ideal_overrides(normalized)


def _capability_profile_lookup_keys(model_key: str, provider: str | None = None) -> list[str]:
    """Return case-insensitive lookup keys for full and bare model ids."""
    full = str(model_key or "").strip()
    bare = full.split(":", 1)[-1] if ":" in full else full
    inferred_provider = provider or (full.split(":", 1)[0] if ":" in full else "")
    keys = [full, bare]
    if inferred_provider and bare:
        keys.append(f"{inferred_provider}:{bare}")
    if inferred_provider == "fabric" and bare:
        keys.append(bare)
    seen: set[str] = set()
    normalized_keys: list[str] = []
    for key in keys:
        lowered = key.lower()
        if lowered and lowered not in seen:
            seen.add(lowered)
            normalized_keys.append(lowered)
    return normalized_keys


def _builtin_capability_profiles_by_lookup_key() -> dict[str, dict]:
    """Return bundled capability profiles indexed by settings lookup keys."""
    from app.model_capability_defaults import clone_builtin_capability_profiles

    profiles: dict[str, dict] = {}
    for profile in clone_builtin_capability_profiles().values():
        model_key = str(profile.get("model_key") or "").strip()
        if not model_key:
            continue
        for key in _capability_profile_lookup_keys(model_key, profile.get("provider")):
            profiles.setdefault(key, copy.deepcopy(profile))
    return profiles


def _load_capability_profiles(path: str) -> dict[str, dict]:
    """Load and normalize capability profiles from *path* with mtime caching."""
    builtin_profiles = _builtin_capability_profiles_by_lookup_key()
    if not path:
        return builtin_profiles
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return builtin_profiles

    if (
        _capability_profile_cache.get("path") == path
        and _capability_profile_cache.get("mtime") == mtime
    ):
        return copy.deepcopy(_capability_profile_cache.get("profiles", {}))

    try:
        with open(path) as f:
            payload = json.load(f)
    except Exception:
        logger.warning("Failed to read model capability profiles from %s", path, exc_info=True)
        return builtin_profiles

    raw_profiles: Any
    if isinstance(payload, dict):
        raw_profiles = payload.get("profiles") or payload.get("models") or payload
    else:
        raw_profiles = payload

    items: list[dict] = []
    if isinstance(raw_profiles, list):
        items = [item for item in raw_profiles if isinstance(item, dict)]
    elif isinstance(raw_profiles, dict):
        for key, value in raw_profiles.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("model_key", key)
                items.append(item)

    profiles: dict[str, dict] = builtin_profiles
    for item in items:
        if item.get("benchmarkable") is False:
            continue
        normalized = _normalize_capability_profile(item, path)
        model_key = str(normalized.get("model_key") or "").strip()
        if not model_key:
            continue
        provider = normalized.get("provider")
        for key in _capability_profile_lookup_keys(model_key, provider):
            profiles[key] = copy.deepcopy(normalized)

    _capability_profile_cache.update({
        "path": path,
        "mtime": mtime,
        "profiles": copy.deepcopy(profiles),
    })
    return copy.deepcopy(profiles)


def get_model_capability_profile(model_key: str) -> dict:
    """Return the normalized capability profile for *model_key* if enabled.

    The parser tolerates the current benchmark profile shape and future added
    fields. It returns only the stable subset the assistant consumes.
    """
    if not is_capability_profiles_enabled():
        return {}
    profiles = _load_capability_profiles(get_capability_profile_path())
    for key in _capability_profile_lookup_keys(model_key):
        if key in profiles:
            return copy.deepcopy(profiles[key])
    return {}


def set_default_model(model_id: str, source: str = "") -> None:
    """Update ``ai.default_model`` and ``ai.default_model_source`` and persist."""
    settings = _get_settings()
    settings["ai"]["default_model"] = model_id
    settings["ai"]["default_model_source"] = source
    save_settings(settings)


def get_jupyter_port() -> int:
    """Return ``services.jupyter_port``."""
    return _get_settings()["services"]["jupyter_port"]


def get_model_proxy_port() -> int:
    """Return ``services.model_proxy_port``."""
    return _get_settings()["services"]["model_proxy_port"]


def get_ssh_command_line() -> str:
    """Return ``fabric.ssh_command_line``."""
    return _get_settings()["fabric"]["ssh_command_line"]


# ---------------------------------------------------------------------------
# Chameleon accessors
# ---------------------------------------------------------------------------


def is_chameleon_enabled() -> bool:
    """Return ``chameleon.enabled``."""
    return _get_settings().get("chameleon", {}).get("enabled", False)


def is_federated_enabled() -> bool:
    """Return whether the Federated Slice view is enabled."""
    views = _get_settings().get("views", {})
    return views.get("federated_enabled", views.get("composite_enabled", False))


def is_composite_enabled() -> bool:
    """Compatibility alias for the old view-toggle accessor."""
    return is_federated_enabled()


def get_chameleon_sites() -> dict:
    """Return ``chameleon.sites`` dict keyed by site name."""
    return _get_settings().get("chameleon", {}).get("sites", {})


def get_chameleon_site_config(site: str) -> dict:
    """Return config for a specific Chameleon site."""
    return get_chameleon_sites().get(site, {})


def get_chameleon_password_auth() -> dict:
    """Return shared Chameleon password-auth credentials."""
    return _get_settings().get("chameleon", {}).get("password_auth", {})


def get_chameleon_default_site() -> str:
    """Return ``chameleon.default_site``."""
    return _get_settings().get("chameleon", {}).get("default_site", "CHI@TACC")


def get_chameleon_default_key_name(site: str) -> str:
    """Return the configured default Nova keypair name for a Chameleon site."""
    return str(get_chameleon_site_config(site).get("default_key_name", "") or "").strip()


def resolve_chameleon_key_name(site: str, node: dict | None = None, fallback: str = "loomai-key") -> str:
    """Resolve the Nova keypair name for a Chameleon server.

    Per-node overrides win over the per-site default. If neither is set, the
    LoomAI-managed keypair remains the compatibility fallback.
    """
    node_key = str((node or {}).get("key_name", "") or "").strip()
    if node_key:
        return node_key
    site_key = get_chameleon_default_key_name(site)
    if site_key:
        return site_key
    return fallback


def get_chameleon_ssh_key() -> str:
    """Return Chameleon SSH key path, falling back to FABRIC slice key.

    Resolution order:
    1. ``chameleon.ssh_key_file`` from settings (if non-empty)
    2. Default FABRIC slice private key (via ``get_default_slice_key_path``)
    3. Empty string (caller should handle gracefully)
    """
    key = _get_settings().get("chameleon", {}).get("ssh_key_file", "")
    if key:
        return key
    # Fall back to default FABRIC slice private key
    from app.fablib_manager import get_default_slice_key_path
    try:
        config_dir = get_config_dir()
        priv_key, _pub_key = get_default_slice_key_path(config_dir)
        return priv_key
    except Exception:
        return ""


def is_chameleon_site_configured(site: str) -> bool:
    """Check if a Chameleon site has credentials configured."""
    cfg = get_chameleon_site_config(site)
    auth_type = cfg.get("auth_type", "application_credential")
    if auth_type == "password":
        password_auth = get_chameleon_password_auth()
        username = password_auth.get("username") or cfg.get("username", "")
        password = password_auth.get("password") or cfg.get("password", "")
        project_id = cfg.get("project_id", "") or password_auth.get("project_id", "")
        return bool(
            cfg.get("auth_url")
            and username
            and password
            and project_id
            and cfg.get("client_id")
        )
    return bool(cfg.get("app_credential_id") and cfg.get("app_credential_secret"))


# ---------------------------------------------------------------------------
# SPHERE / MergeTB accessors
# ---------------------------------------------------------------------------


def get_sphere_settings() -> dict:
    """Return the ``sphere`` settings block."""
    return _get_settings().get("sphere", {})


def is_sphere_enabled() -> bool:
    """Return ``sphere.enabled``."""
    return bool(get_sphere_settings().get("enabled", False))


def get_sphere_default_project() -> str:
    """Return ``sphere.default_project`` (may be empty)."""
    return str(get_sphere_settings().get("default_project", "") or "").strip()


def is_sphere_configured() -> bool:
    """True when SPHERE is enabled and has a token or username+password."""
    cfg = get_sphere_settings()
    if not cfg.get("enabled"):
        return False
    return bool(cfg.get("token")) or bool(cfg.get("username") and cfg.get("password"))


# ---------------------------------------------------------------------------
# Derived file generation
# ---------------------------------------------------------------------------


def generate_fabric_rc(settings: dict) -> None:
    """Write ``fabric_rc`` into the config directory from *settings*."""
    from app.fablib_manager import get_default_slice_key_path

    paths = settings["paths"]
    fabric = settings["fabric"]
    hosts = fabric["hosts"]
    ai = settings["ai"]
    # Live root config dir (symlink to active user), not the stale stored path.
    config_dir = _live_config_dir()

    # Resolve actual default slice key paths (handles key set default logic)
    try:
        priv_key_path, pub_key_path = get_default_slice_key_path(config_dir)
    except Exception:
        # Fallback to nominal paths if key resolution fails
        slice_keys_dir = paths["slice_keys_dir"]
        priv_key_path = os.path.join(slice_keys_dir, "default", "slice_key")
        pub_key_path = os.path.join(slice_keys_dir, "default", "slice_key.pub")

    avoid_str = ",".join(fabric.get("avoid_sites", []))

    # Resolve {config_dir} placeholder in ssh_command_line
    ssh_cmd = fabric.get("ssh_command_line", "").replace("{config_dir}", config_dir)

    ai_renci_key = _resolve_ai_renci_api_key(ai)

    lines = [
        f"export FABRIC_CREDMGR_HOST={hosts.get('credmgr', 'cm.fabric-testbed.net')}",
        f"export FABRIC_ORCHESTRATOR_HOST={hosts.get('orchestrator', 'orchestrator.fabric-testbed.net')}",
        f"export FABRIC_CORE_API_HOST={hosts.get('core_api', 'uis.fabric-testbed.net')}",
        f"export FABRIC_AM_HOST={hosts.get('artifact_manager', 'artifacts.fabric-testbed.net')}",
        f"export FABRIC_TOKEN_LOCATION={os.path.join(config_dir, 'id_token.json')}",
        f"export FABRIC_BASTION_HOST={hosts.get('bastion', 'bastion.fabric-testbed.net')}",
        f"export FABRIC_BASTION_USERNAME={fabric.get('bastion_username', '')}",
        f"export FABRIC_BASTION_KEY_LOCATION={os.path.join(config_dir, 'fabric_bastion_key')}",
        f"export FABRIC_BASTION_SSH_CONFIG_FILE={os.path.join(config_dir, 'ssh_config')}",
        f"export FABRIC_SLICE_PUBLIC_KEY_FILE={pub_key_path}",
        f"export FABRIC_SLICE_PRIVATE_KEY_FILE={priv_key_path}",
        f"export FABRIC_PROJECT_ID={fabric.get('project_id', '')}",
        f"export FABRIC_LOG_LEVEL={fabric.get('logging', {}).get('level', 'INFO')}",
        f"export FABRIC_LOG_FILE={paths.get('log_file', '/tmp/fablib/fablib.log')}",
        f"export FABRIC_AVOID={avoid_str}",
        f'export FABRIC_SSH_COMMAND_LINE="{ssh_cmd}"',
        f"export FABRIC_AI_API_KEY={ai.get('fabric_api_key', '')}",
        f"export AI_RENCI_API_KEY={ai_renci_key}",
        f"export NRP_API_KEY={ai.get('nrp_api_key', '')}",
    ]
    for provider in ai.get("custom_providers") or []:
        if not isinstance(provider, dict):
            continue
        name = str(provider.get("name") or "custom").strip()
        if not name:
            continue
        lines.append(f"export {custom_provider_base_url_env_key(name)}={provider.get('base_url', '')}")
        lines.append(f"export {custom_provider_env_key(name)}={provider.get('api_key', '')}")

    rc_content = "\n".join(lines) + "\n"
    rc_path = os.path.join(config_dir, "fabric_rc")
    os.makedirs(config_dir, exist_ok=True)
    _atomic_write_text(rc_path, rc_content)
    logger.debug("Wrote fabric_rc to %s", rc_path)


def generate_ssh_config(settings: dict) -> None:
    """Write ``ssh_config`` into the config directory from *settings*."""
    fabric = settings["fabric"]
    config_dir = _live_config_dir()
    bastion_username = fabric.get("bastion_username", "")
    bastion_key_file = os.path.join(config_dir, "fabric_bastion_key")

    content = f"""\
UserKnownHostsFile /dev/null
StrictHostKeyChecking no
ServerAliveInterval 120

Host bastion.fabric-testbed.net
    User {bastion_username}
    ForwardAgent yes
    Hostname %h
    IdentityFile {bastion_key_file}
    IdentitiesOnly yes

Host * !bastion.fabric-testbed.net
    ProxyJump {bastion_username}@bastion.fabric-testbed.net:22
"""

    ssh_config_path = os.path.join(config_dir, "ssh_config")
    os.makedirs(config_dir, exist_ok=True)
    _atomic_write_text(ssh_config_path, content)
    logger.debug("Wrote ssh_config to %s", ssh_config_path)


def apply_env_vars(settings: dict) -> None:
    """Set ``os.environ`` entries from *settings* so FABlib and subprocesses inherit them."""
    paths = settings["paths"]
    fabric = settings["fabric"]
    ai = settings["ai"]

    # Config-derived paths are computed from the live root ``fabric_config``
    # symlink, NOT the (possibly stale) per-user absolute paths stored in
    # settings.json — those go stale across user switches / storage relocation.
    live_config = _live_config_dir()

    ai_renci_key = _resolve_ai_renci_api_key(ai)

    env_map = {
        # NOTE: FABRIC_STORAGE_DIR is deliberately NOT set here. It is the flat
        # root (set once by the container) and must never be overwritten with a
        # per-user path — doing so makes users_base_dir()/get_root_storage_dir()
        # resolve under the active user's folder and recursively nest per-user
        # storage. Per-user resolution happens via the registry + root symlinks.
        "FABRIC_CONFIG_DIR": live_config,
        "FABRIC_PROJECT_ID": fabric.get("project_id", ""),
        "FABRIC_BASTION_USERNAME": fabric.get("bastion_username", ""),
        "FABRIC_BASTION_HOST": fabric.get("hosts", {}).get("bastion", ""),
        "FABRIC_CREDMGR_HOST": fabric.get("hosts", {}).get("credmgr", ""),
        "FABRIC_ORCHESTRATOR_HOST": fabric.get("hosts", {}).get("orchestrator", ""),
        "FABRIC_CORE_API_HOST": fabric.get("hosts", {}).get("core_api", ""),
        "FABRIC_AM_HOST": fabric.get("hosts", {}).get("artifact_manager", ""),
        "FABRIC_TOKEN_LOCATION": os.path.join(live_config, "id_token.json"),
        "FABRIC_BASTION_KEY_LOCATION": os.path.join(live_config, "fabric_bastion_key"),
        "FABRIC_BASTION_SSH_CONFIG_FILE": os.path.join(live_config, "ssh_config"),
        "FABRIC_LOG_LEVEL": fabric.get("logging", {}).get("level", "INFO"),
        "FABRIC_LOG_FILE": paths.get("log_file", ""),
        "FABRIC_AVOID": ",".join(fabric.get("avoid_sites", [])),
        "FABRIC_AI_API_KEY": ai.get("fabric_api_key", ""),
        "AI_RENCI_API_KEY": ai_renci_key,
        "NRP_API_KEY": ai.get("nrp_api_key", ""),
    }
    for provider in ai.get("custom_providers") or []:
        if not isinstance(provider, dict):
            continue
        name = str(provider.get("name") or "custom").strip()
        if not name:
            continue
        env_map[custom_provider_base_url_env_key(name)] = provider.get("base_url", "")
        env_map[custom_provider_env_key(name)] = provider.get("api_key", "")

    ssh_cmd = fabric.get("ssh_command_line", "")
    if ssh_cmd:
        env_map["FABRIC_SSH_COMMAND_LINE"] = ssh_cmd.replace("{config_dir}", live_config)

    for key, value in env_map.items():
        if value:
            os.environ[key] = str(value)


# ---------------------------------------------------------------------------
# Legacy migration
# ---------------------------------------------------------------------------


def migrate_from_legacy() -> dict:
    """Parse existing ``fabric_rc`` and ``.ai_tools.json`` into a new ``settings.json``.

    Returns the migrated settings dict (also saved to disk).
    """
    settings = get_default_settings()
    storage_dir = get_storage_dir()
    config_dir = os.path.join(storage_dir, "fabric_config")

    # --- Parse fabric_rc ---
    rc_path = os.path.join(config_dir, "fabric_rc")
    if os.path.isfile(rc_path):
        logger.info("Migrating settings from %s", rc_path)
        rc_vars: Dict[str, str] = {}
        with open(rc_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export ") and "=" in line:
                    kv = line[len("export "):]
                    key, _, value = kv.partition("=")
                    rc_vars[key.strip()] = value.strip()

        # Map fabric_rc keys to settings paths
        _rc_host_map = {
            "FABRIC_CREDMGR_HOST": "credmgr",
            "FABRIC_ORCHESTRATOR_HOST": "orchestrator",
            "FABRIC_CORE_API_HOST": "core_api",
            "FABRIC_AM_HOST": "artifact_manager",
            "FABRIC_BASTION_HOST": "bastion",
        }
        for env_key, host_key in _rc_host_map.items():
            if env_key in rc_vars:
                settings["fabric"]["hosts"][host_key] = rc_vars[env_key]

        if "FABRIC_BASTION_USERNAME" in rc_vars:
            settings["fabric"]["bastion_username"] = rc_vars["FABRIC_BASTION_USERNAME"]

        if "FABRIC_PROJECT_ID" in rc_vars:
            settings["fabric"]["project_id"] = rc_vars["FABRIC_PROJECT_ID"]

        if "FABRIC_LOG_LEVEL" in rc_vars:
            settings["fabric"]["logging"]["level"] = rc_vars["FABRIC_LOG_LEVEL"]

        if "FABRIC_LOG_FILE" in rc_vars:
            settings["paths"]["log_file"] = rc_vars["FABRIC_LOG_FILE"]

        if "FABRIC_AVOID" in rc_vars:
            avoid_str = rc_vars["FABRIC_AVOID"]
            if avoid_str:
                settings["fabric"]["avoid_sites"] = [
                    s.strip() for s in avoid_str.split(",") if s.strip()
                ]
            else:
                settings["fabric"]["avoid_sites"] = []

        if "FABRIC_SSH_COMMAND_LINE" in rc_vars:
            ssh_val = rc_vars["FABRIC_SSH_COMMAND_LINE"]
            # Strip surrounding quotes if present
            if (ssh_val.startswith('"') and ssh_val.endswith('"')) or \
               (ssh_val.startswith("'") and ssh_val.endswith("'")):
                ssh_val = ssh_val[1:-1]
            settings["fabric"]["ssh_command_line"] = ssh_val

        if "FABRIC_AI_API_KEY" in rc_vars:
            settings["ai"]["fabric_api_key"] = rc_vars["FABRIC_AI_API_KEY"]

        if "NRP_API_KEY" in rc_vars:
            settings["ai"]["nrp_api_key"] = rc_vars["NRP_API_KEY"]

    # --- Parse .ai_tools.json ---
    ai_tools_path = os.path.join(storage_dir, ".ai_tools.json")
    if os.path.isfile(ai_tools_path):
        logger.info("Migrating AI tool toggles from %s", ai_tools_path)
        try:
            with open(ai_tools_path) as f:
                tools_data = json.load(f)
            if isinstance(tools_data, dict):
                default_tools = settings["ai"]["tools"]
                for k in default_tools:
                    if k in tools_data:
                        default_tools[k] = bool(tools_data[k])
        except Exception:
            logger.warning("Failed to parse %s", ai_tools_path, exc_info=True)

    # Write the migrated settings
    save_settings(settings)
    logger.info("Legacy migration complete — settings.json written to %s", get_settings_path())
    return settings


# ---------------------------------------------------------------------------
# Tool config management
# ---------------------------------------------------------------------------


def get_tool_config_dir(tool: str) -> str:
    """Return ``{settings_dir}/tools/{tool}/``, creating it if needed."""
    d = os.path.join(get_settings_dir(), _TOOLS_SUBDIR, tool)
    os.makedirs(d, exist_ok=True)
    return d


def seed_tool_configs() -> None:
    """Copy default tool configs from the Docker image to ``.loomai/tools/``.

    For each tool directory in ``_DOCKER_AI_TOOLS_DIR``, copies its contents
    to ``.loomai/tools/{tool}/`` only if that target directory does not
    already exist (preserves user customizations).
    """
    if not os.path.isdir(_DOCKER_AI_TOOLS_DIR):
        logger.debug("Docker AI tools dir %s not found — skipping seed", _DOCKER_AI_TOOLS_DIR)
        return

    for entry in os.listdir(_DOCKER_AI_TOOLS_DIR):
        src = os.path.join(_DOCKER_AI_TOOLS_DIR, entry)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(get_settings_dir(), _TOOLS_SUBDIR, entry)
        if os.path.exists(dst):
            logger.debug("Tool config for %s already exists — skipping", entry)
            continue
        try:
            shutil.copytree(src, dst)
            logger.info("Seeded tool config for %s from %s", entry, src)
        except Exception:
            logger.warning("Failed to seed tool config for %s", entry, exc_info=True)


def reset_tool_config(tool: str) -> None:
    """Delete ``.loomai/tools/{tool}/`` and re-copy from the Docker image.

    Raises ``FileNotFoundError`` if the tool has no default config in the
    Docker image.
    """
    src = os.path.join(_DOCKER_AI_TOOLS_DIR, tool)
    if not os.path.isdir(src):
        raise FileNotFoundError(
            f"No default config for tool '{tool}' in {_DOCKER_AI_TOOLS_DIR}"
        )

    dst = os.path.join(get_settings_dir(), _TOOLS_SUBDIR, tool)
    if os.path.exists(dst):
        shutil.rmtree(dst)

    shutil.copytree(src, dst)
    logger.info("Reset tool config for %s from %s", tool, src)


def get_tool_config_status() -> List[Dict[str, Any]]:
    """Return a list of dicts describing each tool's config status.

    Each dict contains:
    - ``tool`` (str): tool name
    - ``has_config`` (bool): whether a config directory exists in ``.loomai/tools/``
    - ``files`` (list[str]): list of filenames in the config directory
    """
    tools_dir = os.path.join(get_settings_dir(), _TOOLS_SUBDIR)
    result: List[Dict[str, Any]] = []

    # Collect tool names from both Docker defaults and user configs
    tool_names: set[str] = set()
    if os.path.isdir(_DOCKER_AI_TOOLS_DIR):
        for entry in os.listdir(_DOCKER_AI_TOOLS_DIR):
            if os.path.isdir(os.path.join(_DOCKER_AI_TOOLS_DIR, entry)):
                tool_names.add(entry)
    if os.path.isdir(tools_dir):
        for entry in os.listdir(tools_dir):
            if os.path.isdir(os.path.join(tools_dir, entry)):
                tool_names.add(entry)

    for name in sorted(tool_names):
        tool_dir = os.path.join(tools_dir, name)
        has_config = os.path.isdir(tool_dir)
        files: List[str] = []
        if has_config:
            try:
                files = sorted(os.listdir(tool_dir))
            except OSError:
                pass
        result.append({
            "tool": name,
            "has_config": has_config,
            "files": files,
        })

    return result
