import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from ParallelProse import agent as ag
from ParallelProse.agent import (ComparisonCritique, ComposerAnswer, CorpusCritique, CorpusFinding,
                                 EFirst, EFirstBatch, EPostVerdict, ESecond, PerBookCritique)
from ParallelProse.catalog import CATALOG


def corpus_slot(label=None, chunks=None, lineage=None, reason=None, narrowed_query=None, silence_cause=None,
                P=None, retry_used=False):
    return {"chunks": chunks, "lineage": lineage or [], "label": label, "reason": reason,
            "narrowed_query": narrowed_query, "silence_cause": silence_cause, "P": P, "retry_used": retry_used}


def reflection_state(corpora, answer="", iteration=1, needs_revision=False):
    return {"query": "q", "answer": answer, "needs_revision": needs_revision, "feedback": "",
            "iteration": iteration, "corpora": corpora}


def composer_answer(a_finding, a_quote, b_finding, b_quote, agreement="agree", disagreement="disagree"):
    return ComposerAnswer(agreement=agreement, disagreement=disagreement, unique_findings=[
        CorpusFinding(corpus_id="A", claim_in_passage=a_finding, quote=a_quote),
        CorpusFinding(corpus_id="B", claim_in_passage=b_finding, quote=b_quote),
    ])


class FakeStructured:
    def __init__(self, result):
        self.result = result
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return self.result


class FakeLLM:
    def __init__(self, results):
        self.results = results
        self.calls = {}

    def with_structured_output(self, schema):
        self.calls[schema] = FakeStructured(self.results[schema])
        return self.calls[schema]


@pytest.mark.parametrize("a, b, expected", [
    ("ok", "ok", "__end__"),
    ("miss", "ok", "retriever"),
    ("miss", "silent", "retriever"),
    ("silent", "ok", "finalize"),
    ("silent", "silent", "finalize"),
])
def test_route_after_reflection(a, b, expected):
    state = reflection_state({"A": corpus_slot(a), "B": corpus_slot(b)})
    assert str(ag.route_after_reflection(state)) == expected


def test_route_stops_retrying_at_max_iterations_but_still_finalizes_silent():
    misses_only = reflection_state({"A": corpus_slot("miss"), "B": corpus_slot("ok")},
                                   iteration=ag.MAX_ITERATIONS)
    assert str(ag.route_after_reflection(misses_only)) == "__end__"
    miss_and_silent = reflection_state({"A": corpus_slot("miss"), "B": corpus_slot("silent")},
                                       iteration=ag.MAX_ITERATIONS)
    assert ag.route_after_reflection(miss_and_silent) == "finalize"


def test_route_after_e_first_retries_only_when_a_book_is_left_miss():
    assert ag.route_after_e_first({
        "corpora": {"A": corpus_slot("miss"), "B": corpus_slot("ok")}}) == "retry"
    assert ag.route_after_e_first({
        "corpora": {"A": corpus_slot("ok"), "B": corpus_slot("silent")}}) == "done"


def test_retriever_forwards_skipped_slots_unchanged(monkeypatch):
    monkeypatch.setattr(ag, "bridged_tools_by_corpus", {})
    monkeypatch.setattr(ag, "retrieval_agents_by_corpus", {})

    async def no_tools(client, corpus):
        return []

    class MustNotRetrieve:
        async def ainvoke(self, *args, **kwargs):
            raise AssertionError("a skipped book must not be retrieved again")

    monkeypatch.setattr(ag, "mcp_tools_as_langchain_tools", no_tools)
    monkeypatch.setattr(ag, "create_agent", lambda **kwargs: MustNotRetrieve())
    lineage = [{"iteration": 0, "tool": "call_parent_retriever", "args": {"query": "q"}, "forced_retriever": False}]
    state = reflection_state({
        "A": corpus_slot("ok", chunks=["a1"], lineage=lineage, reason="ra"),
        "B": corpus_slot("silent", chunks=["b1"], reason="rb"),
    })

    out = asyncio.run(ag.retriever(state))

    assert out["corpora"]["A"] == {"chunks": ["a1"], "lineage": lineage, "label": "ok", "reason": "ra",
                                   "narrowed_query": None, "silence_cause": None, "P": None, "retry_used": False}
    assert out["corpora"]["B"] == {"chunks": ["b1"], "lineage": [], "label": "silent", "reason": "rb",
                                   "narrowed_query": None, "silence_cause": None, "P": None, "retry_used": False}


