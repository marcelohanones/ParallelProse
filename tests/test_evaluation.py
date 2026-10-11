import asyncio
import inspect
import json

import pytest

from ParallelProse import theme_batches as tb
from ParallelProse.agent import ComposerAnswer, CorpusFinding
from ParallelProse import evaluation as ev
from ParallelProse.evaluation import (EVALUATORS, JUDGES, GoldenEntry, OkExpectation, anchor_hits,
                                      anchors_evaluator, golden_target, label_agreement, labels_evaluator,
                                      push_golden_set, run_experiment, run_golden_entry)

BITE_EXTRA_KEYS = {"quote_selection", "side_is_target", "verified", "verification", "retrieval"}


def fake_result():
    answer = ComposerAnswer(agreement="both", disagreement="none", unique_findings=[
        CorpusFinding(corpus_id="A", finding="a", quote="qa"),
        CorpusFinding(corpus_id="B", finding="query content is absent", quote=None),
    ])
    corpora = {
        "A": {"chunks": ["some text qa more text"], "label": "ok", "reason": "fine", "lineage": []},
        "B": {"chunks": None, "label": "silent", "reason": "absent", "lineage": []},
    }
    return {"answer": answer, "corpora": corpora}


def entry():
    return GoldenEntry(
        id="g01", theme="t", query="What keeps people sunk in sleep?", side="A", specificity="abstract",
        wording="book", known_failure=False, note="n",
        expected={"A": {"label": "ok", "anchors": ["held down pleasantly as in sleep"], "min_hits": 1},
                  "B": {"label": "silent", "near_miss": False, "absent_terms": ["television", "telephone"]}})


def stub_run_query(monkeypatch, queries_run):
    async def fake_run_query(query):
        queries_run.append(query)
        return fake_result()

    monkeypatch.setattr(tb, "run_query", fake_run_query)


def test_answer_query_returns_the_bite_extras_and_the_corpora(monkeypatch):
    stub_run_query(monkeypatch, [])

    answer, extra, corpora = asyncio.run(tb.answer_query("a query", "A"))

    assert set(extra) == BITE_EXTRA_KEYS
    assert extra["side_is_target"] == {"A": True, "B": False}
    assert corpora["A"]["chunks"] == ["some text qa more text"]


def test_golden_record_is_a_bite_plus_id_and_each_books_chunks(monkeypatch):
    queries_run = []
    stub_run_query(monkeypatch, queries_run)

    record = asyncio.run(run_golden_entry(entry()))

    assert queries_run == ["What keeps people sunk in sleep?"]
    assert set(record) == {"id", "query", "answer"} | BITE_EXTRA_KEYS | {"chunks"}
    assert record["id"] == "g01"
    assert record["retrieval"]["B"]["label"] == "silent"
    assert record["chunks"] == {"A": ["some text qa more text"], "B": []}


ANCHOR = "held down pleasantly as in sleep"
SCATTERED = ["the first passage of the answer", "a second passage further on", "a third passage near the end"]


def scored(chunks_a, anchors=(ANCHOR,), min_hits=1):
    expected = {"A": OkExpectation(label="ok", anchors=list(anchors), min_hits=min_hits), "B": entry().expected["B"]}
    return anchor_hits({"chunks": {"A": chunks_a, "B": []}}, entry().model_copy(update={"expected": expected}))


def test_anchor_in_one_chunk_passes_and_silent_books_are_left_out():
    result = scored(["Thus I was Held down\npleasantly as in sleep by the world."])

    assert result == {"A": {"found": 1, "needed": 1, "passed": True, "missing": []}}


def test_anchor_split_across_two_chunks_is_missing():
    result = scored(["the baggage of this world held down", "pleasantly as in sleep and I could not wake"])

    assert result["A"]["passed"] is False
    assert result["A"]["missing"] == [ANCHOR]


def test_scattered_answer_below_min_hits_fails_and_names_what_was_missed():
    result = scored(["here is the first passage of the answer, retrieved"], anchors=SCATTERED, min_hits=2)

    assert result["A"] == {"found": 1, "needed": 2, "passed": False, "missing": SCATTERED[1:]}


