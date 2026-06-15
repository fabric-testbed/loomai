"""Regression tests for CLI roadmap work."""

import json
from unittest.mock import patch


def test_format_after_subcommand(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = [{"name": "slice-a", "id": "id-a", "state": "StableOK"}]
        result = runner.invoke(cli, ["slices", "list", "--format", "json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed[0]["name"] == "slice-a"


def test_status_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"status": "ok", "checks": {"settings": {"ok": True}}}
        result = runner.invoke(cli, ["status", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["status"] == "ok"


def test_ai_rag_search_table(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "query": "hello fabric",
            "count": 1,
            "hits": [
                {
                    "score": 0.9,
                    "source_type": "weave",
                    "source_path": "Hello_FABRIC",
                    "section": "overview",
                    "preview": "Create a basic FABRIC slice.",
                }
            ],
        }
        result = runner.invoke(cli, ["ai", "rag", "search", "hello fabric"])

    assert result.exit_code == 0
    assert "Hello_FABRIC" in result.output
    assert "0.9" in result.output


def test_ai_models_default_set(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"default": "qwen3-coder-30b", "source": "fabric"}
        result = runner.invoke(cli, [
            "ai", "models", "set-default", "qwen3-coder-30b", "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["default"] == "qwen3-coder-30b"


def test_schedule_next_available_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "available_now": [{"site": "TACC", "cores_available": 100, "ram_available": 512}],
            "available_soon": [],
            "not_available": [],
        }
        result = runner.invoke(cli, [
            "schedule", "next-available", "--cores", "4", "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["available_now"][0]["site"] == "TACC"


def test_schedule_reservation_create(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "id": "res-1",
            "slice_name": "slice-a",
            "scheduled_time": "2026-06-15T14:00:00Z",
            "duration_hours": 24,
            "auto_submit": True,
        }
        result = runner.invoke(cli, [
            "schedule", "reservations", "create",
            "slice-a", "2026-06-15T14:00:00Z", "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["id"] == "res-1"


def test_slice_state_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"name": "slice-a", "state": "StableOK"}
        result = runner.invoke(cli, ["slices", "state", "slice-a", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["state"] == "StableOK"


def test_slice_resolve_sites_override(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"name": "slice-a", "state": "Draft"}
        result = runner.invoke(cli, [
            "slices", "resolve-sites", "slice-a",
            "--override", "@edge=TACC",
            "--all",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["name"] == "slice-a"
    assert mock.call_args.kwargs["json"]["group_overrides"] == {"@edge": "TACC"}


def test_network_ip_hints_set_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "network": "fabnet",
            "hints": {"node1-nic1-p1": {"ip": "10.128.1.10"}},
            "status": "ok",
        }
        result = runner.invoke(cli, [
            "networks", "ip-hints", "set", "slice-a", "fabnet",
            "--ip", "node1-nic1-p1=10.128.1.10",
            "--format", "json",
        ])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["hints"]["node1-nic1-p1"]["ip"] == "10.128.1.10"


def test_network_l3_config_set_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "network": "fabnet",
            "l3_config": {"mode": "user_octet", "route_mode": "custom"},
            "status": "ok",
        }
        result = runner.invoke(cli, [
            "networks", "l3-config", "set", "slice-a", "fabnet",
            "--mode", "user_octet",
            "--route-mode", "custom",
            "--custom-route", "10.128.0.0/10",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["l3_config"]["mode"] == "user_octet"


def test_facility_port_update_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"name": "slice-a", "facility_ports": [{"name": "fp1", "vlan": "100"}]}
        result = runner.invoke(cli, [
            "facility-ports", "update", "slice-a", "fp1",
            "--vlan", "100",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["facility_ports"][0]["vlan"] == "100"


def test_port_mirror_add_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"name": "slice-a", "port_mirrors": [{"name": "pm1"}]}
        result = runner.invoke(cli, [
            "port-mirrors", "add", "slice-a", "pm1",
            "--mirror-interface", "node1-nic1-p1",
            "--receive-interface", "node2-nic1-p1",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["port_mirrors"][0]["name"] == "pm1"


def test_settings_get_dot_path(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"fabric": {"project_id": "proj-1"}}
        result = runner.invoke(cli, [
            "settings", "get", "fabric.project_id", "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["fabric.project_id"] == "proj-1"


def test_settings_set_json_value(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.side_effect = [
            {"views": {"federated_enabled": False}},
            {"views": {"federated_enabled": True}},
        ]
        result = runner.invoke(cli, [
            "settings", "set", "views.federated_enabled", "true", "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["views"]["federated_enabled"] is True
    assert "composite_enabled" not in json.loads(result.output)["views"]
    assert mock.call_args.kwargs["json"]["views"]["federated_enabled"] is True


def test_config_check_update_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"current_version": "1.0.0", "update_available": False}
        result = runner.invoke(cli, ["config", "check-update", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["update_available"] is False


def test_chameleon_status_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"enabled": False, "configured": False, "sites": {}}
        result = runner.invoke(cli, ["chameleon", "status", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["enabled"] is False


def test_chameleon_node_types_detail_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.side_effect = [
            {"enabled": True},
            {"site": "CHI@TACC", "node_types": [{"node_type": "compute_skylake", "total": 4}]},
        ]
        result = runner.invoke(cli, [
            "chameleon", "node-types", "detail", "CHI@TACC", "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["node_types"][0]["node_type"] == "compute_skylake"


def test_chameleon_slice_readiness_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.side_effect = [
            {"enabled": True},
            {"slice_id": "chi-1", "ready": True, "instances": []},
        ]
        result = runner.invoke(cli, [
            "chameleon", "slices", "check-readiness", "chi-1", "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["ready"] is True


def test_chameleon_draft_interfaces_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.side_effect = [
            {"enabled": True},
            {"id": "chi-1", "nodes": [{"id": "node-1", "interfaces": []}]},
        ]
        result = runner.invoke(cli, [
            "chameleon", "drafts", "set-interfaces", "chi-1", "node-1",
            "--interface", "0=sharednet1:sharednet1",
            "--interface", "1=fabnetv4",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["id"] == "chi-1"


def test_federated_create_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"id": "fed-1", "name": "fed-test", "state": "Draft"}
        result = runner.invoke(cli, [
            "federated", "create", "fed-test", "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["id"] == "fed-1"


def test_federated_member_add_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "id": "fed-1",
            "members": [{"provider": "fabric", "slice_id": "fab-1"}],
        }
        result = runner.invoke(cli, [
            "federated", "members", "add", "fed-1", "fabric", "fab-1",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["members"][0]["slice_id"] == "fab-1"


def test_federated_facility_port_connection_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "id": "fed-1",
            "cross_connections": [{"id": "conn-1", "type": "facility_port_l2", "vlan": "1234"}],
        }
        result = runner.invoke(cli, [
            "federated", "connections", "add", "fed-1",
            "--type", "facility_port_l2",
            "--fabric-slice", "fab-1",
            "--chameleon-slice", "chi-1",
            "--fabric-site", "STAR",
            "--chameleon-site", "CHI@TACC",
            "--facility-port", "star-fp",
            "--vlan", "1234",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["cross_connections"][0]["vlan"] == "1234"
    payload = mock.call_args.kwargs["json"]
    assert payload["endpoint_a"]["provider"] == "fabric"
    assert payload["endpoint_b"]["provider"] == "chameleon"


def test_ai_tools_status_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "opencode": {
                "installed": True,
                "display_name": "OpenCode",
                "type": "npm",
                "size_estimate": "~200 MB",
            }
        }
        result = runner.invoke(cli, ["ai", "tools", "status", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["opencode"]["installed"] is True


def test_ai_tools_install_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"status": "installed", "tool": "opencode", "output": "ok"}
        result = runner.invoke(cli, [
            "ai", "tools", "install", "opencode", "--format", "json",
        ])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["tool"] == "opencode"
    assert parsed["output"] == "ok"


def test_ai_tools_web_start_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"port": 9198, "status": "running"}
        result = runner.invoke(cli, [
            "ai", "tools", "web", "start", "opencode", "--model", "qwen3-coder-30b",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["port"] == 9198
    assert mock.call_args.args[:2] == ("POST", "/ai/opencode-web/start")
    assert mock.call_args.kwargs["params"]["model"] == "qwen3-coder-30b"


def test_tunnels_open_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "id": "tun-1",
            "slice_name": "slice-a",
            "node_name": "node1",
            "remote_port": 8888,
            "local_port": 9100,
            "status": "active",
        }
        result = runner.invoke(cli, [
            "tunnels", "open", "slice-a", "node1", "8888", "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["id"] == "tun-1"
    assert mock.call_args.kwargs["json"]["port"] == 8888


def test_jupyter_status_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"status": "running", "ready": True, "port": 8888}
        result = runner.invoke(cli, ["jupyter", "status", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["ready"] is True


def test_notebook_launch_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "status": "running",
            "jupyter_path": "/jupyter/lab/tree/notebooks/Hello_FABRIC/demo.ipynb",
        }
        result = runner.invoke(cli, [
            "notebooks", "launch", "Hello_FABRIC", "--force-refresh", "--format", "json",
        ])

    assert result.exit_code == 0
    assert "Hello_FABRIC" in json.loads(result.output)["jupyter_path"]
    assert mock.call_args.kwargs["params"]["force_refresh"] is True


def test_experiments_create_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "name": "Cross Test",
            "dir_name": "Cross_Test",
            "tags": ["cross-testbed"],
        }
        result = runner.invoke(cli, [
            "experiments", "create", "Cross Test",
            "--description", "demo",
            "--tags", "cross-testbed,demo",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["dir_name"] == "Cross_Test"
    assert mock.call_args.kwargs["json"]["tags"] == ["cross-testbed", "demo"]


def test_experiments_load_experiment_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "name": "slice-a",
            "experiment_loaded": True,
            "experiment_name": "Hello FABRIC",
        }
        result = runner.invoke(cli, [
            "experiments", "load-experiment", "Hello_FABRIC",
            "--var", "SLICE_NAME=slice-a",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["experiment_loaded"] is True
    assert mock.call_args.kwargs["json"]["variables"]["SLICE_NAME"] == "slice-a"


def test_users_list_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "active_user": "user-1",
            "multiuser": True,
            "users": [{"uuid": "user-1", "name": "A", "is_active": True}],
        }
        result = runner.invoke(cli, ["users", "list", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["active_user"] == "user-1"


def test_users_switch_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"status": "ok", "active_user": "user-2"}
        result = runner.invoke(cli, [
            "users", "switch", "user-2", "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["active_user"] == "user-2"


def test_ai_agent_create_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "id": "my-agent",
            "name": "My Agent",
            "description": "Demo",
            "source": "custom",
        }
        result = runner.invoke(cli, [
            "ai", "agents", "create", "my-agent",
            "--name", "My Agent",
            "--description", "Demo",
            "--content", "Use LoomAI carefully.",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["source"] == "custom"
    assert mock.call_args.args[:2] == ("PUT", "/ai/agents/my-agent")
    assert mock.call_args.kwargs["json"]["content"] == "Use LoomAI carefully."


def test_ai_skill_edit_preserves_existing_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.side_effect = [
            {
                "id": "my-skill",
                "name": "Old",
                "description": "Old description",
                "content": "Old body",
            },
            {
                "id": "my-skill",
                "name": "New",
                "description": "Old description",
                "source": "custom",
            },
        ]
        result = runner.invoke(cli, [
            "ai", "skills", "edit", "my-skill",
            "--name", "New",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["name"] == "New"
    assert mock.call_args.kwargs["json"]["content"] == "Old body"


def test_trovi_list_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "artifacts": [{"uuid": "tr-1", "title": "Hello Chameleon"}],
            "total": 1,
        }
        result = runner.invoke(cli, [
            "trovi", "list", "--query", "hello", "--tag", "notebook", "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["artifacts"][0]["uuid"] == "tr-1"
    assert mock.call_args.kwargs["params"]["q"] == "hello"


def test_monitor_history_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"slice_name": "slice-a", "history": {"node1": []}}
        result = runner.invoke(cli, [
            "monitor", "history", "slice-a", "--minutes", "15", "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["slice_name"] == "slice-a"
    assert mock.call_args.kwargs["params"]["minutes"] == 15


def test_monitor_node_enable_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"status": "enabled", "message": "ok"}
        result = runner.invoke(cli, [
            "monitor", "nodes", "enable", "slice-a", "node1", "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["status"] == "enabled"
    assert mock.call_args.args[:2] == ("POST", "/monitoring/slice-a/nodes/node1/enable")


def test_chameleon_openstack_request_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.side_effect = [
            {"enabled": True},
            {"servers": []},
        ]
        result = runner.invoke(cli, [
            "chameleon", "openstack-request",
            "--site", "CHI@TACC",
            "--service", "compute",
            "--method", "GET",
            "--path", "/servers/detail",
            "--params-json", '{"limit": 5}',
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["servers"] == []
    payload = mock.call_args.kwargs["json"]
    assert payload["service_type"] == "compute"
    assert payload["params"]["limit"] == 5


def test_files_list_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = [
            {"name": "work", "type": "dir", "size": 0, "modified": "2026-06-14T12:00:00"},
        ]
        result = runner.invoke(cli, ["files", "list", "work", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output)[0]["name"] == "work"
    assert mock.call_args.kwargs["params"]["path"] == "work"


def test_files_write_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"path": "notes.txt", "status": "ok"}
        result = runner.invoke(cli, [
            "files", "write", "notes.txt", "--content", "hello", "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["status"] == "ok"
    assert mock.call_args.kwargs["json"]["content"] == "hello"


def test_files_vm_execute_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"stdout": "ok\n", "stderr": ""}
        result = runner.invoke(cli, [
            "files", "vm", "execute", "slice-a", "node1", "hostname",
            "--timeout", "20",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["stdout"] == "ok\n"
    assert mock.call_args.kwargs["json"]["timeout"] == 20


def test_files_chameleon_read_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"path": "/home/cc/readme.txt", "content": "hello"}
        result = runner.invoke(cli, [
            "files", "chameleon", "read", "inst-1", "/home/cc/readme.txt",
            "--site", "CHI@TACC",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["content"] == "hello"
    assert mock.call_args.kwargs["params"]["site"] == "CHI@TACC"


def test_files_provision_add_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {
            "id": "rule-1",
            "source": "setup.sh",
            "slice_name": "slice-a",
            "node_name": "node1",
            "dest": "/tmp/setup.sh",
        }
        result = runner.invoke(cli, [
            "files", "provisions", "add",
            "setup.sh", "slice-a", "node1", "/tmp/setup.sh",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["id"] == "rule-1"
    assert mock.call_args.kwargs["json"]["node_name"] == "node1"


def test_files_boot_running_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"running": ["slice-a"], "slices": {"slice-a": 3}}
        result = runner.invoke(cli, ["files", "boot", "running", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["running"] == ["slice-a"]


def test_boot_config_set_json_outputs_saved_config(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"slice_name": "slice-a", "node_name": "node1", "commands": []}
        result = runner.invoke(cli, [
            "boot-config", "set", "slice-a", "node1",
            "-c", "echo ready",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["node_name"] == "node1"
    assert mock.call_args.args[:2] == ("PUT", "/files/boot-config/slice-a/node1")


def test_boot_config_log_lines_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"lines": [{"message": "boot started"}]}
        result = runner.invoke(cli, ["boot-config", "log", "slice-a", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["lines"][0]["message"] == "boot started"


def test_artifact_versions_empty_json(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.return_value = {"uuid": "art-1", "versions": []}
        result = runner.invoke(cli, ["artifacts", "versions", "art-1", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_root_help_hides_composite_alias(runner):
    from loomai_cli.main import cli

    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "federated" in result.output.lower()
    assert "composite" not in result.output.lower()


def test_chameleon_lease_create_json_clean(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.side_effect = [
            {"enabled": True},
            {"id": "lease-1", "name": "test", "status": "PENDING"},
        ]
        result = runner.invoke(cli, [
            "chameleon", "leases", "create",
            "--site", "CHI@TACC",
            "--name", "test",
            "--type", "compute_skylake",
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["id"] == "lease-1"


def test_chameleon_instance_reboot_json_clean(runner):
    from loomai_cli.main import cli

    with patch("loomai_cli.client.Client._request") as mock:
        mock.side_effect = [
            {"enabled": True},
            {"id": "inst-1", "status": "rebooting"},
        ]
        result = runner.invoke(cli, [
            "chameleon", "instances", "reboot", "inst-1", "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["status"] == "rebooting"
    assert mock.call_args.args[:2] == ("POST", "/chameleon/instances/inst-1/reboot")


def test_chameleon_keypair_upload_private_key_json(runner, tmp_path):
    from loomai_cli.main import cli

    key_path = tmp_path / "chameleon.pem"
    key_path.write_text("PRIVATE KEY\n")

    with patch("loomai_cli.client.Client._request") as mock:
        mock.side_effect = [
            {"enabled": True},
            {"name": "loomai-key", "site": "CHI@TACC", "has_private_key": True},
        ]
        result = runner.invoke(cli, [
            "chameleon", "keypairs", "upload-private-key", "loomai-key",
            "--site", "CHI@TACC",
            "--file", str(key_path),
            "--format", "json",
        ])

    assert result.exit_code == 0
    assert json.loads(result.output)["has_private_key"] is True
    assert mock.call_args.args[:2] == ("POST", "/chameleon/keypairs/loomai-key/private-key")
    assert mock.call_args.kwargs["params"] == {"site": "CHI@TACC"}
