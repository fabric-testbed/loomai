"""Multi-step operation templates for common FABRIC tasks.

When the user asks for a complex operation (e.g., "create a 2-node slice"),
the template system breaks it into steps that LoomAI can execute sequentially.
"""

from __future__ import annotations

import re
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "create_multi_node_slice",
        "pattern": re.compile(
            r"create\s+(?:a\s+)?(\d+)[- ]?node\s+(?:slice|cluster)\s*"
            r"(?:(?:at|on)\s+(\w+))?\s*(?:(?:called|named)\s+['\"]?(\S+?)['\"]?)?",
            re.IGNORECASE,
        ),
        "description": "Create a multi-node slice with networking",
        "build_steps": lambda m: _build_multi_node_steps(
            int(m.group(1)),
            m.group(2),  # site (optional)
            m.group(3),  # name (optional)
        ),
        "confirm": True,
    },
    {
        "name": "deploy_hello_fabric",
        "pattern": re.compile(
            r"(?:run|deploy|load)\s+(?:the\s+)?hello[_ ]?fabric",
            re.IGNORECASE,
        ),
        "description": "Deploy the Hello FABRIC weave",
        "build_steps": lambda m: [
            ("load_template", {"template_name": "Hello_FABRIC", "slice_name": "hello-fabric"}),
            ("submit_slice", {"slice_name": "hello-fabric", "wait": True}),
        ],
        "confirm": True,
    },
    {
        "name": "delete_dead_slices",
        "pattern": re.compile(
            r"(?:delete|remove|clean\s*up)\s+(?:all\s+)?(?:my\s+)?dead\s+slices?",
            re.IGNORECASE,
        ),
        "description": "Delete all slices in Dead state",
        "build_steps": lambda m: [
            ("list_slices", {}),
            # Subsequent steps determined dynamically after list_slices
        ],
        "confirm": True,
        "dynamic": True,  # Steps built from first tool's results
    },
    {
        "name": "find_gpu_sites",
        "pattern": re.compile(
            r"(?:find|show|which|what)\s+sites?\s+(?:have|with)\s+(\w+)\s*(?:gpu)?",
            re.IGNORECASE,
        ),
        "description": "Find sites with specific hardware",
        "build_steps": lambda m: [
            ("query_sites", {}),
        ],
        "confirm": False,
    },
]


def _build_multi_node_steps(
    node_count: int, site: str | None, name: str | None,
) -> list[tuple[str, dict]]:
    """Build steps for creating a multi-node slice."""
    slice_name = name or "my-slice"
    site = site or "auto"
    node_count = min(node_count, 10)  # Cap at 10 nodes

    steps: list[tuple[str, dict]] = [
        ("create_slice", {"name": slice_name}),
    ]

    for i in range(node_count):
        node_name = f"node{i + 1}"
        steps.append(("add_node", {
            "slice_name": slice_name,
            "name": node_name,
            "site": site.upper() if site != "auto" else "auto",
            "cores": 2,
            "ram": 8,
            "disk": 50,
            "image": "default_ubuntu_22",
        }))

    # Add a network if 2+ nodes
    if node_count >= 2:
        steps.append(("add_network", {
            "slice_name": slice_name,
            "name": "net1",
            "type": "FABNetv4",
        }))

    return steps


def match_template(message: str) -> Optional[dict]:
    """Match a user message against operation templates.

    Returns a dict with: name, description, steps, confirm
    or None if no match.
    """
    for template in TEMPLATES:
        match = template["pattern"].search(message)
        if match:
            steps = template["build_steps"](match)
            logger.info("Template matched: %s from '%s'", template["name"], message[:50])
            return {
                "name": template["name"],
                "description": template["description"],
                "steps": steps,
                "confirm": template.get("confirm", True),
                "dynamic": template.get("dynamic", False),
            }
    return None