def test_ok_book_with_no_chunks_misses_every_anchor():
    result = scored([], anchors=SCATTERED, min_hits=2)

    assert result["A"]["found"] == 0 and result["A"]["missing"] == SCATTERED


@pytest.mark.parametrize("expected, final, agree", [
    ("ok", "ok", True), ("ok", "miss", False), ("ok", "silent", False),
    ("silent", "ok", False), ("silent", "miss", False), ("silent", "silent", True),
])
def test_label_agreement_is_an_exact_match_and_miss_never_agrees(expected, final, agree):
    expectation = (OkExpectation(label="ok", anchors=[ANCHOR], min_hits=1) if expected == "ok"
                   else entry().expected["B"])
    golden = entry().model_copy(update={"expected": {"A": expectation, "B": entry().expected["B"]}})
    record = {"retrieval": {"A": {"label": final}, "B": {"label": "silent"}}}

    result = label_agreement(record, golden)

    assert result["A"] == {"expected": expected, "final": final, "agree": agree}
    assert result["B"]["agree"] is True


class FakeClient:
    """Records what push_golden_set asked for; no network."""

    def __init__(self, existing=None):
        self.existing = existing or {}        # dataset name -> number of stored examples
        self.created, self.pushed = [], []

    def has_dataset(self, dataset_name):
        return dataset_name in self.existing

    def list_examples(self, dataset_name):
        return [{"n": i} for i in range(self.existing[dataset_name])]

    def create_dataset(self, name, description=""):
        self.created.append(name)
        self.existing[name] = 0
        return type("Dataset", (), {"id": f"id-{name}"})()

    def create_examples(self, dataset_id, examples):
        self.pushed.append((dataset_id, examples))
        return examples


def two_entries():
    second = entry().model_copy(update={"id": "g02", "theme": "other", "query": "Why does praise bind a man?"})
    return [entry(), second]


def test_first_push_creates_the_dataset_and_splits_each_entry_by_its_reader():
    client = FakeClient()

    name = push_golden_set(two_entries(), client=client)

    assert name.startswith("golden-augustine_debord-") and client.created == [name]
    dataset_id, examples = client.pushed[0]
    assert dataset_id == f"id-{name}" and len(examples) == 2
    assert examples[0]["inputs"] == {"id": "g01", "query": "What keeps people sunk in sleep?", "side": "A"}
    assert examples[0]["outputs"]["expected"]["A"]["anchors"] == ["held down pleasantly as in sleep"]
    assert set(examples[0]["metadata"]) == {"theme", "specificity", "wording", "known_failure", "note"}


def test_pushing_the_same_entries_again_reuses_the_dataset_without_writing_examples():
    client = FakeClient()
    name = push_golden_set(two_entries(), client=client)
    client.existing[name] = 2

    assert push_golden_set(two_entries(), client=client) == name
    assert len(client.pushed) == 1


def test_editing_an_anchor_gives_the_entries_a_new_dataset_name():
    client = FakeClient()
    edited = two_entries()
    edited[0] = edited[0].model_copy(update={"expected": {
        "A": OkExpectation(label="ok", anchors=["held down pleasantly as in sleepe"], min_hits=1),
        "B": edited[0].expected["B"]}})

    assert push_golden_set(edited, client=client) != push_golden_set(two_entries(), client=client)


def test_a_dataset_left_with_too_few_examples_is_rejected_not_reused():
    client = FakeClient()
    name = push_golden_set(two_entries(), client=client)
    client.existing[name] = 1                 # create_examples failed partway

    with pytest.raises(ValueError, match="holds 1 examples, expected 2"):
        push_golden_set(two_entries(), client=client)


class FakeExample:
    """One LangSmith example: the three parts push_golden_set writes, plus the metadata key LangSmith adds."""

    def __init__(self, pushed):
        self.inputs, self.outputs = pushed["inputs"], pushed["outputs"]
        self.metadata = {**pushed["metadata"], "dataset_split": ["base"]}


def pushed_example(index=0):
    client = FakeClient()
    push_golden_set(two_entries(), client=client)
    return FakeExample(client.pushed[0][1][index])


