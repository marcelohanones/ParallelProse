import asyncio

import pytest

from ParallelProse import theme_batches as tb
from ParallelProse.agent import ComposerAnswer, CorpusFinding
from ParallelProse.evaluation import GoldenEntry, OkExpectation, anchor_hits, label_agreement, run_golden_entry

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
