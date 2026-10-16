"""Item 50 Phase 0 replay: the machinery, no network, no paid call."""

from types import SimpleNamespace

from ParallelProse import citation_replay as cr


def response(blocks, cache_read=0):
    content = [SimpleNamespace(type="text", text=text, citations=[SimpleNamespace(**c) for c in cites])
               for text, cites in blocks]
    return SimpleNamespace(content=content,
                           usage=SimpleNamespace(input_tokens=3000, output_tokens=40,
                                                 cache_read_input_tokens=cache_read))


SENTENCES = ["First one.", "Second, with a colon: here;", "Third."]


def test_request_is_one_custom_content_document_with_effort_low():
    request = cr.make_request("a claim", SENTENCES, "A -- book", "claude-haiku-5-5")
    document, text = request["messages"][0]["content"]
    assert document["type"] == "document" and document["source"]["type"] == "content"
    assert [b["text"] for b in document["source"]["content"]] == SENTENCES
    assert document["citations"] == {"enabled": True}
    assert "cache_control" not in document, "measured: cache_control on a citated document suppresses citations"
    assert text["type"] == "text" and "Never" in text["text"]
    assert cr.make_request("c", SENTENCES, "t", "m", prompt=cr.COPY_PROMPT)["messages"][0]["content"][-1]["text"].endswith(cr.NONE_ANSWER)
    assert request["output_config"] == {"effort": "low"}
    assert "format" not in request["output_config"], "citations x output_config.format is HTTP 400"


def test_make_request_refuses_an_empty_candidate_list():
    raised = False
    try:
        cr.make_request("a claim", [], "A -- book", "m")
    except AssertionError:
        raised = True
    assert raised, "an empty candidate list must not build a document-less request"


def test_read_answer_maps_a_block_range():
    answer = cr.read_answer(response([("Second, with a colon: here;", [
        {"cited_text": "Second, with a colon: here;", "start_block_index": 1, "end_block_index": 1}])]), SENTENCES)
    assert answer["declined"] is False and answer["start_blocks"] == [1] and answer["invalid_block_index"] is False


def test_read_answer_separates_decline_from_unfounded():
    declined = cr.read_answer(response([(cr.NONE_ANSWER, [])]), SENTENCES)
    unfounded = cr.read_answer(response([("Some sentence I made up.", [])]), SENTENCES)
    assert declined["declined"] is True and declined["unfounded"] is False
    assert unfounded["declined"] is False and unfounded["unfounded"] is True


def test_read_answer_flags_an_out_of_range_block_index():
    answer = cr.read_answer(response([("quote", [{"cited_text": "quote", "start_block_index": 7,
                                                  "end_block_index": 7}])]), SENTENCES)
    assert answer["invalid_block_index"] is True


def test_buckets_cover_every_case():
    same = cr.read_answer(response([("First one.", [{"cited_text": "First one.", "start_block_index": 0,
                                                     "end_block_index": 0}])]), SENTENCES)
    other = cr.read_answer(response([("Third.", [{"cited_text": "Third.", "start_block_index": 2,
                                                  "end_block_index": 2}])]), SENTENCES)
    declined = cr.read_answer(response([(cr.NONE_ANSWER, [])]), SENTENCES)
    unfounded = cr.read_answer(response([("invented", [])]), SENTENCES)
    assert cr.bucket_of("First one.", same, SENTENCES) == "1a"
    assert cr.bucket_of(None, declined, SENTENCES) == "1b"
    assert cr.bucket_of("First one.", other, SENTENCES) == "2"
    assert cr.bucket_of("First one.", declined, SENTENCES) == "3"
    assert cr.bucket_of(None, same, SENTENCES) == "4"
    assert cr.bucket_of("First one.", unfounded, SENTENCES) == "unfounded"


def test_an_empty_answer_is_not_a_selection():
    empty = cr.read_answer(SimpleNamespace(content=[], usage=None, stop_reason="max_tokens"), SENTENCES)
    assert empty["empty"] is True and empty["declined"] is False and empty["stop_reason"] == "max_tokens"
    assert cr.bucket_of("First one.", empty, SENTENCES) == "empty"


def test_cited_range_end_is_exclusive_and_strict_needs_exactly_one():
    one = cr.read_answer(response([("Second, with a colon: here;", [
        {"cited_text": "Second, with a colon: here;", "start_block_index": 1, "end_block_index": 2}])]), SENTENCES)
    assert one["cited_blocks"] == [1], "(1, 2) is block 1 alone"
    assert cr.same_sentence(one, "Second, with a colon: here;", SENTENCES, "strict") is True
    two = cr.read_answer(response([("quote", [
        {"cited_text": "First one.", "start_block_index": 0, "end_block_index": 1},
        {"cited_text": "Second, with a colon: here;", "start_block_index": 1, "end_block_index": 2}])]), SENTENCES)
    assert two["cited_blocks"] == [0, 1]
    assert cr.same_sentence(two, "Second, with a colon: here;", SENTENCES, "lenient") is True
    assert cr.same_sentence(two, "Second, with a colon: here;", SENTENCES, "strict") is False
    assert cr.bucket_of("Second, with a colon: here;", two, SENTENCES, "strict") == "2"
    assert cr.bucket_of("Second, with a colon: here;", two, SENTENCES, "lenient") == "1a"


