import json

from ParallelProse.witness_view import build_witness_view


def pair(claim, sentence):
    return {"claim": claim, "sentence": sentence}


def bite(code, query, findings, retrieval, side_is_target, verification, bite_id):
    return {
        "code": code, "query": query,
        "answer": {"agreement": "should never appear", "disagreement": "should never appear",
                  "unique_findings": findings},
        "bite_id": bite_id, "retrieval": retrieval, "side_is_target": side_is_target,
        "verification": verification,
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


RECORD_KEYS = {"bite_id", "session", "query_code", "query", "corpus_id", "edition",
               "retrieval", "sentence", "verification", "passage", "claim"}


def test_one_record_per_pair_per_book_per_query(tmp_path, monkeypatch):
    monkeypatch.setattr("ParallelProse.witness_view.book_passage", lambda book, sentence: None)
    consolidated = write_session(tmp_path, [
        bite("1.1a", "q1",
             [{"corpus_id": "A", "headline": "ha", "pairs": [pair("ca", "qa")]},
              {"corpus_id": "B", "headline": "hb", "pairs": [pair("cb", "qb")]}],
             {"A": {"label": "ok", "lineage": [], "silence_cause": None},
              "B": {"label": "ok", "lineage": [], "silence_cause": None}},
             {"A": None, "B": None},
             {"A": [{"status": "verbatim"}], "B": [{"status": "verbatim"}]},
             {"A": ["idA"], "B": ["idB"]}),
    ])

    out = build_witness_view(consolidated)
    witness = json.loads(out.read_text())

    assert out.name == "witness_view_augustine_debord_2026-01-01_0000.json"
    assert len(witness["records"]) == 2
    assert {r["corpus_id"] for r in witness["records"]} == {"A", "B"}
    assert [r["claim"] for r in witness["records"]] == ["ca", "cb"]


def test_two_pairs_under_one_book_become_two_records(tmp_path, monkeypatch):
    monkeypatch.setattr("ParallelProse.witness_view.book_passage", lambda book, sentence: None)
    consolidated = write_session(tmp_path, [
        bite("1.1a", "q1",
             [{"corpus_id": "A", "headline": "ha", "pairs": [pair("ca1", "qa1"), pair("ca2", "qa2")]}],
             {"A": {"label": "ok", "lineage": [], "silence_cause": None}},
             {"A": None},
             {"A": [{"status": "verbatim"}, {"status": "not_found"}]},
             {"A": ["idA1", "idA2"]}),
    ])

    records = json.loads(build_witness_view(consolidated).read_text())["records"]

    assert [r["claim"] for r in records] == ["ca1", "ca2"]
    assert [r["sentence"] for r in records] == ["qa1", "qa2"]
    assert [r["bite_id"] for r in records] == ["idA1", "idA2"]
    assert [r["verification"] for r in records] == [{"status": "verbatim"}, {"status": "not_found"}]


def test_comparison_fields_never_appear_in_the_output(tmp_path, monkeypatch):
    monkeypatch.setattr("ParallelProse.witness_view.book_passage", lambda book, sentence: None)
    consolidated = write_session(tmp_path, [
        bite("1.1a", "q1",
             [{"corpus_id": "A", "headline": "ha", "pairs": [pair("ca", "qa")]}],
             {"A": {"label": "ok", "lineage": [], "silence_cause": None}}, {"A": None},
             {"A": [{"status": "verbatim"}]}, {"A": ["idA"]}),
    ])

    witness_text = build_witness_view(consolidated).read_text()

    for forbidden in ("agreement", "disagreement", "needs_revision", "should never appear"):
        assert forbidden not in witness_text


def test_a_silent_book_carries_P_and_still_gets_a_record(tmp_path, monkeypatch):
    monkeypatch.setattr("ParallelProse.witness_view.book_passage", lambda book, sentence: None)
    consolidated = write_session(tmp_path, [
        bite("1.1a", "q1",
             [{"corpus_id": "A", "headline": "query content is absent", "pairs": []}],
             {"A": {"label": "silent", "lineage": [], "silence_cause": "adjacent_topic",
                    "P": "the adjacent proposition"}},
             {"A": None},
             {"A": []}, {"A": []}),
    ])

    record = json.loads(build_witness_view(consolidated).read_text())["records"][0]

    assert set(record) == RECORD_KEYS
    assert record["sentence"] is None
    assert record["passage"] is None
    assert record["verification"] is None
    assert record["bite_id"] is None
    assert record["claim"] == "the adjacent proposition"
    assert record["retrieval"]["silence_cause"] == "adjacent_topic"


def test_a_silent_book_the_composer_omits_still_gets_a_record(tmp_path, monkeypatch):
    monkeypatch.setattr("ParallelProse.witness_view.book_passage", lambda book, sentence: None)
    consolidated = write_session(tmp_path, [
        bite("1.1a", "q1",
             [],
             {"A": {"label": "silent", "lineage": [], "silence_cause": "absence", "P": None}},
             {"A": None},
             {"A": []}, {"A": []}),
    ])

    record = json.loads(build_witness_view(consolidated).read_text())["records"][0]

    assert record["corpus_id"] == "A"
    assert record["claim"] is None


def test_the_passage_is_the_evidence_and_travels_with_the_record(tmp_path, monkeypatch):
    looked_up = []
    monkeypatch.setattr("ParallelProse.witness_view.book_passage",
                        lambda book, sentence: looked_up.append(sentence) or "the paragraph the sentence sits in")
    consolidated = write_session(tmp_path, [
        bite("1.1a", "q1",
             [{"corpus_id": "A", "headline": "ha", "pairs": [pair("ca", "qa")]}],
             {"A": {"label": "ok", "lineage": [], "silence_cause": None}}, {"A": None},
             {"A": [{"status": "verbatim"}]}, {"A": ["idA"]}),
    ])

    record = json.loads(build_witness_view(consolidated).read_text())["records"][0]

    assert looked_up == ["qa"]
    assert record["passage"] == "the paragraph the sentence sits in"
    assert record["sentence"] == "qa"


def test_field_order_puts_the_evidence_before_the_claim(tmp_path, monkeypatch):
    monkeypatch.setattr("ParallelProse.witness_view.book_passage", lambda book, sentence: None)
    consolidated = write_session(tmp_path, [
        bite("1.1a", "q1",
             [{"corpus_id": "A", "headline": "ha", "pairs": [pair("ca", "qa")]}],
             {"A": {"label": "ok", "lineage": [], "silence_cause": None}}, {"A": None},
             {"A": [{"status": "verbatim"}]}, {"A": ["idA"]}),
    ])

    record = json.loads(build_witness_view(consolidated).read_text())["records"][0]
    keys = list(record)

    assert keys.index("sentence") < keys.index("claim")


def test_edition_and_query_code_travel_through(tmp_path, monkeypatch):
    monkeypatch.setattr("ParallelProse.witness_view.book_passage", lambda book, sentence: None)
    consolidated = write_session(tmp_path, [
        bite("2.3b", "a precise query",
             [{"corpus_id": "A", "headline": "ha", "pairs": [pair("ca", "qa")]}],
             {"A": {"label": "ok", "lineage": [{"tool": "x"}], "silence_cause": None}}, {"A": True},
             {"A": [{"status": "verbatim"}]}, {"A": ["idA"]}),
    ])

    record = json.loads(build_witness_view(consolidated).read_text())["records"][0]

    assert record["query_code"] == "2.3b" and record["query"] == "a precise query"
    assert record["edition"] == {"title": "Book A", "translator": "T.A."}
    assert record["retrieval"] == {"label": "ok", "side_is_target": True, "lineage": [{"tool": "x"}],
                                   "silence_cause": None}
    assert record["bite_id"] == "idA"
