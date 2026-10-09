import asyncio

from ParallelProse import theme_batches as tb
from ParallelProse.agent import ComposerAnswer, CorpusFinding
from ParallelProse.evaluation import GoldenEntry, run_golden_entry

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
