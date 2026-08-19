"""Dependency-free stdio MCP server for LoomAI's local REST API.

The external-harness configs use this module as a local MCP server. It speaks
the small JSON-RPC subset required by OpenCode: initialize, tools/list, and
tools/call.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib import error as urllib_error
from urllib import parse, request


DEFAULT_BACKEND_URL = "http://localhost:8000"
SUBMIT_STABLEOK_WAIT_TIMEOUT_SECONDS = 240
METATOOL_NAMES = {"list-endpoints", "describe-endpoint"}

# FC18-1: deterministic evidence-closure hints (<=200 chars each) appended to
# SUCCESS results of state-changing tools for weak-profile models only. The
# hint tells the model to SHOW its work; it never states what the answer is.
EVIDENCE_CLOSURE_HINTS = {
    "submit_slice": (
        "Before finishing, show the user: final slice state (StableOK), the node list, and the "
        "verification output (ping/curl/iperf) proving the goal."
    ),
    "run_weave": (
        "Before finishing, show the user: the weave run status, the log tail, and the results/ "
        "output proving the goal."
    ),
    "execute_recipe": (
        "Before finishing, show the user: the recipe job result and the command output proving "
        "the install succeeded."
    ),
    "configure_networking": (
        "Before finishing, show the user: the networking verification output (ping) and the "
        "slice state proving connectivity."
    ),
}


@dataclass
class Job:
    id: str
    tool: str
    status: str = "pending"
    result: dict[str, Any] | None = None
    error: str = ""
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, tool: str, target: Any, *args: Any, **kwargs: Any) -> str:
        job = Job(id=str(uuid.uuid4()), tool=tool)
        with self._lock:
            self._jobs[job.id] = job
        thread = threading.Thread(target=self._run, args=(job.id, target, args, kwargs), daemon=True)
        thread.start()
        return job.id

    def _run(self, job_id: str, target: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
        try:
            result = target(*args, **kwargs)
            with self._lock:
                job = self._jobs[job_id]
                job.status = "succeeded"
                job.result = result
                job.ended_at = time.time()
        except Exception as exc:  # noqa: BLE001 - reported through MCP result
            with self._lock:
                job = self._jobs[job_id]
                job.status = "failed"
                job.error = str(exc)
                job.ended_at = time.time()

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {"job_id": job_id, "status": "not_found"}
            return {
                "job_id": job.id,
                "tool": job.tool,
                "status": job.status,
                "result": job.result,
                "error": job.error,
                "started_at": job.started_at,
                "ended_at": job.ended_at,
            }


class LoomAIRestClient:
    def __init__(self, base_url: str = DEFAULT_BACKEND_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 300) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = request.Request(url, data=data, method=method, headers={"Accept": "application/json"})
        if payload is not None:
            req.add_header("Content-Type", "application/json")
        started = time.time()
        try:
            with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - localhost/API URL
                text = response.read().decode("utf-8", errors="replace")
                status = int(getattr(response, "status", 0) or 0)
        except urllib_error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            status = int(exc.code)
        parsed = _parse_json(text)
        return {
            "method": method,
            "path": path,
            "http_status": status,
            "ok": 200 <= status < 300,
            "elapsed_seconds": round(time.time() - started, 6),
            "body": parsed if parsed is not None else text,
        }


class MCPServer:
    def __init__(self, client: LoomAIRestClient | None = None, jobs: JobStore | None = None) -> None:
        self.client = client or LoomAIRestClient(os.environ.get("LOOMAI_URL", DEFAULT_BACKEND_URL))
        self.jobs = jobs or JobStore()

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = str(message.get("method") or "")
        msg_id = message.get("id")
        try:
            if method == "initialize":
                return _response(msg_id, {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "loomai-harness", "version": "0.1.0"},
                    "capabilities": {"tools": {}},
                })
            if method == "notifications/initialized":
                return None
            if method == "tools/list":
                return _response(msg_id, {"tools": tool_definitions()})
            if method == "tools/call":
                params = message.get("params") or {}
                result = self.call_tool(str(params.get("name") or ""), params.get("arguments") or {})
                return _response(msg_id, {"content": [{"type": "text", "text": json.dumps(result, indent=2, sort_keys=True)}]})
            return _error(msg_id, -32601, f"unknown method: {method}")
        except Exception as exc:  # noqa: BLE001 - JSON-RPC error response
            return _error(msg_id, -32000, str(exc))

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name in METATOOL_NAMES and _mcp_metatools_enabled():
            if name == "list-endpoints":
                from app.openapi_metatools import list_endpoints

                return list_endpoints(
                    tag=str(args.get("tag") or ""),
                    path_prefix=str(args.get("path_prefix") or ""),
                    limit=int(args.get("limit") or 120),
                )
            if name == "describe-endpoint":
                from app.openapi_metatools import describe_endpoint

                return describe_endpoint(
                    method=str(args.get("method") or ""),
                    path=str(args.get("path") or ""),
                )
        if name == "list_slices":
            return self.client.request("GET", "/api/slices")
        if name == "get_slice":
            return self.client.request("GET", f"/api/slices/{_quote(args['slice_name'])}")
        if name == "validate_slice":
            return self.client.request("GET", f"/api/slices/{_quote(args['slice_name'])}/validate")
        if name == "create_slice":
            return self.client.request("POST", "/api/slices", {"name": args["name"]})
        if name == "delete_slice":
            return self.client.request("DELETE", f"/api/slices/{_quote(args['slice_name'])}")
        if name == "submit_slice":
            wait_for_stableok = bool(args.get("wait_for_stableok", False))
            payload = {"lease_hours": int(args.get("lease_hours") or 6), "wait_for_stableok": wait_for_stableok}
            timeout = SUBMIT_STABLEOK_WAIT_TIMEOUT_SECONDS if wait_for_stableok else 300
            job_id = self.jobs.start(
                name,
                self.client.request,
                "POST",
                f"/api/slices/{_quote(args['slice_name'])}/submit",
                payload,
                timeout,
            )
            return _with_evidence_closure_hint(name, {
                "job_id": job_id,
                "status": "started",
                "wait_for_stableok": wait_for_stableok,
                "wait_timeout_seconds": timeout if wait_for_stableok else None,
                "message": (
                    "Submit is running in a LoomAI harness job. Poll get_job_status with this job_id; "
                    "after the job succeeds, poll get_slice/list_slices for StableOK before claiming readiness."
                ),
            })
        if name == "renew_slice":
            payload = {"hours": int(args.get("lease_hours") or 6)}
            job_id = self.jobs.start(name, self.client.request, "POST", f"/api/slices/{_quote(args['slice_name'])}/renew", payload)
            return {"job_id": job_id, "status": "started"}
        if name == "configure_networking":
            result = self.client.request("POST", f"/api/slices/{_quote(args['slice_name'])}/configure-networking", {"verify": True})
            if result.get("ok"):
                result = _with_evidence_closure_hint(name, result)
            return result
        if name == "run_weave":
            script = args.get("script") or "weave.sh"
            path = f"/api/templates/{_quote(args['template'])}/run-script/{_quote(script)}"
            payload = {"args": {**(args.get("args") or {}), "lease_hours": int(args.get("lease_hours") or 6)}}
            job_id = self.jobs.start(name, self.client.request, "POST", path, payload)
            return _with_evidence_closure_hint(name, {"job_id": job_id, "status": "started"})
        if name == "get_weave_status":
            return self.client.request("GET", f"/api/templates/{_quote(args['template'])}")
        if name == "execute_recipe":
            path = f"/api/recipes/{_quote(args['recipe'])}/execute/{_quote(args['slice_name'])}/{_quote(args['node_name'])}"
            job_id = self.jobs.start(name, self.client.request, "POST", path)
            return _with_evidence_closure_hint(name, {"job_id": job_id, "status": "started"})
        if name == "create_tunnel":
            payload = {
                "slice_name": args["slice_name"],
                "node_name": args["node_name"],
                "remote_port": int(args["remote_port"]),
            }
            if args.get("local_port"):
                payload["local_port"] = int(args["local_port"])
            return self.client.request("POST", "/api/tunnels", payload)
        if name == "list_tunnels":
            return self.client.request("GET", "/api/tunnels")
        if name == "vm_exec":
            return self.client.request("POST", f"/api/files/vm/{_quote(args['slice_name'])}/{_quote(args['node_name'])}/execute", {"command": args["command"]})
        if name == "list_artifacts":
            return self.client.request("GET", "/api/artifacts/local")
        if name == "validate_artifact":
            payload = {
                key: args[key]
                for key in ("dir_name", "weave_json", "vm_template_json", "recipe_json", "scripts", "files")
                if key in args
            }
            return self.client.request("POST", "/api/artifacts/validate", payload)
        if name == "list_sites":
            return self.client.request("GET", "/api/sites")
        if name == "list_hosts":
            return self.client.request("GET", f"/api/sites/{_quote(args['site'])}/hosts")
        if name == "list_images":
            return self.client.request("GET", "/api/images")
        if name == "get_job_status":
            status = self.jobs.status(args["job_id"])
            job_tool = str(status.get("tool") or "")
            job_result = status.get("result")
            job_http_ok = not (isinstance(job_result, dict) and job_result.get("ok") is False)
            if status.get("status") == "succeeded" and job_http_ok and job_tool in EVIDENCE_CLOSURE_HINTS:
                status = _with_evidence_closure_hint(job_tool, status)
            return status
        return {"ok": False, "error": f"unknown tool: {name}"}


def tool_definitions() -> list[dict[str, Any]]:
    tools = [
        _tool("list_slices", "Read-only list of LoomAI slices.", {}, read_only=True),
        _tool("get_slice", "Read-only details for one slice.", {"slice_name": _str_schema()}, read_only=True),
        _tool(
            "validate_slice",
            "Read-only draft validation. Call validate_slice BEFORE submit_slice and fix reported issues first; "
            "this catches FABNet per-site/service limits and other placement errors.",
            {"slice_name": _str_schema()},
            read_only=True,
        ),
        _tool("create_slice", "Create a draft slice.", {"name": _str_schema()}, destructive=True),
        _tool(
            "delete_slice",
            "Delete one exact LoomAI/FABRIC slice by name. This is destructive and should only be called "
            "after explicit user authorization for the named slice, for example to recover from a wrong "
            "or over-policy lease.",
            {"slice_name": _str_schema()},
            destructive=True,
        ),
        _tool(
            "submit_slice",
            "Submit a draft slice asynchronously. Call validate_slice first and do not submit when validation "
            "reports errors. Default wait_for_stableok=false to avoid long MCP turns: poll get_job_status, "
            "then poll get_slice/list_slices for StableOK before claiming readiness. If wait_for_stableok=true "
            f"the harness HTTP wait is capped at {SUBMIT_STABLEOK_WAIT_TIMEOUT_SECONDS} seconds; on timeout, "
            "continue polling the slice. FABNetv4/v6 services must attach only VMs at one site, up to 255 VMs "
            "per service; use one FABNet service per site for multi-site L3. Defaults to a 6-hour lease.",
            {
                "slice_name": _str_schema(),
                "lease_hours": _int_schema(1, 6, required=False, default=6),
                "wait_for_stableok": _bool_schema(required=False, default=False),
            },
            destructive=True,
        ),
        _tool("renew_slice", "Renew a slice lease asynchronously with a 6-hour maximum.", {"slice_name": _str_schema(), "lease_hours": _int_schema(1, 6, required=False, default=6)}, destructive=True),
        _tool(
            "configure_networking",
            "Configure and verify post-StableOK private/FABNet networking only. It cannot fix an invalid "
            "cross-site single FABNet service; FABNet services are per-site, so use per-node/per-site FABNet "
            "before submit_slice.",
            {"slice_name": _str_schema()},
            destructive=True,
        ),
        _tool("run_weave", "Run a weave script asynchronously with a 6-hour lease default.", {"template": _str_schema(), "script": _str_schema(required=False, default="weave.sh"), "args": _object_schema(), "lease_hours": _int_schema(1, 6, required=False, default=6)}, destructive=True),
        _tool("get_weave_status", "Read-only local template details/status.", {"template": _str_schema()}, read_only=True),
        _tool("execute_recipe", "Execute a recipe on a node asynchronously.", {"recipe": _str_schema(), "slice_name": _str_schema(), "node_name": _str_schema()}, destructive=True),
        _tool("create_tunnel", "Create a LoomAI web tunnel.", {"slice_name": _str_schema(), "node_name": _str_schema(), "remote_port": _int_schema(1, 65535), "local_port": _int_schema(1, 65535, required=False)}, destructive=True),
        _tool("list_tunnels", "Read-only list of active web tunnels.", {}, read_only=True),
        _tool("vm_exec", "Execute a command on a VM through the backend.", {"slice_name": _str_schema(), "node_name": _str_schema(), "command": _str_schema()}, destructive=True),
        _tool("list_artifacts", "Read-only list of local artifacts.", {}, read_only=True),
        _tool(
            "validate_artifact",
            "Read-only static validation for a local artifact or inline weave payload. Call before run_weave or "
            "publish_artifact; it checks marker JSON, args shape, run_script consistency, shell progress/error "
            "handling, and results/ output path conventions.",
            {
                "dir_name": _str_schema(required=False),
                "weave_json": _object_schema(required=False),
                "vm_template_json": _object_schema(required=False),
                "recipe_json": _object_schema(required=False),
                "scripts": _object_schema(required=False),
                "files": _object_schema(required=False),
            },
            read_only=True,
        ),
        _tool("list_sites", "Read-only FABRIC site availability.", {}, read_only=True),
        _tool("list_hosts", "Read-only host availability for a site.", {"site": _str_schema()}, read_only=True),
        _tool("list_images", "Read-only VM image list.", {}, read_only=True),
        _tool("get_job_status", "Read-only status for async submit/run/recipe jobs.", {"job_id": _str_schema()}, read_only=True),
    ]
    if _mcp_metatools_enabled():
        tools.extend(_metatool_definitions())
    return tools


def _metatool_definitions() -> list[dict[str, Any]]:
    return [
        _tool(
            "list-endpoints",
            "Read-only compact catalog of LoomAI REST endpoints from OpenAPI. Optional filters: tag, path_prefix, limit.",
            {
                "tag": _str_schema(required=False),
                "path_prefix": _str_schema(required=False, default="/api"),
                "limit": _int_schema(1, 300, required=False, default=120),
            },
            read_only=True,
        ),
        _tool(
            "describe-endpoint",
            "Read-only compact OpenAPI description for one endpoint, including parameters, request/response schemas, and examples.",
            {
                "method": _str_schema(),
                "path": _str_schema(),
            },
            read_only=True,
        ),
    ]


def main() -> int:
    server = MCPServer()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = server.handle(message)
            if response is not None:
                sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps(_error(None, -32700, str(exc)), separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


def _tool(name: str, description: str, properties: dict[str, dict[str, Any]], *, read_only: bool = False, destructive: bool = False) -> dict[str, Any]:
    normalized: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    for key, schema in properties.items():
        item = dict(schema)
        if item.pop("_required", True):
            required.append(key)
        normalized[key] = item
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": normalized,
            "required": required,
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": read_only, "destructiveHint": destructive},
    }


def _str_schema(*, required: bool = True, default: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "_required": required}
    if default is not None:
        schema["default"] = default
    return schema


def _int_schema(minimum: int, maximum: int, *, required: bool = True, default: int | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "integer", "minimum": minimum, "maximum": maximum, "_required": required}
    if default is not None:
        schema["default"] = default
    return schema


def _bool_schema(*, required: bool = True, default: bool | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "boolean", "_required": required}
    if default is not None:
        schema["default"] = default
    return schema


def _object_schema(*, required: bool = False) -> dict[str, Any]:
    return {"type": "object", "_required": required, "additionalProperties": True}


def _mcp_metatools_enabled() -> bool:
    try:
        from app.settings_manager import get_mcp_metatools_enabled

        return get_mcp_metatools_enabled()
    except Exception:
        return False


def _evidence_closure_model_key() -> str:
    """Model key of the harness session, from the launcher environment."""
    return (os.environ.get("LOOMAI_MCP_MODEL") or os.environ.get("LOOMAI_MODEL") or "").strip()


def _evidence_closure_hint(tool: str) -> str | None:
    """Return the FC18-1 hint for *tool* when the weak-profile gate is on."""
    if tool not in EVIDENCE_CLOSURE_HINTS:
        return None
    try:
        from app.settings_manager import get_mcp_evidence_closure_hints_enabled

        if get_mcp_evidence_closure_hints_enabled(_evidence_closure_model_key()):
            return EVIDENCE_CLOSURE_HINTS[tool]
    except Exception:
        return None
    return None


def _with_evidence_closure_hint(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    hint = _evidence_closure_hint(tool)
    if hint and "next_step_hint" not in result:
        result["next_step_hint"] = hint
    return result


def _quote(value: Any) -> str:
    return parse.quote(str(value), safe="")


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def _response(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    raise SystemExit(main())
