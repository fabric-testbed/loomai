"""Contract-test support endpoints.

These endpoints are mounted only when ``LOOMAI_CONTRACT_MODE=1``. They provide
deterministic setup/teardown for backend contract tests without exposing test
controls in normal deployments.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.fabric_call_manager import CacheEntry, get_call_manager
from app.fablib_manager import get_fablib, reset_fablib
from app.graph_builder import build_graph
from app.slice_serializer import slice_to_dict

router = APIRouter(prefix="/api/__test", tags=["contract-test"])


FABRIC_SEED_SLICE = "contract-fabric-slice"
FABRIC_SEED_NODE = "fabric-node-1"
CHAMELEON_SEED_SLICE = "chi-contract-slice"
CHAMELEON_SEED_NODE = "chi-node-1"


def _contract_mode() -> bool:
    return os.environ.get("LOOMAI_CONTRACT_MODE", "").strip() == "1"


def _require_contract_mode() -> None:
    if not _contract_mode():
        raise HTTPException(status_code=404, detail="Not found")


def _ensure_contract_files() -> None:
    """Create minimal config files expected by shared app helpers."""
    os.environ.setdefault("FABRIC_PROJECT_ID", "contract-project")
    storage_dir = os.environ.get("FABRIC_STORAGE_DIR", "/tmp/loomai-contract")
    config_dir = os.environ.get("FABRIC_CONFIG_DIR", os.path.join(storage_dir, "fabric_config"))
    token_file = os.environ.get("FABRIC_TOKEN_FILE", os.path.join(config_dir, "id_token.json"))
    os.environ["FABRIC_STORAGE_DIR"] = storage_dir
    os.environ["FABRIC_CONFIG_DIR"] = config_dir
    os.environ["FABRIC_TOKEN_FILE"] = token_file

    os.makedirs(config_dir, exist_ok=True)
    os.makedirs(os.path.dirname(token_file), exist_ok=True)
    if not os.path.isfile(token_file):
        with open(token_file, "w") as f:
            json.dump({"id_token": "contract-token"}, f)

    fabric_rc = os.path.join(config_dir, "fabric_rc")
    if not os.path.isfile(fabric_rc):
        with open(fabric_rc, "w") as f:
            f.write(f"export FABRIC_PROJECT_ID={os.environ['FABRIC_PROJECT_ID']}\n")
            f.write(f"export FABRIC_TOKEN_LOCATION={token_file}\n")

    key_dir = os.path.join(config_dir, "slice_keys", "default")
    os.makedirs(key_dir, exist_ok=True)
    private_key = os.path.join(key_dir, "slice_key")
    public_key = os.path.join(key_dir, "slice_key.pub")
    if not os.path.isfile(private_key):
        with open(private_key, "w") as f:
            f.write("contract-private-key\n")
        os.chmod(private_key, 0o600)
    if not os.path.isfile(public_key):
        with open(public_key, "w") as f:
            f.write("contract-public-key\n")


def _clear_contract_storage() -> None:
    """Clear contract-mode persistence under the configured /tmp root."""
    storage_dir = os.path.abspath(os.environ.get("FABRIC_STORAGE_DIR", "/tmp/loomai-contract"))
    if not storage_dir.startswith("/tmp/loomai-contract"):
        return
    for rel in ("my_slices", "my_artifacts", ".loomai"):
        path = os.path.join(storage_dir, rel)
        if os.path.isdir(path):
            shutil.rmtree(path)
    os.makedirs(os.path.join(storage_dir, "my_slices"), exist_ok=True)
    os.makedirs(os.path.join(storage_dir, "my_artifacts"), exist_ok=True)
    os.makedirs(os.path.join(storage_dir, ".loomai"), exist_ok=True)


def _clear_fabric_route_state() -> None:
    from app.routes import slices

    with slices._draft_lock:
        slices._draft_slices.clear()
        slices._draft_is_new.clear()
        slices._draft_site_groups.clear()
        slices._draft_ip_hints.clear()
        slices._draft_l3_config.clear()
        slices._draft_project_id.clear()
        # _serialize_cache was removed in the large-slice refresh refactor; the
        # read-model caches it replaced are invalidated by slices._invalidate_slice_read_caches.

    from app.user_context import get_slices_dir

    registry_path = os.path.join(get_slices_dir(), "registry.json")
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)
    with open(registry_path, "w") as f:
        json.dump({"slices": {}}, f)


def _clear_chameleon_state() -> None:
    from app.routes import chameleon

    with chameleon._chameleon_slices_lock:
        chameleon._chameleon_slices.clear()
        chameleon._persist_slices()


def _clear_federated_state() -> None:
    from app.routes import composite

    composite._composite_slices.clear()
    composite._persist()


def _serialized_fabric_seed() -> dict[str, Any]:
    fablib = get_fablib()
    seed = fablib.seed_slice(
        name=FABRIC_SEED_SLICE,
        slice_id=FABRIC_SEED_SLICE,
        node_name=FABRIC_SEED_NODE,
    )
    data = slice_to_dict(seed)
    return {**data, "graph": build_graph(data)}


def _seed_fabric() -> dict[str, Any]:
    from app.slice_registry import register_slice

    data = _serialized_fabric_seed()
    register_slice(
        FABRIC_SEED_SLICE,
        uuid=FABRIC_SEED_SLICE,
        state="StableOK",
        project_id=os.environ.get("FABRIC_PROJECT_ID", "contract-project"),
    )

    mgr = get_call_manager()
    entry = CacheEntry(data=data, timestamp=time.time())
    mgr._cache[f"slice:{FABRIC_SEED_SLICE}"] = entry
    return {
        "slice_id": FABRIC_SEED_SLICE,
        "name": FABRIC_SEED_SLICE,
        "node": FABRIC_SEED_NODE,
    }


def _seed_chameleon() -> dict[str, Any]:
    from app.routes import chameleon

    now = "2026-06-08T00:00:00+00:00"
    chameleon_slice = {
        "id": CHAMELEON_SEED_SLICE,
        "name": CHAMELEON_SEED_SLICE,
        "provider": "chameleon",
        "state": "Active",
        "created": now,
        "updated": now,
        "site": "CHI@TACC",
        "sites": ["CHI@TACC"],
        "nodes": [
            {
                "id": "chi-contract-node-1",
                "name": CHAMELEON_SEED_NODE,
                "node_type": "compute_haswell",
                "image": "CC-Ubuntu22.04",
                "count": 1,
                "site": "CHI@TACC",
                "interfaces": [
                    {"nic": 0, "network": {"id": "sharednet1-id", "name": "sharednet1"}},
                    {"nic": 1, "network": {"id": "_fabnetv4", "name": "fabnetv4"}},
                ],
            }
        ],
        "networks": [
            {
                "id": "sharednet1-id",
                "name": "sharednet1",
                "connected_nodes": ["chi-contract-node-1"],
                "site": "CHI@TACC",
            }
        ],
        "floating_ips": [{"node_id": "chi-contract-node-1", "nic": 0}],
        "resources": [
            {
                "resource_id": "res-contract-lease-1",
                "provider": "chameleon",
                "type": "lease",
                "id": "contract-lease-1",
                "provider_id": "contract-lease-1",
                "name": "contract-lease",
                "site": "CHI@TACC",
                "status": "ACTIVE",
                "ownership": "imported",
                "managed": False,
                "created_by": "external",
                "delete_with_slice": False,
                "attached_at": now,
            }
        ],
    }
    with chameleon._chameleon_slices_lock:
        chameleon._chameleon_slices[CHAMELEON_SEED_SLICE] = chameleon_slice
        chameleon._persist_slices()
    return {
        "slice_id": CHAMELEON_SEED_SLICE,
        "name": CHAMELEON_SEED_SLICE,
        "node": CHAMELEON_SEED_NODE,
    }


@router.post("/reset")
async def reset_contract_state() -> dict[str, Any]:
    _require_contract_mode()
    _ensure_contract_files()
    _clear_contract_storage()

    from app import settings_manager
    from app.chameleon_manager import reset_sessions

    settings_manager.invalidate_settings_cache()
    reset_sessions()
    reset_fablib()

    get_call_manager()._cache.clear()
    _clear_fabric_route_state()
    _clear_chameleon_state()
    _clear_federated_state()

    return {"status": "reset"}


@router.post("/seed")
async def seed_contract_state(body: dict | None = Body(None)) -> dict[str, Any]:
    _require_contract_mode()
    _ensure_contract_files()
    body = body or {}
    scenario = body.get("scenario", "federated-one-of-each")
    if scenario != "federated-one-of-each":
        raise HTTPException(400, f"Unknown contract seed scenario: {scenario}")

    fabric = _seed_fabric()
    chameleon = _seed_chameleon()
    return {
        "scenario": scenario,
        "fabric": fabric,
        "chameleon": chameleon,
    }
