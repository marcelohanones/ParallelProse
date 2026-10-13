"""Item 45.1: the per-role tracker and the run-record writer. No API is called here."""

import json
from datetime import datetime, timezone

import pytest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from ParallelProse.run_record import (RoleUsageTracker, cache_read_tokens, is_peak, prompt_sha, role_of,
                                       write_run_record)


def llm_result(model="gpt-4o-mini-2024-07-18", input_tokens=100, output_tokens=20, cache_read=40, tier=None):
    details = {f"{tier}_cache_read" if tier else "cache_read": cache_read}
    message = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": input_tokens, "output_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens, "input_token_details": details},
        response_metadata={"model_name": model})
    return LLMResult(generations=[[ChatGeneration(message=message, text="ok")]])


def start(tracker, run_id, tags):
    tracker.on_chat_model_start({}, [SystemMessage(content="s"), HumanMessage(content="p")], run_id=run_id, tags=tags)


def test_role_of_needs_exactly_one_role_tag():
    assert role_of(["seq:step:2", "role:composer"]) == ("composer", ["composer"])
    assert role_of(["role:composer", "role:reflect"]) == (None, ["composer", "reflect"])
    assert role_of(["seq:step:2"]) == (None, [])


def test_prompt_sha_is_stable_and_content_addressed():
    messages = [HumanMessage(content="same")]
    assert prompt_sha(messages) == prompt_sha([HumanMessage(content="same")])
    assert prompt_sha(messages) != prompt_sha([HumanMessage(content="other")])


def test_prompt_sha_handles_the_batch_shape_and_covers_tool_calls():
    batch = [[HumanMessage(content="p")]]
    assert prompt_sha(batch) == prompt_sha([[HumanMessage(content="p")]])
    assert prompt_sha(batch) != prompt_sha([[HumanMessage(content="q")]])
    plain = [AIMessage(content="")]
    with_tool = [AIMessage(content="", tool_calls=[{"id": "1", "name": "t", "args": {"q": "x"}}])]
    assert prompt_sha(plain) != prompt_sha(with_tool)


def test_cache_read_matches_any_service_tier_suffix():
    assert cache_read_tokens({"input_token_details": {"cache_read": 5}}) == 5
    assert cache_read_tokens({"input_token_details": {"flex_cache_read": 7, "cache_read": 3}}) == 10
    assert cache_read_tokens({"input_token_details": {"cache_creation": 9}}) == 0
    assert cache_read_tokens(None) == 0


def test_usage_is_split_by_role():
    tracker = RoleUsageTracker()
    for run_id in ("r1", "r2"):
        start(tracker, run_id, ["seq:step:2", "role:composer"])
        tracker.on_llm_end(llm_result(), run_id=run_id)
    start(tracker, "r3", ["role:critique"])
    tracker.on_llm_end(llm_result(model="gpt-4o-2024-08-06", tier="flex"), run_id="r3")

    roles = tracker.as_dict()["roles"]
    assert roles["composer"] == {"calls": 2, "input_tokens": 200, "output_tokens": 40, "cache_read_tokens": 80,
                                 "models_returned": {"gpt-4o-mini-2024-07-18": 2},
                                 "prompt_shas": {prompt_sha([SystemMessage(content="s"), HumanMessage(content="p")]): 2}}
    assert roles["critique"]["calls"] == 1
    assert roles["critique"]["cache_read_tokens"] == 40
    assert roles["critique"]["models_returned"] == {"gpt-4o-2024-08-06": 1}
    assert tracker.as_dict()["warnings"] == []


def test_two_role_tags_raise_rather_than_being_resolved():
    tracker = RoleUsageTracker()
    with pytest.raises(ValueError, match="more than one role tag"):
        start(tracker, "r1", ["role:composer", "role:retrieval_agent"])


def test_untagged_and_orphaned_ends_are_warned():
    tracker = RoleUsageTracker()
    start(tracker, "r1", ["seq:step:2"])           # a call site that forgot its role tag
    tracker.on_llm_end(llm_result(), run_id="r1")
    tracker.on_llm_end(llm_result(), run_id="r2")  # an end whose start the tracker never saw

    usage = tracker.as_dict()
    assert usage["roles"]["unattributed"]["calls"] == 2
    assert any("no role tag" in warning for warning in usage["warnings"])
    assert any("without on_chat_model_start" in warning for warning in usage["warnings"])


def test_failed_call_is_warned_and_leaves_no_pending_call():
    tracker = RoleUsageTracker()
    start(tracker, "r1", ["role:judge"])
    tracker.on_llm_error(RuntimeError("boom"), run_id="r1")
    tracker.on_llm_end(llm_result(), run_id="r1")  # the failed run never reaches on_llm_end

    assert tracker.as_dict()["roles"]["unattributed"]["calls"] == 1
    assert any("RuntimeError" in warning for warning in tracker.as_dict()["warnings"])


def test_peak_windows_follow_the_utc_clock():
    assert is_peak(datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc)) is True     # Monday 02:00 UTC
    assert is_peak(datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)) is True     # Monday 06:00 UTC
    assert is_peak(datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)) is False   # 10:00 is off-peak
    assert is_peak(datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc)) is False
    assert is_peak(datetime(2026, 10, 10, 2, 0, tzinfo=timezone.utc)) is False    # Saturday


def test_write_run_record_keeps_requested_and_returned_models_apart(tmp_path):
    tracker = RoleUsageTracker()
    start(tracker, "r1", ["role:judge"])
    tracker.on_llm_end(llm_result(model="deepseek-flash"), run_id="r1")
    configuration = {"judge": {"provider": "ChatDeepSeek", "model_requested": "deepseek-v4-pro",
                               "temperature": 0}}
    when = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)

    path = write_run_record({"id": "g01", "query": "q"}, tracker, configuration, prefix="test", out_dir=tmp_path, now=when)
    payload = json.loads(path.read_text())

    assert path.name == "test_2026-10-12_120000_g01.json"
    assert payload["id"] == "g01"
    assert payload["meta"]["recorded_at"] == "2026-10-12T12:00:00+00:00"
    assert payload["meta"]["peak"] is False
    assert payload["meta"]["configuration"]["judge"]["model_requested"] == "deepseek-v4-pro"
    assert payload["meta"]["usage"]["roles"]["judge"]["models_returned"] == {"deepseek-flash": 1}
