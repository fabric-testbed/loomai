"""Tests for tab completion system."""

from unittest.mock import patch, MagicMock
import time

from loomai_cli.completions import (
    SliceNameComplete, SiteNameComplete, WeaveNameComplete,
    RecipeNameComplete, _cache, _CACHE_TTL, _fetch_cached,
)
from loomai_cli.shell import _shell_completer, _completions_cache, _SHELL_COMMANDS


class TestFetchCached:
    def setup_method(self):
        _cache.clear()

    def test_returns_names_from_api(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"name": "slice-a"}, {"name": "slice-b"},
        ]
        with patch("httpx.get", return_value=mock_resp):
            names = _fetch_cached("test-key", "/slices")
        assert names == ["slice-a", "slice-b"]

    def test_cache_hit_avoids_api_call(self):
        _cache["cached-key"] = (time.time(), ["a", "b"])
        with patch("httpx.get") as mock:
            names = _fetch_cached("cached-key", "/anything")
        mock.assert_not_called()
        assert names == ["a", "b"]

    def test_stale_cache_triggers_fetch(self):
        _cache["stale-key"] = (time.time() - _CACHE_TTL - 1, ["old"])
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"name": "new"}]
        with patch("httpx.get", return_value=mock_resp):
            names = _fetch_cached("stale-key", "/slices")
        assert names == ["new"]

    def test_error_returns_stale_cache(self):
        _cache["err-key"] = (time.time() - 100, ["stale-val"])
        with patch("httpx.get", side_effect=Exception("network error")):
            names = _fetch_cached("err-key", "/slices")
        assert names == ["stale-val"]


class TestSliceNameComplete:
    def test_returns_matching_completions(self):
        comp = SliceNameComplete()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"name": "my-exp"}, {"name": "my-test"}, {"name": "other"},
        ]
        _cache.clear()
        with patch("httpx.get", return_value=mock_resp):
            items = comp.shell_complete(None, None, "my-")
        assert len(items) == 2
        assert items[0].value == "my-exp"
        assert items[1].value == "my-test"


class TestSiteNameComplete:
    def test_returns_matching_sites(self):
        comp = SiteNameComplete()
        _cache["sites"] = (time.time(), ["RENC", "UCSD", "UTAH"])
        items = comp.shell_complete(None, None, "U")
        assert len(items) == 2


class TestShellCompleter:
    """Test the readline completer function used in the interactive shell."""

    def test_completes_top_level_commands(self):
        with patch("readline.get_line_buffer", return_value="sli"):
            result = _shell_completer("sli", 0)
        assert result == "slices"

    def test_completes_subcommands(self):
        with patch("readline.get_line_buffer", return_value="slices "):
            result = _shell_completer("", 0)
        # Should return first matching subcommand
        assert result in _SHELL_COMMANDS["slices"]

    def test_completes_shell_builtins(self):
        with patch("readline.get_line_buffer", return_value="us"):
            result = _shell_completer("us", 0)
        assert result == "use"

    def test_returns_none_when_exhausted(self):
        with patch("readline.get_line_buffer", return_value="zzz"):
            result = _shell_completer("zzz", 0)
        assert result is None

    def test_completes_use_types(self):
        with patch("readline.get_line_buffer", return_value="use sl"):
            result = _shell_completer("sl", 0)
        assert result == "slice"
