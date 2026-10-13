import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from ParallelProse import agent as ag
from ParallelProse.agent import (ComparisonCritique, ComposerAnswer, ComposerDraft, CorpusFinding,
                                 DraftFinding, EFirst, EFirstBatch, EPostVerdict, ESecond, ESecondBatch,
                                 SentenceChoice, SentenceClaim)
from ParallelProse.catalog import CATALOG


def corpus_slot(label=None, chunks=None, lineage=None, reason=None, narrowed_query=None, silence_cause=None,
                P=None, retry_used=False):
    return {"chunks": chunks, "lineage": lineage or [], "label": label, "reason": reason,
            "narrowed_query": narrowed_query, "silence_cause": silence_cause, "P": P, "retry_used": retry_used}


def reflection_state(corpora, answer="", iteration=1, needs_revision=False):
    return {"query": "q", "answer": answer, "needs_revision": needs_revision, "feedback": "",
            "iteration": iteration, "corpora": corpora}


def composer_answer(a_headline, a_sentence, b_headline, b_sentence, agreement="agree", disagreement="disagree"):
    return ComposerAnswer(agreement=agreement, disagreement=disagreement, unique_findings=[
        CorpusFinding(corpus_id="A", headline=a_headline,
                      pairs=[SentenceClaim(claim=a_headline, sentence=a_sentence)]),
        CorpusFinding(corpus_id="B", headline=b_headline,
                      pairs=[SentenceClaim(claim=b_headline, sentence=b_sentence)]),
    ])


