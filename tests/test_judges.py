import json

from ParallelProse import judges


def record():
    return {
        "id": "g01", "query": "q",
        "answer": {"unique_findings": [
            {"corpus_id": "A", "finding": "Saint Augustine says sleep is pleasant; Augustine's world causes it.", "quote": "held down pleasantly"},
            {"corpus_id": "B", "finding": "query content is absent", "quote": None},
        ]},
        "retrieval": {"A": {"label": "ok"}, "B": {"label": "silent"}},
        "chunks": {"A": ["the a passage"], "B": ["the b passage"]},
    }


def stub_judge(monkeypatch, answer):
    prompts = []

    def fake_judge(schema, prompt):
        prompts.append(prompt)
        return answer(schema, prompt)

    monkeypatch.setattr(judges, "_judge", fake_judge)
    return prompts


def test_faithfulness_fails_on_any_unsupported_claim_and_skips_silent_books(monkeypatch):
    stub_judge(monkeypatch, lambda schema, prompt: judges.FaithfulnessVerdict(claims=[
        judges.ClaimCheck(claim="sleep is pleasant", supported=True),
        judges.ClaimCheck(claim="the world causes it", supported=False)]))

    result = judges.faithfulness(record())

    assert result == {"A": {"claims": 2, "unsupported": ["the world causes it"], "passed": False}}


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


def test_judge_records_writes_rows_with_empty_human_fields_and_agreement_reads_them(monkeypatch, tmp_path):
    monkeypatch.setattr(judges, "faithfulness", lambda r: {"A": {"passed": True}})
    monkeypatch.setattr(judges, "attribution", lambda r: {"A": {"judged": "A", "passed": True}})

    rows = json.loads(judges.judge_records([record()], out_dir=tmp_path).read_text())

    assert [(r["id"], r["book"], r["human_faithful"], r["human_source"]) for r in rows] == [("g01", "A", None, None)]
    rows[0]["human_faithful"], rows[0]["human_source"] = False, "A"
    report = judges.judge_agreement(rows)
    assert report["faithfulness"] == {"labelled": 1, "agree": 0, "disagree": ["g01 A"]}
    assert report["attribution"] == {"labelled": 1, "agree": 1, "disagree": []}