def test_retriever_retries_a_miss_with_its_narrowed_query(monkeypatch):
    monkeypatch.setattr(ag, "bridged_tools_by_corpus", {})
    monkeypatch.setattr(ag, "retrieval_agents_by_corpus", {})

    async def no_tools(client, corpus):
        return []

    seen = []

    class RecordingAgent:
        async def ainvoke(self, payload):
            seen.append(payload["messages"][0].content)
            return {"messages": [
                AIMessage(content="", tool_calls=[{"id": "t1", "name": "call_parent_retriever",
                                                   "args": {"query": "narrow"}}]),
                ToolMessage(content=json.dumps(["passage"]), tool_call_id="t1", status="success"),
            ]}

    monkeypatch.setattr(ag, "mcp_tools_as_langchain_tools", no_tools)
    monkeypatch.setattr(ag, "create_agent", lambda **kwargs: RecordingAgent())
    state = reflection_state({
        "A": corpus_slot("miss", chunks=[], narrowed_query="narrow"),
        "B": corpus_slot("ok", chunks=["b1"]),
    })

    out = asyncio.run(ag.retriever(state))

    assert seen == ["narrow"]
    assert out["corpora"]["A"]["chunks"] == ["passage"]
    assert out["corpora"]["A"]["lineage"] == [{"iteration": 1, "tool": "call_parent_retriever",
                                               "args": {"query": "narrow"}, "forced_retriever": False}]


def test_composer_keeps_ok_finding_and_overrides_silent_book(monkeypatch):
    fake = FakeLLM({ComposerAnswer: composer_answer("A drifted", "other", "B fresh", "qb2")})
    monkeypatch.setattr(ag, "llm", fake)
    prior = composer_answer("A kept", "qa", "B old", "qb")
    state = reflection_state({"A": corpus_slot("ok", chunks=["a"]), "B": corpus_slot("silent", chunks=["b"])},
                             answer=prior, iteration=2)

    out = ag.composer(state)

    a, b = out["answer"].unique_findings
    assert (a.claim_in_passage, a.quote) == ("A kept", "qa")
    assert (b.claim_in_passage, b.quote) == ("query content is absent", None)
    assert out["answer"].agreement == (f"{CATALOG['B'].book_title} does not address the query, "
                                       "so there is no cross-book agreement.")
    assert out["answer"].disagreement == "None: only one book addresses the query."
    assert out["iteration"] == 3
    assert "Corpus_id: A = Finding: A kept" in fake.calls[ComposerAnswer].prompts[0]


def test_composer_with_both_books_silent(monkeypatch):
    fake = FakeLLM({ComposerAnswer: composer_answer("x", "x", "y", "y")})
    monkeypatch.setattr(ag, "llm", fake)
    state = reflection_state({"A": corpus_slot("silent", chunks=["a"]), "B": corpus_slot("silent", chunks=["b"])},
                             answer=composer_answer("p", "p", "q", "q"))

    out = ag.composer(state)

    assert out["answer"].agreement == "Neither book addresses the query."
    assert out["answer"].disagreement == "None."
    assert [f.claim_in_passage for f in out["answer"].unique_findings] == ["query content is absent"] * 2


def test_reflect_builds_the_e_record_and_keeps_a_retry_as_miss(monkeypatch):
    fake = FakeLLM({
        EFirstBatch: EFirstBatch(verdicts=[
            EFirst(corpus_id="A", p_adjacent="yes", p_answers="no", P="pa", retry="yes", narrowed_query="na"),
            EFirst(corpus_id="B", p_adjacent="yes", p_answers="yes", P="pb", retry="yes", narrowed_query="nb"),
        ]),
        ComparisonCritique: ComparisonCritique(needs_revision=True, feedback="fb"),
    })
    monkeypatch.setattr(ag, "llm", fake)
    monkeypatch.setattr(ag, "critique_llm", fake)
    state = reflection_state({"A": corpus_slot(chunks=["a"]), "B": corpus_slot(chunks=["b"])},
                             answer=composer_answer("fa", "qa", "fb", "qb"))

    out = ag.reflect(state)

    assert out["needs_revision"] is True and out["feedback"] == "fb"
    assert out["corpora"]["A"] == {"chunks": ["a"], "lineage": [], "label": "miss",
                                   "reason": "p_answers=no, p_adjacent=yes", "narrowed_query": "na",
                                   "silence_cause": None, "P": "pa", "retry_used": False}
    assert out["corpora"]["B"] == {"chunks": ["b"], "lineage": [], "label": "ok",
                                   "reason": "p_answers=yes, p_adjacent=yes", "narrowed_query": None,
                                   "silence_cause": None, "P": "pb", "retry_used": False}