def record_for(chunks_a, label_a="ok", label_b="silent"):
    return {"id": "g01", "query": "q",
            "retrieval": {"A": {"label": label_a}, "B": {"label": label_b}},
            "chunks": {"A": chunks_a, "B": []}}


def test_an_example_rebuilds_the_entry_it_was_split_from():
    assert ev._entry_from(pushed_example()) == two_entries()[0]


def test_the_target_runs_only_the_query_and_side_the_example_carries(monkeypatch):
    stub_run_query(monkeypatch, [])

    record = asyncio.run(golden_target(pushed_example().inputs))

    assert record["id"] == "g01" and record["query"] == "What keeps people sunk in sleep?"
    assert set(record) == {"id", "query", "answer"} | BITE_EXTRA_KEYS | {"chunks"}


def test_each_book_gets_its_own_key_and_a_silent_book_has_no_anchor_key():
    example = pushed_example()
    hit = record_for(["Thus I was held down pleasantly as in sleep."])

    anchors = anchors_evaluator(outputs=hit, example=example)
    labels = labels_evaluator(outputs=hit, example=example)

    assert [r["key"] for r in anchors["results"]] == ["anchor_hits_A"]      # B is expected silent
    assert anchors["results"][0]["score"] == 1
    assert [(r["key"], r["score"]) for r in labels["results"]] == [("label_agreement_A", 1), ("label_agreement_B", 1)]


def test_a_missed_anchor_scores_zero_and_keeps_the_detail_in_its_comment():
    anchors = anchors_evaluator(outputs=record_for(["nothing of the sort"]), example=pushed_example())

    result = anchors["results"][0]
    assert result["score"] == 0
    assert json.loads(result["comment"])["missing"] == ["held down pleasantly as in sleep"]


def test_every_adapter_has_argument_names_langsmith_accepts():
    for evaluator in EVALUATORS + JUDGES:
        assert set(inspect.signature(evaluator).parameters) <= {"run", "example", "inputs", "outputs",
                                                                "reference_outputs", "attachments"}


def fake_aevaluate(monkeypatch):
    """Captures what run_experiment would send LangSmith; no network, no runs."""
    calls = {}

    async def aevaluate(target, **kwargs):
        calls.update(target=target, **kwargs)
        return type("Results", (), {"experiment_name": "pp-test-1"})()

    monkeypatch.setattr(ev, "aevaluate", aevaluate)
    monkeypatch.setattr(ev, "push_golden_set", lambda entries: "golden-test-abcd1234")
    monkeypatch.setattr(ev, "configuration", lambda: {"child_chunk_size_A": 400, "system_model": "gpt-4o-mini"})
    return calls


def test_an_experiment_records_the_live_configuration_and_runs_only_the_free_evaluators(monkeypatch):
    calls = fake_aevaluate(monkeypatch)

    assert asyncio.run(run_experiment(two_entries())) == "pp-test-1"
    assert calls["target"] is golden_target and calls["data"] == "golden-test-abcd1234"
    assert calls["evaluators"] == EVALUATORS
    assert calls["metadata"] == {"child_chunk_size_A": 400, "system_model": "gpt-4o-mini",
                                 "judges": False, "golden_set": "golden-test-abcd1234", "repetitions": 3}
    assert calls["num_repetitions"] == 3 and calls["max_concurrency"] == 2


def test_asking_for_judges_adds_them_and_says_so_in_the_metadata(monkeypatch):
    calls = fake_aevaluate(monkeypatch)

    asyncio.run(run_experiment(two_entries(), judges=True, repetitions=1, concurrency=1))

    assert calls["evaluators"] == EVALUATORS + JUDGES
    assert calls["metadata"]["judges"] is True and calls["metadata"]["repetitions"] == 1
    assert calls["num_repetitions"] == 1 and calls["max_concurrency"] == 1


def test_the_configuration_is_read_from_the_live_retrieval_objects():
    from ParallelProse.mcp_tools import REGISTRY

    config = ev.configuration()

    assert config["child_chunk_size_A"] == REGISTRY["A"].child_config.chunk_size
    assert config["parent_chunk_size_B"] == REGISTRY["B"].parent_config.chunk_size
    assert config["system_model"] == "gpt-4o-mini" and config["judge_model"] == "gpt-4o"
