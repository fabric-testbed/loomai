"""Tests for the monitoring manager — Prometheus metric parsing and computation.

Focuses on data processing logic (_parse_prom_text, _process_metrics, etc.)
rather than SSH transport, which requires live VMs.
"""

from __future__ import annotations

import time
from collections import deque
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Prometheus text parser
# ---------------------------------------------------------------------------

class TestParsePromText:
    def test_basic_metric(self):
        from app.monitoring_manager import _parse_prom_text

        text = 'node_cpu_seconds_total{cpu="0",mode="idle"} 12345.67\n'
        result = _parse_prom_text(text)
        assert "node_cpu_seconds_total" in result
        entry = result["node_cpu_seconds_total"][0]
        assert entry["labels"]["cpu"] == "0"
        assert entry["labels"]["mode"] == "idle"
        assert entry["value"] == 12345.67

    def test_metric_without_labels(self):
        from app.monitoring_manager import _parse_prom_text

        text = "node_load1 0.42\n"
        result = _parse_prom_text(text)
        assert "node_load1" in result
        assert result["node_load1"][0]["labels"] == {}
        assert result["node_load1"][0]["value"] == 0.42

    def test_comments_and_blank_lines_skipped(self):
        from app.monitoring_manager import _parse_prom_text

        text = (
            "# HELP node_load1 1m load average\n"
            "# TYPE node_load1 gauge\n"
            "\n"
            "node_load1 1.5\n"
        )
        result = _parse_prom_text(text)
        assert "node_load1" in result
        assert len(result) == 1

    def test_multiple_metrics(self):
        from app.monitoring_manager import _parse_prom_text

        text = (
            'node_cpu_seconds_total{cpu="0",mode="idle"} 100.0\n'
            'node_cpu_seconds_total{cpu="0",mode="user"} 50.0\n'
            'node_cpu_seconds_total{cpu="1",mode="idle"} 90.0\n'
            "node_load1 2.0\n"
            "node_memory_MemTotal_bytes 8589934592\n"
        )
        result = _parse_prom_text(text)
        assert len(result["node_cpu_seconds_total"]) == 3
        assert len(result["node_load1"]) == 1
        assert result["node_memory_MemTotal_bytes"][0]["value"] == 8589934592.0

    def test_scientific_notation(self):
        from app.monitoring_manager import _parse_prom_text

        text = "node_memory_MemTotal_bytes 8.589934592e+09\n"
        result = _parse_prom_text(text)
        assert abs(result["node_memory_MemTotal_bytes"][0]["value"] - 8589934592.0) < 1

    def test_metric_with_timestamp(self):
        from app.monitoring_manager import _parse_prom_text

        text = 'node_cpu_seconds_total{cpu="0",mode="idle"} 100.0 1711555200000\n'
        result = _parse_prom_text(text)
        assert result["node_cpu_seconds_total"][0]["value"] == 100.0

    def test_nan_value_skipped(self):
        from app.monitoring_manager import _parse_prom_text

        text = "node_load1 NaN\n"
        result = _parse_prom_text(text)
        # NaN parses as float('nan'), which is valid
        if "node_load1" in result:
            import math
            assert math.isnan(result["node_load1"][0]["value"])

    def test_empty_input(self):
        from app.monitoring_manager import _parse_prom_text

        assert _parse_prom_text("") == {}
        assert _parse_prom_text("  \n\n  ") == {}

    def test_malformed_lines_skipped(self):
        from app.monitoring_manager import _parse_prom_text

        text = (
            "this is not a metric line\n"
            "node_load1 1.0\n"
            "also bad {key=val} 99\n"
        )
        result = _parse_prom_text(text)
        assert "node_load1" in result
        assert len(result) == 1


# ---------------------------------------------------------------------------
# MonitoringManager — data processing
# ---------------------------------------------------------------------------

@pytest.fixture()
def manager(tmp_path):
    """Create a MonitoringManager with mocked storage and FABlib."""
    with patch("app.monitoring_manager.get_user_storage", return_value=str(tmp_path)), \
         patch("app.monitoring_manager.get_fablib"):
        from app.monitoring_manager import MonitoringManager
        mgr = MonitoringManager()
        yield mgr