def test_reflect_derives_silence_cause_and_retry_used_from_the_record_fields(monkeypatch):
    fake = FakeLLM({
        EFirstBatch: EFirstBatch(verdicts=[
            EFirst(corpus_id="A", p_adjacent="no", p_answers="no", P=None, retry="no"),
            EFirst(corpus_id="B", p_adjacent="yes", p_answers="no", P="pb", retry="no"),
        ]),
        ComparisonCritique: ComparisonCritique(needs_revision=False, feedback="fb"),
    })
    monkeypatch.setattr(ag, "llm", fake)
    monkeypatch.setattr(ag, "critique_llm", fake)
    state = reflection_state({"A": corpus_slot("miss", chunks=["a"]), "B": corpus_slot(chunks=["b"])},
                             answer=composer_answer("fa", "qa", "fb", "qb"))

    out = ag.reflect(state)

    assert (out["corpora"]["A"]["label"], out["corpora"]["A"]["silence_cause"],
            out["corpora"]["A"]["retry_used"]) == ("silent", "absence", True)
    assert (out["corpora"]["B"]["label"], out["corpora"]["B"]["silence_cause"],
            out["corpora"]["B"]["retry_used"]) == ("silent", "adjacent_topic", False)


def test_e_record_maps_ok_miss_and_silent():
    ok = EPostVerdict(corpus_id="A", p_adjacent="yes", p_answers="yes", P="p", retry="no", narrowed_query=None, ok="yes")
    miss = EPostVerdict(corpus_id="A", p_adjacent="yes", p_answers="no", P="p", retry="yes", narrowed_query="n", ok=None)
    silent = EPostVerdict(corpus_id="A", p_adjacent="no", p_answers="no", P=None, retry="no", narrowed_query=None, ok="no")

    assert ag.e_record(ok, False) == {"label": "ok", "silence_cause": None, "P": "p", "retry_used": False}
    assert ag.e_record(miss, False)["label"] == "miss"
    assert ag.e_record(silent, True) == {"label": "silent", "silence_cause": "absence", "P": None, "retry_used": True}


def test_e_first_field_order_is_the_bias_control():
    assert list(EFirst.model_fields) == ["corpus_id", "p_adjacent", "p_answers", "P", "retry", "narrowed_query"]


def test_e_second_is_e_first_minus_the_two_retry_fields():
    assert list(ESecond.model_fields) == ["corpus_id", "p_adjacent", "p_answers", "P"]


def test_e_judge_first_calls_critique_llm_with_evidence_only(monkeypatch):
    verdict = EFirstBatch(verdicts=[
        EFirst(corpus_id="A", p_adjacent="yes", p_answers="no", P="pa", retry="yes", narrowed_query="nq"),
        EFirst(corpus_id="B", p_adjacent="no", p_answers="no", P=None, retry="no", narrowed_query=None),
    ])
    fake = FakeLLM({EFirstBatch: verdict})
    monkeypatch.setattr(ag, "critique_llm", fake)
    lineage = [{"iteration": 0, "tool": "call_parent_retriever", "args": {"query": "qa"},
                "forced_retriever": False}]
    corpora = {"A": corpus_slot(chunks=["a passage"], lineage=lineage),
               "B": corpus_slot(chunks=["b passage"])}

    out = ag.e_judge_first("the query", corpora)

    assert out is verdict
    prompt = fake.calls[EFirstBatch].prompts[0]
    assert "a passage" in prompt and "b passage" in prompt
    assert "the query" in prompt and "qa" in prompt  # query + lineage, not just chunks
    assert "support" not in prompt


