import json

from ParallelProse.one_sided import classify as one_sided_report_classify
from ParallelProse.one_sided import one_sided_report


def bite(a, b):
    return {"query": "q", "retrieval": {"A": {"label": a}, "B": {"label": b}}}


def test_one_sided_report_counts_each_case(tmp_path):
    theme = tmp_path / "theme-01_t"
    theme.mkdir(parents=True)
    bites = [bite("ok", "ok"), bite("silent", "ok"), bite("ok", "silent"), bite("silent", "silent")]
    (theme / "thesis-01.json").write_text(json.dumps({"theme": "t", "thesis": "x", "bites": bites}))

    report = one_sided_report(tmp_path)

    assert report["total"] == 4
    assert report["counts"] == {"both": 1, "one-sided (A silent)": 1, "one-sided (B silent)": 1, "neither": 1}
    assert one_sided_report_classify(bite("silent", "ok")["retrieval"]) == "one-sided (A silent)"
    assert one_sided_report_classify(bite("ok", "silent")["retrieval"]) == "one-sided (B silent)"
    assert report["one_sided_share"] == 0.5
    assert report["within_threshold"] is False


def test_a_miss_book_is_not_counted_as_silent():
    assert one_sided_report_classify({"A": {"label": "miss"}, "B": {"label": "ok"}}) == "both"
