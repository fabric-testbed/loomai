#!/usr/bin/env python3
"""Post-deploy lifecycle verifier for LoomAI-managed external harnesses.

Run inside a deployed container after the owner-approved rebuild:

    python3 /app/scripts/verify_harness_lifecycle.py --execute

The execute path intentionally uninstalls and reinstalls each selected harness.
It leaves harnesses installed and configured when successful.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


MANAGED_HARNESSES = ("opencode", "goose", "pi", "aider", "crush", "codex", "claude")
INSTALL_OK = {"installed", "already_installed"}
UNINSTALL_OK = {"uninstalled", "not_installed"}
UNINSTALL_REFUSAL = {"running"}


class CheckError(RuntimeError):
    pass


class ApiClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        base = base_url.rstrip("/")
        if not base.endswith("/api"):
            base = f"{base}/api"
        self.base_url = base
        self.timeout = timeout

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", path, params=params)

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, method=method, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise CheckError(f"{method} {path} failed with HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise CheckError(f"{method} {path} failed: {exc.reason}") from exc
        if not body:
            return {}
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise CheckError(f"{method} {path} returned non-JSON: {body[:200]}") from exc
        if not isinstance(data, dict):
            raise CheckError(f"{method} {path} returned unexpected JSON: {data!r}")
        return data


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckError(message)


def _tool_status(api: ApiClient, harness: str) -> dict[str, Any]:
    data = api.get("/ai/tools/status")
    entry = data.get(harness)
    _require(isinstance(entry, dict), f"{harness}: missing tool status entry")
    return entry


def _harness_status(api: ApiClient, harness: str) -> str:
    data = api.get(f"/ai/tools/harnesses/{urllib.parse.quote(harness)}/status")
    entry = data.get("harness")
    _require(isinstance(entry, dict), f"{harness}: missing harness status entry")
    status = entry.get("status")
    _require(isinstance(status, str), f"{harness}: invalid harness status payload {entry!r}")
    return status


def _expect_tool(api: ApiClient, harness: str, installed: bool, phase: str) -> dict[str, Any]:
    entry = _tool_status(api, harness)
    actual = bool(entry.get("installed"))
    _require(
        actual is installed,
        f"{harness}: expected installed={installed} after {phase}, got {actual}",
    )
    return entry


def _expect_harness(api: ApiClient, harness: str, allowed: set[str], phase: str) -> str:
    status = _harness_status(api, harness)
    _require(
        status in allowed,
        f"{harness}: expected harness status in {sorted(allowed)} after {phase}, got {status!r}",
    )
    return status


def _response_diagnostics(data: dict[str, Any]) -> str:
    details = []
    for key in ("error", "message", "output"):
        value = data.get(key)
        if value:
            details.append(f"{key}={str(value)[-4000:]!r}")
    return "; ".join(details) or repr(data)


def _post_status(api: ApiClient, path: str, harness: str, allowed: set[str], phase: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    data = api.post(path, params=params)
    status = data.get("status")
    _require(status in allowed, f"{harness}: unexpected {phase} status {status!r}: {_response_diagnostics(data)}")
    return data


def _post_uninstall(api: ApiClient, harness: str, phase: str, *, expect_refusal: bool = False, params: dict[str, Any] | None = None) -> dict[str, Any]:
    quoted = urllib.parse.quote(harness)
    data = api.post(f"/ai/tools/{quoted}/uninstall", params=params)
    status = data.get("status")
    if status in UNINSTALL_REFUSAL:
        _require(data.get("error"), f"{harness}: active-process refusal lacked an error message: {data!r}")
        if expect_refusal:
            return data
        raise CheckError(
            f"{harness}: uninstall was explicitly refused during {phase}; "
            f"stop the active process and rerun. {_response_diagnostics(data)}"
        )
    _require(status in UNINSTALL_OK, f"{harness}: unexpected {phase} status {status!r}: {_response_diagnostics(data)}")
    if expect_refusal:
        raise CheckError(f"{harness}: expected active-process uninstall refusal, got {status!r}: {data!r}")
    return data


def _expect_pinned_versions_current(entry: dict[str, Any], harness: str, phase: str) -> None:
    _require(
        not bool(entry.get("version_drift")),
        f"{harness}: package version drift remains after {phase}: {entry.get('package_versions')!r}",
    )
    package_versions = entry.get("package_versions") or {}
    if not isinstance(package_versions, dict):
        return
    for package, versions in package_versions.items():
        if not isinstance(versions, dict):
            continue
        pinned = versions.get("pinned")
        installed = versions.get("installed")
        _require(
            not pinned or installed == pinned,
            f"{harness}: {package} installed version {installed!r} does not match pinned {pinned!r} after {phase}",
        )


def _expect_uninstalled_packages_absent(entry: dict[str, Any], harness: str, phase: str) -> None:
    package_versions = entry.get("package_versions") or {}
    if not isinstance(package_versions, dict):
        return
    remaining = [
        f"{package}={versions.get('installed')}"
        for package, versions in package_versions.items()
        if isinstance(versions, dict) and versions.get("installed")
    ]
    _require(
        not remaining,
        f"{harness}: packages remain after {phase}: {', '.join(remaining)}",
    )


def verify_active_uninstall_refusal(api: ApiClient, harness: str) -> None:
    print(f"[{harness}] active-process uninstall refusal", flush=True)
    _expect_tool(api, harness, True, "active-refusal precheck")
    refused = _post_uninstall(api, harness, "active-process refusal", expect_refusal=True)
    _require(refused.get("error"), f"{harness}: refusal response missing error: {refused!r}")
    _expect_tool(api, harness, True, "active-process refusal")


def verify_harness(api: ApiClient, harness: str) -> None:
    quoted = urllib.parse.quote(harness)
    print(f"[{harness}] install and sync defaults", flush=True)
    _post_status(api, f"/ai/tools/{quoted}/install", harness, INSTALL_OK, "install")
    entry = _expect_tool(api, harness, True, "install")
    _expect_pinned_versions_current(entry, harness, "install")
    _expect_harness(api, harness, {"configured"}, "install")

    print(f"[{harness}] reset defaults", flush=True)
    reset = api.post(f"/ai/tools/harnesses/{quoted}/reset")
    _require(reset.get("status") == "ok", f"{harness}: reset failed: {reset!r}")
    _expect_harness(api, harness, {"configured"}, "reset")

    print(f"[{harness}] uninstall while preserving config", flush=True)
    _post_uninstall(api, harness, "uninstall")
    entry = _expect_tool(api, harness, False, "uninstall")
    _expect_uninstalled_packages_absent(entry, harness, "uninstall")
    _expect_harness(api, harness, {"configured"}, "config-preserving uninstall")

    print(f"[{harness}] remove config while uninstalled", flush=True)
    removed = _post_uninstall(
        api,
        harness,
        "remove-config uninstall",
        params={"remove_config": "true"},
    )
    _require(
        int(removed.get("removed_config_files") or 0) > 0,
        f"{harness}: remove_config did not remove expected config files: {removed!r}",
    )
    entry = _expect_tool(api, harness, False, "remove-config uninstall")
    _expect_uninstalled_packages_absent(entry, harness, "remove-config uninstall")
    _expect_harness(api, harness, {"stale"}, "remove-config uninstall")

    print(f"[{harness}] reinstall and re-sync defaults", flush=True)
    _post_status(api, f"/ai/tools/{quoted}/install", harness, INSTALL_OK, "reinstall")
    entry = _expect_tool(api, harness, True, "reinstall")
    _expect_pinned_versions_current(entry, harness, "reinstall")
    _expect_harness(api, harness, {"configured"}, "reinstall")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="LoomAI backend base URL, with or without /api (default: %(default)s)",
    )
    parser.add_argument(
        "--harness",
        action="append",
        choices=MANAGED_HARNESSES,
        help="Managed harness to verify. Repeat to select several; default verifies all.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3600.0,
        help="Per-request timeout in seconds for package install/uninstall calls.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually install, uninstall, remove config, and reinstall selected harnesses.",
    )
    parser.add_argument(
        "--expect-active-refusal",
        action="append",
        choices=MANAGED_HARNESSES,
        help=(
            "Verify that uninstall is refused for a harness that is intentionally "
            "left running. Repeat to select several. These harnesses skip the "
            "destructive lifecycle sequence."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    harnesses = tuple(args.harness or MANAGED_HARNESSES)
    active_refusals = set(args.expect_active_refusal or [])
    if not args.execute:
        print("Dry run only. Pass --execute to run lifecycle checks.")
        print("Planned sequence for each harness:")
        print("  install -> reset -> uninstall keep-config -> remove-config -> reinstall")
        if active_refusals:
            print("Active-refusal checks:", ", ".join(sorted(active_refusals)))
        print("Harnesses:", ", ".join(harnesses))
        return 0

    api = ApiClient(args.base_url, args.timeout)
    try:
        for harness in sorted(active_refusals):
            verify_active_uninstall_refusal(api, harness)
        for harness in harnesses:
            if harness in active_refusals:
                continue
            verify_harness(api, harness)
    except CheckError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: managed harness lifecycle parity verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
