"""Comprehensive help text tests — every command and subcommand."""

import pytest


# (args, expected_strings_in_output)
HELP_CASES = [
    # Root
    (["--help"], ["slices", "nodes", "sites"]),
    # Slices
    (["slices", "--help"], ["list", "show", "create", "delete", "submit", "archive"]),
    (["slices", "list", "--help"], ["--state"]),
    (["slices", "show", "--help"], ["NAME"]),
    (["slices", "create", "--help"], ["NAME"]),
    (["slices", "delete", "--help"], ["--force"]),
    (["slices", "submit", "--help"], ["--wait", "--timeout"]),
    (["slices", "modify", "--help"], ["--wait", "--timeout"]),
    (["slices", "validate", "--help"], ["NAME"]),
    (["slices", "renew", "--help"], ["--days"]),
    (["slices", "refresh", "--help"], ["NAME"]),
    (["slices", "slivers", "--help"], ["NAME"]),
    (["slices", "wait", "--help"], ["--timeout"]),
    (["slices", "clone", "--help"], ["--new-name"]),
    (["slices", "export", "--help"], ["NAME"]),
    (["slices", "import", "--help"], ["FILE"]),
    (["slices", "archive", "--help"], ["--all-terminal", "--force"]),
    # Nodes
    (["nodes", "--help"], ["add", "update", "remove"]),
    (["nodes", "add", "--help"], ["--site", "--cores", "--ram"]),
    (["nodes", "update", "--help"], ["SLICE_NAME"]),
    (["nodes", "remove", "--help"], ["SLICE_NAME"]),
    # Networks
    (["networks", "--help"], ["add", "update", "remove"]),
    (["networks", "add", "--help"], ["--type", "--interfaces"]),
    # Components
    (["components", "--help"], ["add", "remove"]),
    (["components", "add", "--help"], ["--model"]),
    # Sites
    (["sites", "--help"], ["list", "show", "hosts", "find"]),
    (["sites", "list", "--help"], ["--available"]),
    (["sites", "find", "--help"], ["--cores"]),
    # Facility ports
    (["facility-ports", "--help"], ["list", "add", "remove"]),
    (["facility-ports", "add", "--help"], ["--site", "--vlan", "--bandwidth"]),
    (["facility-ports", "remove", "--help"], ["SLICE_NAME", "FP_NAME"]),
    (["facility-ports", "list", "--help"], []),
    # SSH & exec
    (["ssh", "--help"], ["SLICE_NAME"]),
    (["exec", "--help"], ["--all", "--parallel"]),
    # SCP & rsync
    (["scp", "--help"], ["--download", "--all"]),
    (["rsync", "--help"], ["--all", "--parallel"]),
    # Weaves
    (["weaves", "--help"], ["list", "show", "run", "stop", "logs"]),
    (["weaves", "run", "--help"], ["--args"]),
    # Boot config
    (["boot-config", "--help"], ["show", "set", "run", "log"]),
    (["boot-config", "set", "--help"], ["--command", "--from-file"]),
    (["boot-config", "show", "--help"], ["SLICE_NAME", "NODE_NAME"]),
    # Artifacts
    (["artifacts", "--help"], ["list", "search", "show", "get", "publish",
                               "versions", "push-version", "delete-version"]),
    (["artifacts", "versions", "--help"], ["UUID"]),
    (["artifacts", "push-version", "--help"], ["UUID", "DIR_NAME"]),
    (["artifacts", "delete-version", "--help"], ["UUID", "VERSION_UUID", "--force"]),
    (["artifacts", "publish", "--help"], ["--title", "--description"]),
    (["artifacts", "tags", "--help"], []),
    # Recipes
    (["recipes", "--help"], ["list", "show", "run"]),
    # VM templates
    (["vm-templates", "--help"], ["list", "show"]),
    # Monitor
    (["monitor", "--help"], ["enable", "disable", "status", "metrics"]),
    # Config / projects / keys
    (["config", "--help"], ["show"]),
    (["projects", "--help"], ["list", "switch"]),
    (["keys", "--help"], ["list", "generate"]),
    # AI
    (["ai", "--help"], ["chat", "models", "agents"]),
    (["ai", "chat", "--help"], ["--model"]),
    # Completions
    (["completions", "--help"], ["bash", "zsh", "fish"]),
    # Images / component-models
    (["images", "--help"], []),
    (["component-models", "--help"], []),
]


@pytest.mark.parametrize("args,expected", HELP_CASES,
                         ids=[" ".join(a) for a, _ in HELP_CASES])
def test_help(invoke, args, expected):
    result = invoke(*args, "--help") if "--help" not in args else invoke(*args)
    assert result.exit_code == 0, f"Failed: {args}\n{result.output}"
    for s in expected:
        assert s in result.output, f"Missing '{s}' in help for {args}"
