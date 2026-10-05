import json

from ParallelProse.one_sided import classify as one_sided_report_classify
from ParallelProse.one_sided import one_sided_report


def bite(a, b):
    findings = [{"corpus_id": "A", "finding": a, "quote": None}, {"corpus_id": "B", "finding": b, "quote": None}]
    return {"query": "q", "answer": {"agreement": "x", "disagreement": "x", "unique_findings": findings}}


def test_one_sided_report_counts_each_case(tmp_path):
    theme = tmp_path / "theme-01_t"
    theme.mkdir(parents=True)
    bites = [bite("a", "b"), bite("query content is absent", "b"), bite("a", "query content is absent"),
             bite("query content is absent", "query content is absent")]
    (theme / "thesis-01.json").write_text(json.dumps({"theme": "t", "thesis": "x", "bites": bites}))

    report = one_sided_report(tmp_path)

    assert report["total"] == 4
    assert report["counts"] == {"both": 1, "one-sided (A silent)": 1, "one-sided (B silent)": 1, "neither": 1}
    assert one_sided_report_classify(bite("query content is absent", "b")["answer"]) == "one-sided (A silent)"
    assert one_sided_report_classify(bite("a", "query content is absent")["answer"]) == "one-sided (B silent)"
    assert report["one_sided_share"] == 0.5
    assert report["within_threshold"] is False
