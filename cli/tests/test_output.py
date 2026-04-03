"""Tests for output formatting."""

import json

from loomai_cli.output import format_table, format_json, format_yaml


class TestFormatTable:
    def test_basic_table(self):
        rows = [{"name": "a", "state": "Active"}, {"name": "b", "state": "Dead"}]
        result = format_table(rows, ["name", "state"])
        assert "a" in result
        assert "b" in result
        assert "Active" in result

    def test_empty_rows(self):
        result = format_table([], ["name"])
        assert "no results" in result

    def test_missing_column(self):
        rows = [{"name": "a"}]
        result = format_table(rows, ["name", "missing"])
        assert "a" in result

    def test_custom_headers(self):
        rows = [{"n": "test"}]
        result = format_table(rows, ["n"], headers=["Name"])
        assert "Name" in result


class TestFormatJson:
    def test_basic(self):
        data = {"name": "test", "count": 42}
        result = format_json(data)
        parsed = json.loads(result)
        assert parsed == data

    def test_list(self):
        data = [1, 2, 3]
        result = format_json(data)
        assert json.loads(result) == data


class TestFormatYaml:
    def test_basic(self):
        data = {"name": "test"}
        result = format_yaml(data)
        assert "name: test" in result
