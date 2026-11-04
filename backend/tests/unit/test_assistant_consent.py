"""Consent rules for destructive assistant tools."""
import pytest

from app import assistant_consent as consent


@pytest.fixture(autouse=True)
def _clear_pending():
    consent._pending.clear()
    yield
    consent._pending.clear()


class TestWordBoundaries:
    def test_testbed_is_not_test(self):
        # "test" inside "testbed" used to count as an operational-proof term.
        assert not consent.text_authorizes_provisioning(
            "create a slice on the FABRIC testbed with 2 nodes")

    def test_real_build_and_prove_authorizes(self):
        assert consent.text_authorizes_provisioning(
            "Create a two-node slice named bench-l2 and demonstrate inter-node ping.")

    def test_explicit_verb_authorizes(self):
        assert consent.text_authorizes_provisioning("please submit it")
        assert consent.text_authorizes_provisioning("Deploy the draft now")

    def test_look_is_not_ok(self):
        # "ok" inside "look" used to count as a confirmation.
        assert not consent.text_confirms_destruction(
            "look at slice foo and remove node1", ["foo"])

    def test_delete_confirmation_needs_target_delete_and_confirm(self):
        assert consent.text_confirms_destruction("yes, delete old-slice", ["old-slice"])
        assert not consent.text_confirms_destruction("delete old-slice", ["old-slice"])
        assert not consent.text_confirms_destruction("yes, delete it", ["old-slice"])
        assert not consent.text_confirms_destruction("yes delete old-slice-2", ["old-slice"])

    def test_hyphenated_names_match_whole(self):
        assert consent._mentions("drop bench-l2 now, confirmed", "bench-l2")
        assert not consent._mentions("drop bench-l2-copy now", "bench-l2")


class TestBareConfirmation:
    @pytest.mark.parametrize("text", ["yes", "Yes.", "ok go ahead", "yes, delete_slice",
                                      "confirm", "Go ahead please", "proceed"])
    def test_accepts(self, text):
        assert consent.is_bare_confirmation(text)

    @pytest.mark.parametrize("text", ["no", "yes but not yet", "ok, cancel that", "wait",
                                      "", "ok so now create another slice called x and " * 3,
                                      "yesterday it worked"])
    def test_rejects(self, text):
        assert not consent.is_bare_confirmation(text)


class TestPendingAction:
    def test_bare_yes_authorizes_exactly_the_pending_call(self):
        consent.record_pending("c1", "delete_slice", {"slice_name": "old-slice"})

        assert consent.is_destructive_tool_authorized(
            "delete_slice", {"slice_name": "old-slice"},
            user_texts=["delete slice old-slice", "yes"], latest_user_text="yes",
            created_slices=set(), conversation_id="c1")
        # Consumed: a second identical call needs a new confirmation.
        assert consent.pending_for("c1") is None
        assert not consent.is_destructive_tool_authorized(
            "delete_slice", {"slice_name": "old-slice"},
            user_texts=["delete slice old-slice", "yes"], latest_user_text="yes",
            created_slices=set(), conversation_id="c1")

    def test_yes_does_not_authorize_a_different_target_or_tool(self):
        consent.record_pending("c1", "delete_slice", {"slice_name": "old-slice"})
        common = dict(user_texts=["delete old-slice", "yes"], latest_user_text="yes",
                      created_slices=set(), conversation_id="c1")
        assert not consent.is_destructive_tool_authorized(
            "delete_slice", {"slice_name": "other-slice"}, **common)
        assert not consent.is_destructive_tool_authorized(
            "submit_slice", {"slice_name": "old-slice"}, **common)
        assert consent.pending_for("c1") is not None  # still waiting

    def test_yes_from_another_conversation_does_nothing(self):
        consent.record_pending("c1", "delete_slice", {"slice_name": "old-slice"})
        assert not consent.is_destructive_tool_authorized(
            "delete_slice", {"slice_name": "old-slice"},
            user_texts=["yes"], latest_user_text="yes",
            created_slices=set(), conversation_id="c2")

    def test_incidental_args_may_differ(self):
        consent.record_pending("c1", "submit_slice", {"slice_name": "s", "lease_hours": 6})
        assert consent.consume_if_confirmed("c1", "yes", "submit_slice",
                                            {"slice_name": "s", "lease_hours": 4, "wait": True})

    def test_expires(self, monkeypatch):
        consent.record_pending("c1", "delete_slice", {"slice_name": "s"})
        monkeypatch.setattr(consent.time, "time",
                            lambda: consent._pending["c1"].created_at + consent.PENDING_TTL_SECONDS + 1)
        assert consent.pending_for("c1") is None

    def test_no_conversation_id_records_nothing(self):
        consent.record_pending("", "delete_slice", {"slice_name": "s"})
        assert not consent._pending


class TestDecision:
    def test_old_confirmation_does_not_confirm_a_new_delete(self):
        # Confirmation is read from the latest turn only.
        assert not consent.is_destructive_tool_authorized(
            "delete_slice", {"slice_name": "foo"},
            user_texts=["yes, delete foo", "now list my slices"],
            latest_user_text="now list my slices", created_slices=set())

    def test_same_turn_explicit_delete_confirmation(self):
        assert consent.is_destructive_tool_authorized(
            "delete_slice", {"slice_name": "foo"},
            user_texts=["yes, delete slice foo"], latest_user_text="yes, delete slice foo",
            created_slices=set())

    def test_submit_of_slice_created_here_rides_on_earlier_goal(self):
        texts = ["Create a slice named bench and verify ping works", "continue"]
        assert consent.is_destructive_tool_authorized(
            "submit_slice", {"slice_name": "bench"},
            user_texts=texts, latest_user_text="continue", created_slices={"bench"})

    def test_cold_submit_needs_latest_turn(self):
        assert not consent.is_destructive_tool_authorized(
            "submit_slice", {"slice_name": "bench"},
            user_texts=["continue"], latest_user_text="continue", created_slices=set())
        assert consent.is_destructive_tool_authorized(
            "submit_slice", {"slice_name": "bench"},
            user_texts=["submit bench"], latest_user_text="submit bench", created_slices=set())

    def test_other_destructive_tools_need_named_confirmation(self):
        assert not consent.is_destructive_tool_authorized(
            "delete_path", {"path": "results/old"},
            user_texts=["clean up results/old"], latest_user_text="clean up results/old",
            created_slices=set())
        assert consent.is_destructive_tool_authorized(
            "delete_path", {"path": "results/old"},
            user_texts=["yes, delete results/old"], latest_user_text="yes, delete results/old",
            created_slices=set())

    def test_confirmation_instruction_names_the_target(self):
        text = consent.confirmation_instruction("delete_slice", {"slice_name": "foo"})
        assert "delete_slice on 'foo'" in text and "reply 'yes'" in text
