import json

from ParallelProse import judges


def record():
    return {
        "id": "g01", "query": "q",
        "answer": {"unique_findings": [
            {"corpus_id": "A", "headline": "Saint Augustine says sleep is pleasant; Augustine's world causes it.",
             "pairs": [{"claim": "sleep is pleasant", "sentence": "held down pleasantly"},
                       {"claim": "the world causes it", "sentence": "held down pleasantly by the world"}]},
            {"corpus_id": "B", "headline": "query content is absent", "pairs": []},
        ]},
        "retrieval": {"A": {"label": "ok"}, "B": {"label": "silent"}},
        "chunks": {"A": ["the a passage"], "B": ["the b passage"]},
    }


def stub_judge(monkeypatch, answer):
    prompts = []

    def fake_judge(client, role, schema, prompt, callbacks=None):
        prompts.append(prompt)
        return answer(schema, prompt)

    monkeypatch.setattr(judges, "_judge", fake_judge)
    return prompts


def test_faithfulness_fails_on_any_unsupported_pair_and_skips_silent_books(monkeypatch):
    prompts = stub_judge(monkeypatch, lambda schema, prompt: judges.PairVerdict(
        supported="sleep is pleasant" in prompt))

    result = judges.faithfulness(record())

    assert result == {"A": {"pairs": 2, "unsupported": ["the world causes it"], "passed": False}}
    assert len(prompts) == 2  # one judge call per pair, and none for the silent book


def test_attribution_maps_the_blind_answer_back_to_the_book(monkeypatch):
    prompts = stub_judge(monkeypatch, lambda schema, prompt: judges.AttributionVerdict(
        source="1" if prompt.index("the a passage") < prompt.index("the b passage") else "2", reason="r"))

    result = judges.attribution(record())

    assert result["A"]["judged"] == "A" and result["A"]["passed"] is True
    assert "Passages 1" in prompts[0] and "augustine" not in prompts[0].lower()
    assert "the author says sleep is pleasant; the author's world causes it." in prompts[0]


def test_attribution_fails_when_the_finding_describes_the_other_book(monkeypatch):
    stub_judge(monkeypatch, lambda schema, prompt: judges.AttributionVerdict(
        source="2" if prompt.index("the a passage") < prompt.index("the b passage") else "1", reason="r"))

    assert judges.attribution(record())["A"] == {"judged": "B", "passed": False, "reason": "r"}


def test_judge_records_writes_a_row_per_pair_with_empty_human_fields_and_agreement_reads_them(monkeypatch, tmp_path):
    monkeypatch.setattr(judges, "faithfulness",
                        lambda r, callbacks=None: {"A": {"pairs": 2, "unsupported": [], "passed": True}})
    monkeypatch.setattr(judges, "attribution",
                        lambda r, callbacks=None: {"A": {"judged": "A", "passed": True}})

    rows = json.loads(judges.judge_records([record()], out_dir=tmp_path).read_text())

    assert set(rows[0]) == {"id", "book", "query", "claim", "sentence", "faithfulness", "attribution",
                            "human_faithful", "human_source"}
    assert [(r["id"], r["book"], r["human_faithful"], r["human_source"]) for r in rows] == [
        ("g01", "A", None, None), ("g01", "A", None, None)]
    assert [r["claim"] for r in rows] == ["sleep is pleasant", "the world causes it"]
    assert [r["sentence"] for r in rows] == ["held down pleasantly", "held down pleasantly by the world"]
    assert [r["faithfulness"] for r in rows] == [{"passed": True}, {"passed": True}]
    rows[0]["human_faithful"], rows[0]["human_source"] = False, "A"
    report = judges.judge_agreement(rows)
    assert report["faithfulness"] == {"labelled": 1, "agree": 0, "disagree": ["g01 A"]}
    assert report["attribution"] == {"labelled": 1, "agree": 1, "disagree": []}
