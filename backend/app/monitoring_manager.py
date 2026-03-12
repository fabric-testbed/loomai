"""Monitoring manager — scrapes node_exporter metrics from slice VMs via SSH."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from app.fablib_manager import get_fablib
from app.slice_registry import get_slice_uuid
from app.user_context import get_user_storage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

SCRAPE_INTERVAL = 15  # seconds
MAX_SAMPLES = 240  # 240 * 15s = 60 minutes retention


@dataclass
class NodeMonitoringState:
    name: str
    enabled: bool = False
    exporter_installed: bool = False
    management_ip: str = ""
    username: str = ""
    site: str = ""
    last_scrape: float = 0.0
    last_error: str = ""
    # Exponential backoff for unreachable nodes
    consecutive_failures: int = 0
    next_scrape_after: float = 0.0  # unix timestamp — skip scrape until this time


@dataclass
class SliceMonitoringState:
    slice_name: str
    enabled: bool = False
    nodes: Dict[str, NodeMonitoringState] = field(default_factory=dict)


@dataclass
class TimeSeriesPoint:
    t: float  # unix timestamp
    v: float


# ---------------------------------------------------------------------------
# Prometheus text format parser (subset)
# ---------------------------------------------------------------------------

_METRIC_LINE_RE = re.compile(
    r'^(\w+?)(\{[^}]*\})?\s+([\d.eE+\-]+(?:NaN)?)\s*(\d+)?$'
)


def _parse_prom_text(text: str) -> Dict[str, List[Dict[str, Any]]]:
    """Parse Prometheus exposition text into {metric_name: [{labels, value}]}."""
    result: Dict[str, List[Dict[str, Any]]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = _METRIC_LINE_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        labels_str = m.group(2) or ""
        try:
            value = float(m.group(3))
        except ValueError:
            continue
        labels = {}
        if labels_str:
            for lm in re.finditer(r'(\w+)="([^"]*)"', labels_str):
                labels[lm.group(1)] = lm.group(2)
        result.setdefault(name, []).append({"labels": labels, "value": value})
    return result


# ---------------------------------------------------------------------------
# MonitoringManager singleton
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_instance: Optional["MonitoringManager"] = None


def get_monitoring_manager() -> "MonitoringManager":
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = MonitoringManager()
    return _instance


class MonitoringManager:
    def __init__(self) -> None:
        self._states: Dict[str, SliceMonitoringState] = {}
        self._history: Dict[str, Dict[str, Dict[str, deque]]] = {}
        # _history[slice][node][metric_key] = deque of TimeSeriesPoint
        self._prev_cpu: Dict[str, Dict[str, Dict[str, float]]] = {}
        # _prev_cpu[slice][node][mode] = cumulative seconds
        self._prev_net: Dict[str, Dict[str, Dict[str, float]]] = {}
        # _prev_net[slice][node][iface_dir] = cumulative bytes
        self._prev_ts: Dict[str, Dict[str, float]] = {}
        # _prev_ts[slice][node] = last scrape unix time
        self._tasks: Dict[str, asyncio.Task] = {}
        self._executor = ThreadPoolExecutor(max_workers=8)
        self._state_lock = threading.Lock()
        self._load_persisted_states()

    # -- Persistence --------------------------------------------------------

    def _state_dir(self) -> str:
        storage = get_user_storage()
        d = os.path.join(storage, ".monitoring")
        os.makedirs(d, exist_ok=True)
        return d

    def _state_file(self, slice_name: str) -> str:
        safe = re.sub(r'[^\w\-. ]', '_', slice_name).strip()
        return os.path.join(self._state_dir(), f"{safe}.json")

    def _persist_state(self, slice_name: str) -> None:
        state = self._states.get(slice_name)
        if not state:
            return
        data = {
            "slice_name": state.slice_name,
            "enabled": state.enabled,
            "nodes": {
                n: {
                    "name": ns.name,
                    "enabled": ns.enabled,
                    "exporter_installed": ns.exporter_installed,
                    "management_ip": ns.management_ip,
                    "username": ns.username,
                    "site": ns.site,
                }
                for n, ns in state.nodes.items()
            },
        }
        try:
            with open(self._state_file(slice_name), "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("Failed to persist monitoring state for %s: %s", slice_name, e)

    def _load_persisted_states(self) -> None:
        state_dir = self._state_dir()
        if not os.path.isdir(state_dir):
            return
        for fname in os.listdir(state_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(state_dir, fname)) as f:
                    data = json.load(f)
                sname = data["slice_name"]
                state = SliceMonitoringState(slice_name=sname, enabled=data.get("enabled", False))
                for nname, nd in data.get("nodes", {}).items():
                    state.nodes[nname] = NodeMonitoringState(
                        name=nd["name"],
                        enabled=nd.get("enabled", False),
                        exporter_installed=nd.get("exporter_installed", False),
                        management_ip=nd.get("management_ip", ""),
                        username=nd.get("username", ""),
                        site=nd.get("site", ""),
                    )
                self._states[sname] = state
            except Exception as e:
                logger.warning("Failed to load monitoring state from %s: %s", fname, e)

    # -- FABlib helpers -----------------------------------------------------

    def _get_node(self, slice_name: str, node_name: str):
        """Return FABlib node object for a slice/node pair."""
        fablib = get_fablib()
        uuid = get_slice_uuid(slice_name)
        if uuid:
            try:
                slice_obj = fablib.get_slice(slice_id=uuid)
                return slice_obj.get_node(node_name)
            except Exception:
                pass
        slice_obj = fablib.get_slice(slice_name)
        return slice_obj.get_node(node_name)

    def _get_slice_nodes(self, slice_name: str):
        """Return list of FABlib node objects for a slice."""
        fablib = get_fablib()
        uuid = get_slice_uuid(slice_name)
        if uuid:
            try:
                slice_obj = fablib.get_slice(slice_id=uuid)
                return slice_obj.get_nodes()
            except Exception:
                pass
        slice_obj = fablib.get_slice(slice_name)
        return slice_obj.get_nodes()

    # -- node_exporter installation -----------------------------------------

    def install_node_exporter(self, slice_name: str, node_name: str) -> str:
        """Install node_exporter on a VM. Returns status message."""
        node = self._get_node(slice_name, node_name)
        mgmt_ip = str(node.get_management_ip())
        username = node.get_username()
        site = str(getattr(node, 'get_site', lambda: '')())
        if hasattr(node, 'get_site'):
            try:
                site = node.get_site()
            except Exception:
                site = ""

        # Update state
        with self._state_lock:
            state = self._states.setdefault(
                slice_name, SliceMonitoringState(slice_name=slice_name)
            )
            ns = state.nodes.setdefault(
                node_name, NodeMonitoringState(name=node_name)
            )
            ns.management_ip = mgmt_ip
            ns.username = username
            ns.site = site

        # Check if already running
        stdout, stderr = node.execute("curl -s -o /dev/null -w '%{http_code}' http://localhost:9100/metrics 2>/dev/null || echo 'fail'")
        stdout = stdout.strip()
        if stdout == "200":
            with self._state_lock:
                ns.exporter_installed = True
                ns.enabled = True
                self._persist_state(slice_name)
            return f"node_exporter already running on {node_name}"

        # Detect OS
        stdout_os, _ = node.execute("cat /etc/os-release 2>/dev/null | head -5")
        is_rocky = "rocky" in stdout_os.lower() or "centos" in stdout_os.lower() or "rhel" in stdout_os.lower()

        # Install Docker and run node_exporter container
        install_cmds = []
        if is_rocky:
            install_cmds = [
                "sudo dnf install -y dnf-plugins-core 2>/dev/null",
                "sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo 2>/dev/null || true",
                "sudo dnf install -y docker-ce docker-ce-cli containerd.io 2>/dev/null || sudo dnf install -y docker 2>/dev/null",
                "sudo systemctl start docker",
                "sudo systemctl enable docker",
            ]
        else:
            install_cmds = [
                "sudo apt-get update -qq",
                "sudo apt-get install -y -qq docker.io",
                "sudo systemctl start docker",
                "sudo systemctl enable docker",
            ]

        install_cmds.extend([
            "sudo docker rm -f node_exporter 2>/dev/null || true",
            "sudo docker run -d --name node_exporter --restart=unless-stopped "
            "--net=host --pid=host -v /:/host:ro,rslave "
            "prom/node-exporter --path.rootfs=/host",
        ])

        errors = []
        for cmd in install_cmds:
            try:
                stdout_c, stderr_c = node.execute(cmd)
                if stderr_c and "error" in stderr_c.lower():
                    errors.append(f"{cmd}: {stderr_c.strip()}")
            except Exception as e:
                errors.append(f"{cmd}: {e}")

        # Verify
        import time as _time
        _time.sleep(3)
        stdout_v, _ = node.execute("curl -s -o /dev/null -w '%{http_code}' http://localhost:9100/metrics 2>/dev/null || echo 'fail'")
        installed = stdout_v.strip() == "200"

        with self._state_lock:
            ns.exporter_installed = installed
            ns.enabled = installed
            if not installed:
                ns.last_error = f"Installation may have failed: {'; '.join(errors[-3:])}"
            self._persist_state(slice_name)

        return f"node_exporter {'installed' if installed else 'FAILED'} on {node_name}"

    # -- Scraping -----------------------------------------------------------

    # Max backoff interval for unreachable nodes (5 minutes)
    _MAX_BACKOFF = 300

    def _scrape_node(self, slice_name: str, node_name: str) -> Optional[str]:
        """Scrape metrics from a single node. Returns raw text or None.

        Implements exponential backoff for unreachable nodes to avoid
        wasting thread pool time on nodes that are consistently failing.
        """
        try:
            node = self._get_node(slice_name, node_name)
            stdout, stderr = node.execute(
                "curl -s --max-time 10 http://localhost:9100/metrics 2>/dev/null"
            )
            if stdout and "node_cpu_seconds_total" in stdout:
                # Success — reset backoff
                with self._state_lock:
                    state = self._states.get(slice_name)
                    if state and node_name in state.nodes:
                        ns = state.nodes[node_name]
                        ns.consecutive_failures = 0
                        ns.next_scrape_after = 0.0
                return stdout
            # No useful data — treat as failure
            self._record_scrape_failure(slice_name, node_name, "No metrics data")
            return None
        except Exception as e:
            self._record_scrape_failure(slice_name, node_name, str(e))
            return None

    def _record_scrape_failure(self, slice_name: str, node_name: str, error: str):
        """Record a scrape failure and apply exponential backoff."""
        with self._state_lock:
            state = self._states.get(slice_name)
            if state and node_name in state.nodes:
                ns = state.nodes[node_name]
                ns.last_error = error
                ns.consecutive_failures += 1
                # Exponential backoff: 15s, 30s, 60s, 120s, 300s (capped)
                backoff = min(SCRAPE_INTERVAL * (2 ** ns.consecutive_failures),
                              self._MAX_BACKOFF)
                ns.next_scrape_after = time.time() + backoff
                logger.debug("Node %s/%s: failure #%d, backoff %ds",
                             slice_name, node_name,
                             ns.consecutive_failures, backoff)

    def _process_metrics(self, slice_name: str, node_name: str, raw: str) -> None:
        """Parse raw metrics text and update history."""
        now = time.time()
        parsed = _parse_prom_text(raw)

        with self._state_lock:
            state = self._states.get(slice_name)
            if state and node_name in state.nodes:
                state.nodes[node_name].last_scrape = now
                state.nodes[node_name].last_error = ""

        # Ensure history structures exist
        slice_hist = self._history.setdefault(slice_name, {})
        node_hist = slice_hist.setdefault(node_name, {})

        # --- CPU ---
        cpu_data = parsed.get("node_cpu_seconds_total", [])
        cpu_by_mode: Dict[str, float] = {}
        for entry in cpu_data:
            mode = entry["labels"].get("mode", "")
            cpu_by_mode[mode] = cpu_by_mode.get(mode, 0.0) + entry["value"]

        prev_cpu = self._prev_cpu.setdefault(slice_name, {}).get(node_name)
        prev_ts = self._prev_ts.setdefault(slice_name, {}).get(node_name)

        if prev_cpu and prev_ts and (now - prev_ts) > 0:
            dt = now - prev_ts
            total_delta = sum(cpu_by_mode.get(m, 0) - prev_cpu.get(m, 0) for m in cpu_by_mode)
            idle_delta = cpu_by_mode.get("idle", 0) - prev_cpu.get("idle", 0)
            if total_delta > 0:
                cpu_pct = 100.0 * (1.0 - idle_delta / total_delta)
                cpu_pct = max(0.0, min(100.0, cpu_pct))
                node_hist.setdefault("cpu_percent", deque(maxlen=MAX_SAMPLES)).append(
                    TimeSeriesPoint(t=now, v=round(cpu_pct, 2))
                )

        self._prev_cpu.setdefault(slice_name, {})[node_name] = cpu_by_mode
        self._prev_ts.setdefault(slice_name, {})[node_name] = now

        # --- Memory ---
        mem_total = 0.0
        mem_avail = 0.0
        for entry in parsed.get("node_memory_MemTotal_bytes", []):
            mem_total += entry["value"]
        for entry in parsed.get("node_memory_MemAvailable_bytes", []):
            mem_avail += entry["value"]
        if mem_total > 0:
            mem_pct = 100.0 * (1.0 - mem_avail / mem_total)
            node_hist.setdefault("memory_percent", deque(maxlen=MAX_SAMPLES)).append(
                TimeSeriesPoint(t=now, v=round(mem_pct, 2))
            )

        # --- Load ---
        for metric_name, key in [
            ("node_load1", "load1"),
            ("node_load5", "load5"),
            ("node_load15", "load15"),
        ]:
            vals = parsed.get(metric_name, [])
            if vals:
                node_hist.setdefault(key, deque(maxlen=MAX_SAMPLES)).append(
                    TimeSeriesPoint(t=now, v=round(vals[0]["value"], 3))
                )

        # --- Network ---
        prev_net = self._prev_net.setdefault(slice_name, {}).get(node_name, {})
        new_net: Dict[str, float] = {}
        for metric_name, direction in [
            ("node_network_receive_bytes_total", "rx"),
            ("node_network_transmit_bytes_total", "tx"),
        ]:
            for entry in parsed.get(metric_name, []):
                iface = entry["labels"].get("device", "unknown")
                if iface in ("lo",):
                    continue
                net_key = f"{iface}_{direction}"
                new_net[net_key] = entry["value"]
                if prev_ts and net_key in prev_net and (now - prev_ts) > 0:
                    dt = now - prev_ts
                    rate = max(0.0, (entry["value"] - prev_net[net_key]) / dt)
                    hist_key = f"net_{direction}_bytes.{iface}"
                    node_hist.setdefault(hist_key, deque(maxlen=MAX_SAMPLES)).append(
                        TimeSeriesPoint(t=now, v=round(rate, 2))
                    )

        self._prev_net.setdefault(slice_name, {})[node_name] = new_net

    async def _scrape_loop(self, slice_name: str) -> None:
        """Background task that scrapes all enabled nodes every SCRAPE_INTERVAL."""
        logger.info("Starting scrape loop for slice %s", slice_name)
        loop = asyncio.get_event_loop()
        while True:
            try:
                state = self._states.get(slice_name)
                if not state or not state.enabled:
                    break

                now = time.time()
                enabled_nodes = [
                    n for n, ns in state.nodes.items()
                    if ns.enabled and ns.exporter_installed
                    and now >= ns.next_scrape_after  # respect backoff
                ]
                if not enabled_nodes:
                    await asyncio.sleep(SCRAPE_INTERVAL)
                    continue

                # Scrape all nodes in parallel using thread pool
                futures = {
                    n: loop.run_in_executor(self._executor, self._scrape_node, slice_name, n)
                    for n in enabled_nodes
                }
                results = {}
                for n, fut in futures.items():
                    results[n] = await fut

                # Process results
                for n, raw in results.items():
                    if raw:
                        self._process_metrics(slice_name, n, raw)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scrape loop error for %s: %s", slice_name, e)

            await asyncio.sleep(SCRAPE_INTERVAL)

        logger.info("Scrape loop stopped for slice %s", slice_name)

    # -- Public API ---------------------------------------------------------

    def enable_slice(self, slice_name: str) -> Dict[str, Any]:
        """Enable monitoring for all nodes in a slice. Installs exporters."""
        nodes = self._get_slice_nodes(slice_name)
        with self._state_lock:
            state = self._states.setdefault(
                slice_name, SliceMonitoringState(slice_name=slice_name)
            )
            state.enabled = True
            for node in nodes:
                nname = node.get_name()
                if nname not in state.nodes:
                    state.nodes[nname] = NodeMonitoringState(name=nname)

        # Install node_exporter on each node
        results = {}
        for node in nodes:
            nname = node.get_name()
            try:
                msg = self.install_node_exporter(slice_name, nname)
                results[nname] = msg
            except Exception as e:
                results[nname] = f"Error: {e}"
                with self._state_lock:
                    state.nodes[nname].last_error = str(e)

        self._persist_state(slice_name)
        return results

    def disable_slice(self, slice_name: str) -> None:
        """Disable monitoring for a slice."""
        with self._state_lock:
            state = self._states.get(slice_name)
            if state:
                state.enabled = False
                for ns in state.nodes.values():
                    ns.enabled = False
                self._persist_state(slice_name)

        # Cancel scrape task
        task = self._tasks.pop(slice_name, None)
        if task:
            task.cancel()

    def enable_node(self, slice_name: str, node_name: str) -> str:
        """Enable monitoring for a single node."""
        msg = self.install_node_exporter(slice_name, node_name)
        self._ensure_scrape_loop(slice_name)
        return msg

    def disable_node(self, slice_name: str, node_name: str) -> None:
        """Disable monitoring for a single node."""
        with self._state_lock:
            state = self._states.get(slice_name)
            if state and node_name in state.nodes:
                state.nodes[node_name].enabled = False
                self._persist_state(slice_name)

    def _ensure_scrape_loop(self, slice_name: str) -> None:
        """Start scrape loop if not already running."""
        existing = self._tasks.get(slice_name)
        if existing and not existing.done():
            return
        try:
            loop = asyncio.get_event_loop()
            task = loop.create_task(self._scrape_loop(slice_name))
            self._tasks[slice_name] = task
        except RuntimeError:
            logger.warning("No event loop available to start scrape loop for %s", slice_name)

    def start_scrape_loop(self, slice_name: str) -> None:
        """Public method to start the scrape loop for a slice."""
        self._ensure_scrape_loop(slice_name)

    def get_status(self, slice_name: str) -> Dict[str, Any]:
        """Get monitoring status for a slice."""
        state = self._states.get(slice_name)
        if not state:
            return {"slice_name": slice_name, "enabled": False, "nodes": []}
        return {
            "slice_name": state.slice_name,
            "enabled": state.enabled,
            "nodes": [
                {
                    "name": ns.name,
                    "enabled": ns.enabled,
                    "exporter_installed": ns.exporter_installed,
                    "management_ip": ns.management_ip,
                    "site": ns.site,
                    "last_scrape": ns.last_scrape,
                    "last_error": ns.last_error,
                }
                for ns in state.nodes.values()
            ],
        }

    def get_latest_metrics(self, slice_name: str) -> Dict[str, Any]:
        """Get the most recent metric values for all nodes."""
        slice_hist = self._history.get(slice_name, {})
        result = {}
        for node_name, node_hist in slice_hist.items():
            latest = {}
            for key, dq in node_hist.items():
                if dq:
                    pt = dq[-1]
                    latest[key] = {"t": pt.t, "v": pt.v}
            result[node_name] = latest
        return {"slice_name": slice_name, "nodes": result}

    def get_history(self, slice_name: str, minutes: int = 30) -> Dict[str, Any]:
        """Get time-series history for charting."""
        cutoff = time.time() - (minutes * 60)
        slice_hist = self._history.get(slice_name, {})
        result = {}
        for node_name, node_hist in slice_hist.items():
            node_data: Dict[str, list] = {}
            for key, dq in node_hist.items():
                points = [{"t": pt.t, "v": pt.v} for pt in dq if pt.t >= cutoff]
                if points:
                    node_data[key] = points
            if node_data:
                result[node_name] = node_data
        return {"slice_name": slice_name, "nodes": result}

    def remove_slice(self, slice_name: str) -> None:
        """Clean up all monitoring state for a slice."""
        self.disable_slice(slice_name)
        self._history.pop(slice_name, None)
        self._prev_cpu.pop(slice_name, None)
        self._prev_net.pop(slice_name, None)
        self._prev_ts.pop(slice_name, None)
        with self._state_lock:
            self._states.pop(slice_name, None)
        try:
            path = self._state_file(slice_name)
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