class TestProcessMetrics:
    """Test _process_metrics which computes CPU%, memory%, load, and network rates."""

    _SAMPLE_METRICS = (
        '# HELP node_cpu_seconds_total Seconds the CPUs spent in each mode.\n'
        '# TYPE node_cpu_seconds_total counter\n'
        'node_cpu_seconds_total{cpu="0",mode="idle"} 900.0\n'
        'node_cpu_seconds_total{cpu="0",mode="user"} 50.0\n'
        'node_cpu_seconds_total{cpu="0",mode="system"} 30.0\n'
        'node_cpu_seconds_total{cpu="0",mode="iowait"} 20.0\n'
        'node_memory_MemTotal_bytes 8589934592\n'
        'node_memory_MemAvailable_bytes 4294967296\n'
        'node_load1 1.5\n'
        'node_load5 1.2\n'
        'node_load15 0.9\n'
        'node_network_receive_bytes_total{device="eth0"} 1000000\n'
        'node_network_transmit_bytes_total{device="eth0"} 500000\n'
        'node_network_receive_bytes_total{device="lo"} 99999\n'
        'node_network_transmit_bytes_total{device="lo"} 99999\n'
    )

    def test_memory_percentage(self, manager):
        """Memory = 100 * (1 - available/total) = 50%."""
        from app.monitoring_manager import SliceMonitoringState, NodeMonitoringState
        manager._states["slice1"] = SliceMonitoringState(
            slice_name="slice1",
            enabled=True,
            nodes={"node1": NodeMonitoringState(name="node1", enabled=True)},
        )

        manager._process_metrics("slice1", "node1", self._SAMPLE_METRICS)

        hist = manager._history["slice1"]["node1"]
        assert "memory_percent" in hist
        mem_pt = hist["memory_percent"][-1]
        assert abs(mem_pt.v - 50.0) < 0.1

    def test_load_values(self, manager):
        from app.monitoring_manager import SliceMonitoringState, NodeMonitoringState
        manager._states["slice1"] = SliceMonitoringState(
            slice_name="slice1",
            enabled=True,
            nodes={"node1": NodeMonitoringState(name="node1", enabled=True)},
        )

        manager._process_metrics("slice1", "node1", self._SAMPLE_METRICS)

        hist = manager._history["slice1"]["node1"]
        assert hist["load1"][-1].v == 1.5
        assert hist["load5"][-1].v == 1.2
        assert hist["load15"][-1].v == 0.9

    def test_cpu_requires_two_samples(self, manager):
        """CPU percentage needs a previous sample to compute delta."""
        from app.monitoring_manager import SliceMonitoringState, NodeMonitoringState
        manager._states["slice1"] = SliceMonitoringState(
            slice_name="slice1",
            enabled=True,
            nodes={"node1": NodeMonitoringState(name="node1", enabled=True)},
        )

        # First scrape — no cpu_percent yet
        manager._process_metrics("slice1", "node1", self._SAMPLE_METRICS)
        hist = manager._history["slice1"]["node1"]
        assert "cpu_percent" not in hist

    def test_cpu_computed_after_two_samples(self, manager):
        """Second sample with increased counters produces a cpu_percent value."""
        from app.monitoring_manager import SliceMonitoringState, NodeMonitoringState
        manager._states["slice1"] = SliceMonitoringState(
            slice_name="slice1",
            enabled=True,
            nodes={"node1": NodeMonitoringState(name="node1", enabled=True)},
        )

        # First scrape
        manager._process_metrics("slice1", "node1", self._SAMPLE_METRICS)

        # Second scrape with increased counters
        metrics2 = (
            'node_cpu_seconds_total{cpu="0",mode="idle"} 910.0\n'
            'node_cpu_seconds_total{cpu="0",mode="user"} 55.0\n'
            'node_cpu_seconds_total{cpu="0",mode="system"} 33.0\n'
            'node_cpu_seconds_total{cpu="0",mode="iowait"} 22.0\n'
            'node_memory_MemTotal_bytes 8589934592\n'
            'node_memory_MemAvailable_bytes 4294967296\n'
        )
        manager._process_metrics("slice1", "node1", metrics2)

        hist = manager._history["slice1"]["node1"]
        assert "cpu_percent" in hist
        # Total delta = (910-900)+(55-50)+(33-30)+(22-20) = 10+5+3+2 = 20
        # Idle delta = 910-900 = 10
        # CPU% = 100*(1 - 10/20) = 50%
        assert abs(hist["cpu_percent"][-1].v - 50.0) < 0.1

    def test_network_rates_computed(self, manager):
        """Network byte rates require two samples (like CPU)."""
        from app.monitoring_manager import SliceMonitoringState, NodeMonitoringState
        manager._states["slice1"] = SliceMonitoringState(
            slice_name="slice1",
            enabled=True,
            nodes={"node1": NodeMonitoringState(name="node1", enabled=True)},
        )

        # First scrape
        manager._process_metrics("slice1", "node1", self._SAMPLE_METRICS)

        # Second scrape 10 seconds later with increased counters
        metrics2 = (
            'node_network_receive_bytes_total{device="eth0"} 1100000\n'
            'node_network_transmit_bytes_total{device="eth0"} 550000\n'
            'node_network_receive_bytes_total{device="lo"} 100000\n'
            'node_network_transmit_bytes_total{device="lo"} 100000\n'
            'node_memory_MemTotal_bytes 8589934592\n'
            'node_memory_MemAvailable_bytes 4294967296\n'
        )
        manager._process_metrics("slice1", "node1", metrics2)

        hist = manager._history["slice1"]["node1"]
        # Network rates should be present for eth0 but not lo
        rx_keys = [k for k in hist if k.startswith("net_rx_bytes.")]
        tx_keys = [k for k in hist if k.startswith("net_tx_bytes.")]
        assert any("eth0" in k for k in rx_keys)
        assert any("eth0" in k for k in tx_keys)
        assert not any("lo" in k for k in rx_keys)

    def test_loopback_excluded(self, manager):
        """Loopback interface (lo) should be excluded from network metrics."""
        from app.monitoring_manager import SliceMonitoringState, NodeMonitoringState
        manager._states["slice1"] = SliceMonitoringState(
            slice_name="slice1",
            enabled=True,
            nodes={"node1": NodeMonitoringState(name="node1", enabled=True)},
        )

        metrics_lo_only = (
            'node_network_receive_bytes_total{device="lo"} 99999\n'
            'node_network_transmit_bytes_total{device="lo"} 88888\n'
            'node_memory_MemTotal_bytes 1000\n'
            'node_memory_MemAvailable_bytes 500\n'
        )
        manager._process_metrics("slice1", "node1", metrics_lo_only)
        manager._process_metrics("slice1", "node1", metrics_lo_only)

        hist = manager._history["slice1"]["node1"]
        lo_keys = [k for k in hist if "lo" in k]
        assert lo_keys == []

    def test_zero_memory_total_no_crash(self, manager):
        """Zero total memory should not cause division by zero."""
        from app.monitoring_manager import SliceMonitoringState, NodeMonitoringState
        manager._states["slice1"] = SliceMonitoringState(
            slice_name="slice1",
            enabled=True,
            nodes={"node1": NodeMonitoringState(name="node1", enabled=True)},
        )

        metrics = (
            "node_memory_MemTotal_bytes 0\n"
            "node_memory_MemAvailable_bytes 0\n"
        )
        manager._process_metrics("slice1", "node1", metrics)
        hist = manager._history.get("slice1", {}).get("node1", {})
        assert "memory_percent" not in hist