def composer_draft(a_headline, a_claim, b_headline, b_claim, agreement="agree", disagreement="disagree"):
    """The composer's draft: the headlines and the atomic claims — the sentences arrive from the picker."""
    return ComposerDraft(agreement=agreement, disagreement=disagreement, unique_findings=[
        DraftFinding(corpus_id="A", headline=a_headline, claims=[a_claim]),
        DraftFinding(corpus_id="B", headline=b_headline, claims=[b_claim]),
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


def test_composer_builds_findings_for_ok_books_only(monkeypatch):
    fake = FakeLLM({ComposerDraft: composer_draft("A fresh", "a claim", "B ghost", "b claim")})
    monkeypatch.setattr(ag, "llm", fake)
    picker = FakeLLM({SentenceChoice: SentenceChoice(sentence_index=1)})
    monkeypatch.setattr(ag, "critique_llm", picker)
    state = reflection_state({"A": corpus_slot("ok", chunks=["Only one sentence here."]),
                              "B": corpus_slot("silent", chunks=["b"])})

    out = ag.composer(state)

    assert [slot.corpus_id for slot in out["answer"].unique_findings] == ["A"]
    assert out["answer"].unique_findings[0].pairs[0].sentence == "Only one sentence here."
    assert out["answer"].agreement == (f"{CATALOG['B'].book_title} does not address the query, "
                                       "so there is no cross-book agreement.")
    assert out["answer"].disagreement == "None: only one book addresses the query."
    assert out["iteration"] == state["iteration"] + 1


def test_composer_skips_the_llm_when_no_book_answers(monkeypatch):
    class MustNotCompose:
        def with_structured_output(self, schema):
            raise AssertionError("no ok book means no composition")

    monkeypatch.setattr(ag, "llm", MustNotCompose())
    state = reflection_state({"A": corpus_slot("silent", chunks=["a"]), "B": corpus_slot("silent", chunks=["b"])})

    out = ag.composer(state)

    assert out["answer"].agreement == "Neither book addresses the query."
    assert out["answer"].disagreement == "None."
    assert out["answer"].unique_findings == []


def test_reflect_short_circuits_when_fewer_than_two_books_answer(monkeypatch):
    class MustNotCompare:
        def with_structured_output(self, schema):
            raise AssertionError("fewer than two ok books means no comparison")

    monkeypatch.setattr(ag, "llm", MustNotCompare())
    state = reflection_state({"A": corpus_slot("ok"), "B": corpus_slot("silent")},
                             answer=composer_answer("fa", "qa", "fb", "qb"))

    out = ag.reflect(state)

    assert out["needs_revision"] is False
    assert "fewer than two" in out["feedback"]


def test_reflect_judges_the_comparison_when_both_books_answer(monkeypatch):
    fake = FakeLLM({ComparisonCritique: ComparisonCritique(needs_revision=True, feedback="fb")})
    monkeypatch.setattr(ag, "llm", fake)
    state = reflection_state({"A": corpus_slot("ok"), "B": corpus_slot("ok")},
                             answer=composer_answer("fa", "qa", "fb", "qb"))

    out = ag.reflect(state)

    assert out == {"needs_revision": True, "feedback": "fb"}
    assert "Agreement: agree" in fake.calls[ComparisonCritique].prompts[0]


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


def test_e_second_decides_ok_silent_and_marks_retry_used(monkeypatch):
    fake = FakeLLM({ESecondBatch: ESecondBatch(verdicts=[
        ESecond(corpus_id="A", p_adjacent="yes", p_answers="yes", P="pa"),
        ESecond(corpus_id="B", p_adjacent="no", p_answers="no", P=None),
    ])})
    monkeypatch.setattr(ag, "critique_llm", fake)
    state = reflection_state({"A": corpus_slot("miss", chunks=["a"]), "B": corpus_slot("ok", chunks=["b"])})

    out = ag.e_second(state)

    assert out["corpora"]["A"]["label"] == "ok" and out["corpora"]["A"]["retry_used"] is True
    assert out["corpora"]["B"]["label"] == "silent" and out["corpora"]["B"]["retry_used"] is False


def test_graph_places_e_before_composer_with_a_single_retry_branch():
    edges = {(edge.source, edge.target, edge.data) for edge in ag.reflection_app.get_graph().edges}
    assert ("retriever", "e_first", None) in edges
    assert ("e_first", "retry_retriever", "retry") in edges
    assert ("e_first", "composer", "done") in edges
    assert ("retry_retriever", "e_second", None) in edges
    assert ("e_second", "composer", None) in edges
    assert ("composer", "reflect", None) in edges
    assert ("reflect", "__end__", None) in edges
    assert not any("finalize" in (source, target) for source, target, _ in edges)


def test_select_sentences_gives_one_sentence_to_one_claim(monkeypatch):
    """A picker that answers the same sentence twice grounds one claim with it and leaves the other unpaired:
    three claims resting on one sentence are not three grounded steps."""
    answers = iter([SentenceChoice(sentence_index=1), SentenceChoice(sentence_index=1)])
    monkeypatch.setattr(ag, "critique_llm", FakeLLM({SentenceChoice: next(answers)}))
    draft = ComposerDraft(agreement="a", disagreement="d", unique_findings=[
        DraftFinding(corpus_id="A", headline="h", claims=["first claim", "second claim"])])
    corpora = {"A": {"chunks": ["Only one sentence here."]}}

    answer = ag.select_sentences(draft, corpora)

    finding = answer.unique_findings[0]
    assert [p.claim for p in finding.pairs] == ["first claim"]
    assert finding.pairs[0].sentence == "Only one sentence here."
    assert finding.unpaired == ["second claim"]


def test_select_sentences_keeps_a_claim_no_sentence_states(monkeypatch):
    monkeypatch.setattr(ag, "critique_llm", FakeLLM({SentenceChoice: SentenceChoice(sentence_index=None)}))
    draft = ComposerDraft(agreement="a", disagreement="d", unique_findings=[
        DraftFinding(corpus_id="A", headline="h", claims=["a claim nothing states"])])
    corpora = {"A": {"chunks": ["An unrelated sentence."]}}

    finding = ag.select_sentences(draft, corpora).unique_findings[0]

    assert finding.pairs == [] and finding.unpaired == ["a claim nothing states"]


def test_e_first_retries_a_batch_that_omits_a_book(monkeypatch):
    """A structured-output batch occasionally comes back one book short; the missing book is asked for again
    rather than deleting its slot (the state invariant: returning corpora replaces the whole dict)."""
    calls = []
    a_only = EFirstBatch(verdicts=[EFirst(corpus_id="A", p_adjacent="no", p_answers="no", retry="no")])
    b_only = EFirstBatch(verdicts=[EFirst(corpus_id="B", p_adjacent="no", p_answers="no", retry="no")])

    def judge(query, corpora):
        calls.append(query)
        return a_only if len(calls) == 1 else b_only

    monkeypatch.setattr(ag, "e_judge_first", judge)
    state = reflection_state({"A": corpus_slot(None), "B": corpus_slot(None)})

    out = ag.e_first(state)

    assert len(calls) == 2
    assert set(out["corpora"]) == {"A", "B"}
    assert out["corpora"]["B"]["label"] == "silent"


def test_e_first_names_a_book_its_batch_never_returns(monkeypatch):
    """A book still absent after the retry fails loudly, naming it — never a bare KeyError, never a dropped slot."""
    monkeypatch.setattr(ag, "e_judge_first", lambda query, corpora: EFirstBatch(
        verdicts=[EFirst(corpus_id="A", p_adjacent="no", p_answers="no", retry="no")]))
    state = reflection_state({"A": corpus_slot(None), "B": corpus_slot(None)})

    with pytest.raises(ValueError, match="B"):
        ag.e_first(state)
