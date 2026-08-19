"""Network-service hard limit coverage for AI assets and harness context."""

from __future__ import annotations

import json
from pathlib import Path

from app.chat_prompt import LOOMAI_MODE_PROMPT
import app.harness_config as harness_config


ROOT = Path(__file__).resolve().parents[3]
ASSET_MIRRORS = (ROOT / "backend" / "ai-tools", ROOT / "ai-tools")


def test_shared_assets_carry_fabric_network_service_limits() -> None:
    for asset_root in ASSET_MIRRORS:
        fabric_ai = (asset_root / "shared" / "FABRIC_AI.md").read_text(encoding="utf-8")
        operator = (asset_root / "shared" / "agents" / "fabric-slice-operator.md").read_text(encoding="utf-8")

        assert "FABRIC Network Service Limits" in fabric_ai
        assert "FABNet service is PER-SITE" in fabric_ai
        assert "up to 255 VMs per service" in fabric_ai
        assert "never one\nFABNetv4 network mixing sites" in fabric_ai
        assert "FABNetv4/v6/Ext | all attached VMs at one site" in operator


def test_fablib_rag_example_indexes_multisite_fabnet_limit() -> None:
    for asset_root in ASSET_MIRRORS:
        index = json.loads((asset_root / "fablib-examples" / "INDEX.json").read_text(encoding="utf-8"))
        entry = next(item for item in index if item["file"] == "networking/multisite_fabnet_per_site.py")

        assert "network-service-limits" in entry["tags"]
        assert "one-site, 255-VM hard limit" in entry["description"]

        example = (asset_root / "fablib-examples" / entry["file"]).read_text(encoding="utf-8")
        assert "WRONG: one FABNetv4 service spanning multiple sites" in example
        assert "RIGHT: use add_fabnet once per node" in example
        assert "one FABNet service per site" in example


def test_harness_shared_context_includes_network_limits() -> None:
    fabric_ai = (ROOT / "backend" / "ai-tools" / "shared" / "FABRIC_AI.md").read_text(encoding="utf-8")
    context = harness_config._shared_context(fabric_ai)

    assert "FABRIC Network Service Limits" in context
    assert "FABNet service is PER-SITE" in context
    assert "per-node FABNet attachment (`add_fabnet` once per node)" in context


def test_assistant_prompt_includes_network_limit_table() -> None:
    assert "## Network Service Limits" in LOOMAI_MODE_PROMPT
    assert "| L2Bridge | all interfaces at one site |" in LOOMAI_MODE_PROMPT
    assert "| FABNetv4/v6/Ext | all attached VMs at one site, up to 255 VMs |" in LOOMAI_MODE_PROMPT
    assert "Do not create one FABNet network that mixes sites" in LOOMAI_MODE_PROMPT