# ---------------------------------------------------------------------------
# Monitoring state management
# ---------------------------------------------------------------------------

class TestStateManagement:
    def test_get_status_unknown_slice(self, manager):
        status = manager.get_status("nonexistent")
        assert status["enabled"] is False
        assert status["nodes"] == []

    def test_get_status_with_nodes(self, manager):
        from app.monitoring_manager import SliceMonitoringState, NodeMonitoringState
        manager._states["slice1"] = SliceMonitoringState(
            slice_name="slice1",
            enabled=True,
            nodes={
                "node1": NodeMonitoringState(
                    name="node1",
                    enabled=True,
                    exporter_installed=True,
                    management_ip="10.0.0.1",
                    site="TACC",
                )
            },
        )

        status = manager.get_status("slice1")
        assert status["enabled"] is True
        assert len(status["nodes"]) == 1
        assert status["nodes"][0]["name"] == "node1"
        assert status["nodes"][0]["management_ip"] == "10.0.0.1"

    def test_disable_slice(self, manager):
        from app.monitoring_manager import SliceMonitoringState, NodeMonitoringState
        manager._states["slice1"] = SliceMonitoringState(
            slice_name="slice1",
            enabled=True,
            nodes={"node1": NodeMonitoringState(name="node1", enabled=True)},
        )

        manager.disable_slice("slice1")
        assert manager._states["slice1"].enabled is False
        assert manager._states["slice1"].nodes["node1"].enabled is False

    def test_disable_node(self, manager):
        from app.monitoring_manager import SliceMonitoringState, NodeMonitoringState
        manager._states["slice1"] = SliceMonitoringState(
            slice_name="slice1",
            enabled=True,
            nodes={"node1": NodeMonitoringState(name="node1", enabled=True)},
        )

        manager.disable_node("slice1", "node1")
        assert manager._states["slice1"].nodes["node1"].enabled is False

    def test_remove_slice(self, manager):
        from app.monitoring_manager import SliceMonitoringState, NodeMonitoringState
        manager._states["slice1"] = SliceMonitoringState(
            slice_name="slice1",
            enabled=True,
            nodes={"node1": NodeMonitoringState(name="node1", enabled=True)},
        )
        manager._history["slice1"] = {"node1": {"cpu_percent": deque()}}
        manager._prev_cpu["slice1"] = {}
        manager._prev_net["slice1"] = {}
        manager._prev_ts["slice1"] = {}

        manager.remove_slice("slice1")

        assert "slice1" not in manager._states
        assert "slice1" not in manager._history
        assert "slice1" not in manager._prev_cpu

    def test_get_latest_metrics_empty(self, manager):
        result = manager.get_latest_metrics("nonexistent")
        assert result["nodes"] == {}

    def test_get_latest_metrics_with_data(self, manager):
        from app.monitoring_manager import TimeSeriesPoint
        now = time.time()
        manager._history["slice1"] = {
            "node1": {
                "cpu_percent": deque([TimeSeriesPoint(t=now, v=42.5)]),
                "memory_percent": deque([TimeSeriesPoint(t=now, v=60.0)]),
            }
        }

        result = manager.get_latest_metrics("slice1")
        assert result["nodes"]["node1"]["cpu_percent"]["v"] == 42.5
        assert result["nodes"]["node1"]["memory_percent"]["v"] == 60.0

    def test_get_history_with_cutoff(self, manager):
        from app.monitoring_manager import TimeSeriesPoint
        now = time.time()
        old = now - 3600  # 1 hour ago
        recent = now - 60  # 1 minute ago

        manager._history["slice1"] = {
            "node1": {
                "cpu_percent": deque([
                    TimeSeriesPoint(t=old, v=10.0),
                    TimeSeriesPoint(t=recent, v=50.0),
                ]),
            }
        }

        # 30 minutes — should exclude the 1-hour-old point
        result = manager.get_history("slice1", minutes=30)
        points = result["nodes"]["node1"]["cpu_percent"]
        assert len(points) == 1
        assert points[0]["v"] == 50.0

    def test_get_history_empty(self, manager):
        result = manager.get_history("nonexistent")
        assert result["nodes"] == {}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_persist_and_load(self, manager):
        from app.monitoring_manager import SliceMonitoringState, NodeMonitoringState

        manager._states["slice1"] = SliceMonitoringState(
            slice_name="slice1",
            enabled=True,
            nodes={
                "node1": NodeMonitoringState(
                    name="node1",
                    enabled=True,
                    exporter_installed=True,
                    management_ip="10.0.0.1",
                    username="cc",
                    site="TACC",
                )
            },
        )

        manager._persist_state("slice1")

        # Create a new manager and verify it loads the state
        with patch("app.monitoring_manager.get_user_storage", return_value=manager._state_dir().rsplit("/.monitoring", 1)[0]):
            from app.monitoring_manager import MonitoringManager
            mgr2 = MonitoringManager()

        assert "slice1" in mgr2._states
        assert mgr2._states["slice1"].enabled is True
        assert "node1" in mgr2._states["slice1"].nodes

    def test_persist_nonexistent_state(self, manager):
        # Should not crash
        manager._persist_state("nonexistent")


