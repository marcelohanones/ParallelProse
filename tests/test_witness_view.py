import json

from ParallelProse.witness_view import build_witness_view


def bite(code, query, findings, retrieval, side_is_target, verification, quote_selection, bite_id):
    return {
        "code": code, "query": query,
        "answer": {"agreement": "should never appear", "disagreement": "should never appear",
                  "unique_findings": findings},
        "bite_id": bite_id, "retrieval": retrieval, "side_is_target": side_is_target,
        "verification": verification, "quote_selection": quote_selection,
    }


def write_session(tmp_path, bites):
    session = tmp_path / "2026-01-01_0000"
    session.mkdir()
    (session / "manifest.json").write_text(json.dumps({"project": "augustine_debord"}))
    consolidated = session / "2026-01-01_0000_thesis.json"
    consolidated.write_text(json.dumps({
        "session": "2026-01-01_0000",
        "books": {"A": {"title": "Book A", "translator": "T.A."}, "B": {"title": "Book B", "translator": "T.B."}},
        "theses": [{"theme": "Theme", "thesis": "Thesis", "bites": bites}],
    }))
    return consolidated


def test_one_record_per_book_per_query(tmp_path, monkeypatch):
    monkeypatch.setattr("ParallelProse.witness_view.context_window", lambda book, quote: None)
    consolidated = write_session(tmp_path, [
        bite("1.1a", "q1",
             [{"corpus_id": "A", "claim_in_passage": "fa", "quote": "qa"},
              {"corpus_id": "B", "claim_in_passage": "fb", "quote": "qb"}],
             {"A": {"label": "ok", "lineage": [], "silence_cause": None},
              "B": {"label": "ok", "lineage": [], "silence_cause": None}},
             {"A": None, "B": None},
             {"A": {"status": "verbatim"}, "B": {"status": "verbatim"}},
             {"A": {"replaced": False}, "B": {"replaced": False}},
             {"A": "idA", "B": "idB"}),
    ])

    out = build_witness_view(consolidated)
    witness = json.loads(out.read_text())

    assert out.name == "witness_view_augustine_debord_2026-01-01_0000.json"
    assert len(witness["records"]) == 2
    assert {r["corpus_id"] for r in witness["records"]} == {"A", "B"}


def test_comparison_fields_never_appear_in_the_output(tmp_path, monkeypatch):
    monkeypatch.setattr("ParallelProse.witness_view.context_window", lambda book, quote: None)
    consolidated = write_session(tmp_path, [
        bite("1.1a", "q1",
             [{"corpus_id": "A", "claim_in_passage": "fa", "quote": "qa"}],
             {"A": {"label": "ok", "lineage": [], "silence_cause": None}}, {"A": None},
             {"A": {"status": "verbatim"}}, {"A": {"replaced": False}}, {"A": "idA"}),
    ])

    witness_text = build_witness_view(consolidated).read_text()

    for forbidden in ("agreement", "disagreement", "needs_revision", "should never appear"):
        assert forbidden not in witness_text


def test_a_silent_book_carries_no_quote_but_still_gets_a_record(tmp_path, monkeypatch):
    monkeypatch.setattr("ParallelProse.witness_view.context_window", lambda book, quote: None)
    consolidated = write_session(tmp_path, [
        bite("1.1a", "q1",
             [{"corpus_id": "A", "claim_in_passage": "query content is absent", "quote": None}],
             {"A": {"label": "silent", "lineage": [], "silence_cause": "absence"}}, {"A": None},
             {"A": {"status": "no_quote"}}, {"A": {"replaced": False}}, {"A": "idA"}),
    ])

    record = json.loads(build_witness_view(consolidated).read_text())["records"][0]

    assert record["quote"] is None
    assert record["context_window"] is None
    assert record["finding"] == "query content is absent"
    assert record["retrieval"]["silence_cause"] == "absence"


def test_field_order_puts_quote_before_finding(tmp_path, monkeypatch):
    monkeypatch.setattr("ParallelProse.witness_view.context_window", lambda book, quote: None)
    consolidated = write_session(tmp_path, [
        bite("1.1a", "q1",
             [{"corpus_id": "A", "claim_in_passage": "fa", "quote": "qa"}],
             {"A": {"label": "ok", "lineage": [], "silence_cause": None}}, {"A": None},
             {"A": {"status": "verbatim"}}, {"A": {"replaced": False}}, {"A": "idA"}),
    ])

    record = json.loads(build_witness_view(consolidated).read_text())["records"][0]
    keys = list(record)

    assert keys.index("quote") < keys.index("finding")


def test_edition_and_query_code_travel_through(tmp_path, monkeypatch):
    monkeypatch.setattr("ParallelProse.witness_view.context_window", lambda book, quote: None)
    consolidated = write_session(tmp_path, [
        bite("2.3b", "a precise query",
             [{"corpus_id": "A", "claim_in_passage": "fa", "quote": "qa"}],
             {"A": {"label": "ok", "lineage": [{"tool": "x"}], "silence_cause": None}}, {"A": True},
             {"A": {"status": "verbatim"}}, {"A": {"replaced": False}}, {"A": "idA"}),
    ])

    record = json.loads(build_witness_view(consolidated).read_text())["records"][0]

    assert record["query_code"] == "2.3b" and record["query"] == "a precise query"
    assert record["edition"] == {"title": "Book A", "translator": "T.A."}
    assert record["retrieval"] == {"label": "ok", "side_is_target": True, "lineage": [{"tool": "x"}],
                                   "silence_cause": None}
    assert record["bite_id"] == "idA"
