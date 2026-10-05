import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from ParallelProse import agent as ag
from ParallelProse.agent import ComparisonCritique, ComposerAnswer, CorpusCritique, CorpusFinding, PerBookCritique
from ParallelProse.catalog import CATALOG


def corpus_slot(label=None, chunks=None, lineage=None, reason=None, narrowed_query=None):
    return {"chunks": chunks, "lineage": lineage or [], "label": label, "reason": reason,
            "narrowed_query": narrowed_query}


def reflection_state(corpora, answer="", iteration=1, needs_revision=False):
    return {"query": "q", "answer": answer, "needs_revision": needs_revision, "feedback": "",
            "iteration": iteration, "corpora": corpora}


def composer_answer(a_finding, a_quote, b_finding, b_quote, agreement="agree", disagreement="disagree"):
    return ComposerAnswer(agreement=agreement, disagreement=disagreement, unique_findings=[
        CorpusFinding(corpus_id="A", finding=a_finding, quote=a_quote),
        CorpusFinding(corpus_id="B", finding=b_finding, quote=b_quote),
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
                                   "narrowed_query": None}
    assert out["corpora"]["B"] == {"chunks": ["b1"], "lineage": [], "label": "silent", "reason": "rb",
                                   "narrowed_query": None}


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
    assert (a.finding, a.quote) == ("A kept", "qa")
    assert (b.finding, b.quote) == ("query content is absent", None)
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
    assert [f.finding for f in out["answer"].unique_findings] == ["query content is absent"] * 2


def test_reflect_returns_every_book_with_narrowed_query_only_on_miss(monkeypatch):
    fake = FakeLLM({
        PerBookCritique: PerBookCritique(corpora_critique=[
            CorpusCritique(corpus_id="A", label="miss", reason="ra", narrowed_query="na"),
            CorpusCritique(corpus_id="B", label="ok", reason="rb", narrowed_query="nb"),
        ]),
        ComparisonCritique: ComparisonCritique(needs_revision=True, feedback="fb"),
    })
    monkeypatch.setattr(ag, "llm", fake)
    state = reflection_state({"A": corpus_slot(chunks=["a"]), "B": corpus_slot(chunks=["b"])},
                             answer=composer_answer("fa", "qa", "fb", "qb"))

    out = ag.reflect(state)

    assert out["needs_revision"] is True
    assert out["feedback"] == "fb"
    assert out["corpora"]["A"] == {"chunks": ["a"], "lineage": [], "label": "miss", "reason": "ra",
                                   "narrowed_query": "na"}
    assert out["corpora"]["B"] == {"chunks": ["b"], "lineage": [], "label": "ok", "reason": "rb",
                                   "narrowed_query": None}