# ---------------------------------------------------------------------------
# Scrape failure / backoff
# ---------------------------------------------------------------------------

class TestScrapeBackoff:
    def test_record_failure_increments_backoff(self, manager):
        from app.monitoring_manager import SliceMonitoringState, NodeMonitoringState, SCRAPE_INTERVAL

        manager._states["slice1"] = SliceMonitoringState(
            slice_name="slice1",
            enabled=True,
            nodes={"node1": NodeMonitoringState(name="node1", enabled=True)},
        )

        manager._record_scrape_failure("slice1", "node1", "timeout")
        ns = manager._states["slice1"].nodes["node1"]
        assert ns.consecutive_failures == 1
        assert ns.last_error == "timeout"
        assert ns.next_scrape_after > time.time()

    def test_consecutive_failures_increase_backoff(self, manager):
        from app.monitoring_manager import SliceMonitoringState, NodeMonitoringState

        manager._states["slice1"] = SliceMonitoringState(
            slice_name="slice1",
            enabled=True,
            nodes={"node1": NodeMonitoringState(name="node1", enabled=True)},
        )

        manager._record_scrape_failure("slice1", "node1", "err1")
        t1 = manager._states["slice1"].nodes["node1"].next_scrape_after

        manager._record_scrape_failure("slice1", "node1", "err2")
        t2 = manager._states["slice1"].nodes["node1"].next_scrape_after

        # Second failure should have a later backoff time
        assert t2 > t1
        assert manager._states["slice1"].nodes["node1"].consecutive_failures == 2

    def test_backoff_capped(self, manager):
        from app.monitoring_manager import SliceMonitoringState, NodeMonitoringState

        manager._states["slice1"] = SliceMonitoringState(
            slice_name="slice1",
            enabled=True,
            nodes={"node1": NodeMonitoringState(name="node1", enabled=True)},
        )

        # Many failures to hit the cap
        for _ in range(20):
            manager._record_scrape_failure("slice1", "node1", "err")

        ns = manager._states["slice1"].nodes["node1"]
        backoff = ns.next_scrape_after - time.time()
        assert backoff <= manager._MAX_BACKOFF + 1  # small tolerance
