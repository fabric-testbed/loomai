"""Tests for app.chat_intent — intent detection and template matching."""

import pytest

from app.chat_intent import detect_intent, is_destructive
from app.chat_templates import match_template


class TestDetectIntent:
    """Test intent pattern matching."""

    def test_list_slices(self):
        tool, args, conf = detect_intent("list my slices")
        assert tool == "list_slices"
        assert conf == "high"

    def test_show_slices(self):
        tool, args, conf = detect_intent("show slices")
        assert tool == "list_slices"
        assert conf == "high"

    def test_what_slices(self):
        tool, args, conf = detect_intent("what slices do I have")
        assert tool == "list_slices"
        assert conf == "high"

    def test_show_specific_slice(self):
        tool, args, conf = detect_intent("show slice my-exp")
        assert tool == "get_slice"
        assert args["slice_name"] == "my-exp"
        assert conf == "high"

    def test_slice_status(self):
        tool, args, conf = detect_intent("what's the state of test-slice")
        assert tool == "get_slice"
        assert args["slice_name"] == "test-slice"

    def test_available_sites(self):
        tool, args, conf = detect_intent("what sites are available")
        assert tool == "query_sites"
        assert conf == "high"

    def test_find_gpu_sites(self):
        tool, args, conf = detect_intent("find sites with GPU")
        assert tool == "query_sites"

    def test_list_sites(self):
        tool, args, conf = detect_intent("list all sites")
        assert tool == "query_sites"

    def test_show_resources(self):
        tool, args, conf = detect_intent("show me available resources")
        assert tool == "query_sites"

    def test_site_hosts(self):
        tool, args, conf = detect_intent("show hosts at RENC")
        assert tool == "get_site_hosts"
        assert args["site_name"] == "RENC"

    def test_create_slice(self):
        tool, args, conf = detect_intent("create slice my-new-exp")
        assert tool == "create_slice"
        assert args["name"] == "my-new-exp"
        assert conf == "medium"

    def test_delete_slice(self):
        tool, args, conf = detect_intent("delete slice my-exp")
        assert tool == "delete_slice"
        assert args["slice_name"] == "my-exp"
        assert conf == "medium"

    def test_renew_slice(self):
        tool, args, conf = detect_intent("renew slice my-exp")
        assert tool == "renew_slice"
        assert args["slice_name"] == "my-exp"
        assert args["days"] == 7

    def test_submit_slice(self):
        tool, args, conf = detect_intent("submit my-exp")
        assert tool == "submit_slice"
        assert args["slice_name"] == "my-exp"

    def test_list_templates(self):
        tool, args, conf = detect_intent("list weaves")
        assert tool == "list_templates"

    def test_list_artifacts(self):
        tool, args, conf = detect_intent("browse marketplace")
        assert tool == "list_artifacts"

    def test_list_recipes(self):
        tool, args, conf = detect_intent("list recipes")
        assert tool == "list_recipes"

    def test_greeting_low_confidence(self):
        tool, args, conf = detect_intent("hello")
        assert conf == "low"

    def test_help_low_confidence(self):
        tool, args, conf = detect_intent("help")
        assert conf == "low"

    def test_ambiguous_low_confidence(self):
        tool, args, conf = detect_intent("I need help with my experiment")
        assert conf == "low"

    def test_empty_message(self):
        tool, args, conf = detect_intent("")
        assert conf == "low"
        assert tool == ""

    def test_validate_slice(self):
        tool, args, conf = detect_intent("validate my-slice")
        assert tool == "validate_slice"
        assert args["slice_name"] == "my-slice"


class TestIsDestructive:
    def test_delete_is_destructive(self):
        assert is_destructive("delete_slice")

    def test_submit_is_destructive(self):
        assert is_destructive("submit_slice")

    def test_list_is_not_destructive(self):
        assert not is_destructive("list_slices")

    def test_query_is_not_destructive(self):
        assert not is_destructive("query_sites")


class TestMatchTemplate:
    def test_create_2_node_slice(self):
        result = match_template("create a 2-node slice at RENC called my-test")
        assert result is not None
        assert result["name"] == "create_multi_node_slice"
        assert len(result["steps"]) >= 3  # create + 2 nodes + network

    def test_create_3_node_cluster(self):
        result = match_template("create a 3 node cluster")
        assert result is not None
        assert len([s for s in result["steps"] if s[0] == "add_node"]) == 3

    def test_deploy_hello_fabric(self):
        result = match_template("run hello fabric")
        assert result is not None
        assert result["name"] == "deploy_hello_fabric"

    def test_delete_dead_slices(self):
        result = match_template("delete all dead slices")
        assert result is not None
        assert result["confirm"] is True

    def test_no_match(self):
        result = match_template("tell me about FABRIC")
        assert result is None
