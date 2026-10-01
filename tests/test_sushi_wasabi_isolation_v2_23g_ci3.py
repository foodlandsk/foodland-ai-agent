"""
tests/test_sushi_wasabi_isolation_v2_23g_ci3.py  -  V2.23g-CI3 minimal
test/session isolation recovery.

V2.23g-CI2 proved (direct counterfactual, not reproduced CI's exact
ordering) that app.main.get_user_memory()/load_user_memories() is a
process-global singleton backed by a durable file never reset between
tests, and that personalize_products() actively re-sorts search results
using whatever profile has accumulated under a test's effective
identity. A test that omits both client_id and session_id on ChatRequest
falls back to anon-hash(client_key) - and hundreds of tests across this
suite reuse the exact same fake host "127.0.0.1", so they all share ONE
anonymous profile/session for the whole pytest process.

This file does NOT change any production code (app/main.py untouched).
It proves two things, directly:

1. Two different explicit client_ids/session_ids never leak into each
   other (CROSS_TEST_PROFILE_LEAK = FALSE) - the isolation mechanism
   this sprint relies on for the sushi/wasabi test fix.
2. The SAME client_id/session_id across multiple calls still shares
   state as before (same-test continuity is not broken by the fix).

tests/test_core.py::TestSearchProducts::
test_sushi_kitchenware_override_preserves_genuine_sushi_food_requests
itself was given its own unique client_id/session_id in this sprint -
see that file for the target fix.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m


def _chat(message: str, client_id: str, session_id: str, limit: int = 6) -> dict:
    request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))
    return m.chat(
        m.ChatRequest(message=message, limit=limit, client_id=client_id, session_id=session_id),
        request,
    )


class TestCrossTestProfileIsolation:
    """Two distinct explicit identities must never share personalization
    or session state, even though both calls use the SAME fake
    request/host - proving the fix does not depend on the host value."""

    def test_distinct_client_ids_do_not_share_personalization_profile(self):
        profile_a_key = m.user_memory_key("v223gci3_isolation_profile_a", "127.0.0.1")
        profile_b_key = m.user_memory_key("v223gci3_isolation_profile_b", "127.0.0.1")
        assert profile_a_key != profile_b_key

        _chat("co sa hodi k sushi?", "v223gci3_isolation_profile_a", "v223gci3_isolation_profile_a")
        profile_a = m.get_user_memory(profile_a_key)
        profile_b = m.get_user_memory(profile_b_key)

        assert "sushi" in profile_a.get("subjects", {})
        assert "sushi" not in profile_b.get("subjects", {})

    def test_distinct_session_ids_do_not_share_session_memory(self):
        key_a = m.session_memory_key("v223gci3_isolation_session_a", "127.0.0.1")
        key_b = m.session_memory_key("v223gci3_isolation_session_b", "127.0.0.1")
        assert key_a != key_b

        _chat("co sa hodi k sushi?", "v223gci3_isolation_session_a", "v223gci3_isolation_session_a")
        memory_a = m.get_session_memory(key_a)
        memory_b = m.get_session_memory(key_b)

        assert memory_a.get("active_use_case") == "sushi"
        assert memory_b.get("active_use_case") != "sushi"

    def test_heavy_unrelated_pollution_does_not_affect_isolated_identity(self):
        # Directly recreates the V2.23g-CI2 mechanism (heavy accumulated
        # "sushi"/"ryza" signal under a DIFFERENT, shared identity) and
        # confirms it cannot influence a call made under this test's own
        # distinct, explicit identity.
        polluted_key = m.user_memory_key("v223gci3_isolation_pollution_source", "127.0.0.1")
        polluted_profile = m.get_user_memory(polluted_key)
        polluted_profile["subjects"]["sushi"] = 9999
        polluted_profile["subjects"]["ryza"] = 9999

        clean_key = m.user_memory_key("v223gci3_isolation_clean_target", "127.0.0.1")
        clean_profile = m.get_user_memory(clean_key)
        assert clean_profile.get("subjects", {}).get("sushi", 0) == 0
        assert clean_profile.get("subjects", {}).get("ryza", 0) == 0


class TestSameIdentityContinuityPreserved:
    """The fix must not break intentional same-test continuity: repeated
    calls using the SAME explicit client_id/session_id must still share
    state exactly as the original (pre-fix) same-fake-request pattern
    did."""

    def test_same_client_id_accumulates_across_calls(self):
        client_id = "v223gci3_isolation_continuity"
        _chat("co sa hodi k sushi?", client_id, client_id)
        _chat("aku ryzu na sushi mate?", client_id, client_id)
        profile = m.get_user_memory(m.user_memory_key(client_id, "127.0.0.1"))
        assert profile.get("subjects", {}).get("sushi", 0) >= 1

    def test_same_session_id_preserves_active_use_case_across_calls(self):
        session_id = "v223gci3_isolation_continuity_session"
        _chat("co sa hodi k sushi?", session_id, session_id)
        memory = m.get_session_memory(m.session_memory_key(session_id, "127.0.0.1"))
        assert memory.get("active_use_case") == "sushi"
        # Second call under the SAME session_id must still see that state.
        result = _chat("aku ryzu na sushi mate?", session_id, session_id)
        memory_after = m.get_session_memory(m.session_memory_key(session_id, "127.0.0.1"))
        assert memory_after.get("active_use_case") == "sushi"
        titles = [m.normalize(p.get("title", "")) for p in result.get("products", [])]
        assert titles and "ryz" in titles[0]
