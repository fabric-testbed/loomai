"""Repeated-tool guard: a long-running poll is not a stuck tool.

A weave provisioning a FABRIC slice is silent for minutes, so identical
get_background_run_output results are the correct answer. The guard still has
to bound the polling — the model cannot wait — but reporting it as "the tool
result did not change" made a healthy 8-12 minute run read as a failure.
"""

import json

from app.routes.ai_chat import _is_still_running_poll, _record_tool_progress


def _poll(tracker, result, tool="get_background_run_output", args=None):
    return _record_tool_progress(tracker, tool, args or {"run_id": "r1"}, result, limit=3)


class TestStillRunningDetection:
    def test_running_status_detected_in_json_text(self):
        assert _is_still_running_poll(json.dumps({"status": "running", "output": ""}),
                                     "get_background_run_output")

    def test_running_status_detected_in_dict(self):
        assert _is_still_running_poll({"status": "running"}, "get_background_run_output")

    def test_pending_and_starting_count_as_running(self):
        assert _is_still_running_poll({"status": "pending"}, "get_background_run_output")
        assert _is_still_running_poll({"status": "starting"}, "get_background_run_output")

    def test_terminal_states_do_not(self):
        for status in ("completed", "error", "stopped", "unknown"):
            assert not _is_still_running_poll({"status": status},
                                              "get_background_run_output"), status

    def test_non_json_and_non_dict_do_not_crash(self):
        assert not _is_still_running_poll("not json", "get_background_run_output")
        assert not _is_still_running_poll(["a", "list"], "get_background_run_output")
        assert not _is_still_running_poll(None, "get_background_run_output")


class TestGuardStillBoundsPolling:
    def test_a_running_poll_is_still_stopped(self):
        """The model has no way to wait, so unbounded polling must not happen."""
        tracker, result = {}, json.dumps({"status": "running", "output": "x"})
        assert _poll(tracker, result) is None
        assert _poll(tracker, result) is None
        stop = _poll(tracker, result)
        assert stop is not None, "polling must remain bounded"

    def test_but_it_is_reported_as_still_running_not_no_progress(self):
        tracker, result = {}, json.dumps({"status": "running", "output": "x"})
        for _ in range(2):
            _poll(tracker, result)
        stop = _poll(tracker, result)
        assert stop["reason"] == "still_running"
        assert "still in progress" in stop["message"]
        assert "did not change" not in stop["message"]

    def test_a_genuinely_stuck_tool_is_still_no_progress(self):
        """The original guard behaviour must survive for non-polling tools."""
        tracker, result = {}, json.dumps({"topics": ["cpu"]})
        for _ in range(2):
            _poll(tracker, result, tool="list_metric_topics", args={})
        stop = _poll(tracker, result, tool="list_metric_topics", args={})
        assert stop["reason"] == "no_progress"

    def test_a_finished_run_polled_repeatedly_is_no_progress(self):
        """Once the run is done, repeated identical polls really are stuck."""
        tracker, result = {}, json.dumps({"status": "completed", "output": "done"})
        for _ in range(2):
            _poll(tracker, result)
        stop = _poll(tracker, result)
        assert stop["reason"] == "no_progress"


class TestOnlyRunPollersAreExempt:
    """status="running" means READY in plenty of results.

    ai_terminal returns it for a web service that is already serving. Treating
    that as an unfinished run would tell the user to check back on something
    already up — worse than the message this all started from.
    """

    def test_a_ready_service_is_not_a_running_poll(self):
        ready = {"port": 4096, "status": "running"}
        assert not _is_still_running_poll(ready, "get_ai_tool_status")
        assert not _is_still_running_poll(ready, "")

    def test_a_ready_service_polled_repeatedly_reports_no_progress(self):
        tracker = {}
        ready = json.dumps({"port": 4096, "status": "running"})
        for _ in range(2):
            _poll(tracker, ready, tool="get_ai_tool_status", args={"tool": "opencode"})
        stop = _poll(tracker, ready, tool="get_ai_tool_status", args={"tool": "opencode"})
        assert stop["reason"] == "no_progress"

    def test_job_status_is_exempt_too(self):
        """submit_slice(background=true) hands back a job to poll."""
        assert _is_still_running_poll({"status": "running"}, "get_job_status")