def test_unpaired_cause_separates_judgement_reuse_and_malformed():
    assert cr.unpaired_cause(None, 10, set()) == "4a"
    assert cr.unpaired_cause(3, 10, {3}) == "4b"
    assert cr.unpaired_cause(99, 10, set()) == "4c"
    assert cr.unpaired_cause(4, 10, {3}) == "4d"


def test_the_sheet_shows_three_candidates_whatever_the_bucket():
    import json as _json

    sentences = ["First one.", "Second one; here.", "Third one.", "Fourth one."]
    slot = {("g01", "A"): sentences}
    base = {"record": "g01", "corpus_id": "A", "declined": False, "unfounded": False,
            "start_blocks": [], "invalid_block_index": False, "cited_block_count": 1}
    rows_in = [
        dict(base, claim="c1", picker="First one.", cited_texts=["First one."], bucket="1a",
             bucket_lenient="1a", answer_text="First one."),
        dict(base, claim="c2", picker=None, cited_texts=[], bucket="1b", bucket_lenient="1b",
             declined=True, answer_text=cr.NONE_ANSWER),
        dict(base, claim="c3", picker="Second one; here.", cited_texts=["Third one."], bucket="2",
             bucket_lenient="2", answer_text="Third one."),
        dict(base, claim="c4", picker="Second one; here.", cited_texts=[], bucket="3",
             bucket_lenient="3", declined=True, answer_text=cr.NONE_ANSWER),
        dict(base, claim="c5", picker=None, cited_texts=["Fourth one."], bucket="4",
             bucket_lenient="4", answer_text="Fourth one."),
    ]
    rows, key, sampling = cr.blind_sheet(rows_in, slot, bucket3_sample=5, agree_sample=5)
    assert len(rows) == 5 and sampling["rows_in_the_sitting"] == 5
    by_claim = {row["claim"]: row for row in rows}
    for row in rows:
        assert len(row["candidates"]) == 3, "the shape must not leak the bucket (CC-52)"
        assert set(row) == {"id", "claim", "candidates"}, "no origin, no bucket in the row"
    assert "First one." in by_claim["c1"]["candidates"]
    assert set(by_claim["c2"]["candidates"]) <= set(sentences), "a shared refusal must show what it passed over"
    assert "Second one; here." in by_claim["c3"]["candidates"]
    assert "Third one." in by_claim["c3"]["candidates"]
    assert "Second one; here." in by_claim["c4"]["candidates"]
    assert "Fourth one." in by_claim["c5"]["candidates"]
    assert all(len(key[sid]["candidate_origin"]) == 3 for sid in key)
    assert set(key[next(iter(key))]) >= {"bucket", "picker", "citation", "candidate_origin"}


def _unused_old_sheet_test():
    results = [
        {"record": "g01", "corpus_id": "A", "claim": "c1", "picker": "picker sentence",
         "bucket": "2", "declined": False, "unfounded": False, "cited_texts": ["citation sentence"],
         "start_blocks": [0], "invalid_block_index": False, "answer_text": "citation sentence"},
        {"record": "g01", "corpus_id": "B", "claim": "c2", "picker": "picker sentence",
         "bucket": "3", "declined": True, "unfounded": False, "cited_texts": [], "start_blocks": [],
         "invalid_block_index": False, "answer_text": cr.NONE_ANSWER},
    ]
    third = {"record": "g01", "corpus_id": "B", "claim": "c3", "picker": None,
                   "bucket": "4", "declined": False, "unfounded": False, "cited_texts": ["citation sentence"],
                   "start_blocks": [3], "invalid_block_index": False, "answer_text": "citation sentence"}
    rows, key, sampling = cr.blind_sheet(results + [third], bucket3_sample=3, agree_sample=0)
    assert sampling["rows_in_the_sitting"] == 3 and sampling["seed"] == 20261015
    assert len(rows) == 3 and all("bucket" not in row and "origin" not in row for row in rows)
    by_claim = {row["claim"]: row for row in rows}
    assert set(by_claim["c1"]["options"]) == {"picker sentence", "citation sentence"}
    assert set(by_claim["c2"]["options"]) == {"picker sentence", cr.NONE_OPTION}
    assert set(by_claim["c3"]["options"]) == {"citation sentence", cr.NONE_OPTION}, "the picker's unpaired is a side"
    assert all(sorted(order) in (["citation", "picker"], ["none", "picker"], ["citation", "none"])
               for order in (key[sid]["option_order"] for sid in key))


def test_the_sitting_is_capped_by_bucket3_sampling():
    many = [dict(bucket="3", claim="c%d" % i, picker="p", declined=True, unfounded=False,
                 cited_texts=[], start_blocks=[], invalid_block_index=False, answer_text=cr.NONE_ANSWER,
                 bucket_lenient="3", cited_block_count=0, record="g", corpus_id="A") for i in range(40)]
    rows, key, sampling = cr.blind_sheet(many, {}, bucket3_sample=25, agree_sample=15)
    assert len(rows) == 25 and sampling["bucket3_total"] == 40 and sampling["bucket3_sampled"] == 25
    assert sampling["bucket3_rate"] == 0.625


def test_dry_run_reads_the_frozen_record_without_a_client(tmp_path):
    out = tmp_path / "replay.json"
    assert cr.main(["--limit", "2", "--out", str(out)]) == 0
    record = cr.json.loads(out.read_text())
    assert record["dry_run"]["slots"] > 0 and record["dry_run"]["claims"] > 0