def test_e_judge_first_never_receives_the_composer_draft(monkeypatch):
    verdict = EFirstBatch(verdicts=[
        EFirst(corpus_id="A", p_adjacent="no", p_answers="no", retry="no"),
        EFirst(corpus_id="B", p_adjacent="no", p_answers="no", retry="no"),
    ])
    fake = FakeLLM({EFirstBatch: verdict})
    monkeypatch.setattr(ag, "critique_llm", fake)
    draft = "A_DRAFT_SENTENCE_THAT_MUST_NOT_LEAK"
    state = reflection_state({"A": corpus_slot(chunks=["a"]), "B": corpus_slot(chunks=["b"])},
                             answer=composer_answer(draft, "q", draft, "q"))

    ag.e_judge_first(state["query"], state["corpora"])

    assert draft not in fake.calls[EFirstBatch].prompts[0]


def test_postprocess_e_forces_retry_no_when_the_book_answers():
    verdict = EFirst(corpus_id="A", p_adjacent="yes", p_answers="yes", P="pa",
                     retry="yes", narrowed_query="nq")

    out = ag.postprocess_e(verdict)

    assert (out.retry, out.narrowed_query, out.ok) == ("no", None, "yes")
    assert (out.p_adjacent, out.p_answers, out.P) == ("yes", "yes", "pa")


def test_postprocess_e_keeps_a_retry_and_leaves_ok_undecided():
    verdict = EFirst(corpus_id="B", p_adjacent="yes", p_answers="no", P="pa",
                     retry="yes", narrowed_query="nq")

    out = ag.postprocess_e(verdict)

    assert (out.retry, out.narrowed_query, out.ok) == ("yes", "nq", None)


def test_postprocess_e_nulls_narrowed_query_when_retry_is_no():
    verdict = EFirst(corpus_id="B", p_adjacent="no", p_answers="no", P=None,
                     retry="no", narrowed_query="nq")

    out = ag.postprocess_e(verdict)

    assert (out.retry, out.narrowed_query, out.ok) == ("no", None, "no")


def test_postprocess_e_runs_on_e_second_which_has_no_retry_fields():
    answered = ag.postprocess_e(ESecond(corpus_id="A", p_adjacent="yes", p_answers="yes", P="pa"))
    silenced = ag.postprocess_e(ESecond(corpus_id="B", p_adjacent="yes", p_answers="no", P="pa"))

    assert (answered.retry, answered.narrowed_query, answered.ok) == ("no", None, "yes")
    assert (silenced.retry, silenced.narrowed_query, silenced.ok) == ("no", None, "no")


def test_postprocess_e_logs_the_rewrite_without_rejecting(capsys):
    verdict = EFirst(corpus_id="A", p_adjacent="yes", p_answers="yes", P="pa",
                     retry="yes", narrowed_query="nq")

    out = ag.postprocess_e(verdict)

    log = capsys.readouterr().out
    assert "rewrote" in log and "book A" in log
    assert out.retry == "no"


def test_e_first_builds_the_record_and_returns_every_slot(monkeypatch):
    fake = FakeLLM({EFirstBatch: EFirstBatch(verdicts=[
        EFirst(corpus_id="A", p_adjacent="yes", p_answers="no", P="pa", retry="yes", narrowed_query="na"),
        EFirst(corpus_id="B", p_adjacent="no", p_answers="no", P=None, retry="no", narrowed_query=None),
    ])})
    monkeypatch.setattr(ag, "critique_llm", fake)
    state = reflection_state({"A": corpus_slot(chunks=["a"]), "B": corpus_slot(chunks=["b"])})

    out = ag.e_first(state)

    assert set(out["corpora"]) == {"A", "B"}  # the state invariant: no slot omitted
    assert out["corpora"]["A"] == {"chunks": ["a"], "lineage": [], "label": "miss",
                                   "reason": "p_answers=no, p_adjacent=yes", "narrowed_query": "na",
                                   "silence_cause": None, "P": "pa", "retry_used": False}
    assert out["corpora"]["B"] == {"chunks": ["b"], "lineage": [], "label": "silent",
                                   "reason": "p_answers=no, p_adjacent=no", "narrowed_query": None,
                                   "silence_cause": "absence", "P": None, "retry_used": False}
    assert "support" not in fake.calls[EFirstBatch].prompts[0]
