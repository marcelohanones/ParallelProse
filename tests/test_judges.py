import json

from ParallelProse import judges


def record():
    return {
        "id": "g01", "query": "q",
        "answer": {"unique_findings": [
            {"corpus_id": "A", "headline": "Saint Augustine says sleep is pleasant; Augustine's world causes it.",
             "pairs": [{"claim": "sleep is pleasant", "sentence": "held down pleasantly"},
                       {"claim": "the world causes it", "sentence": "held down pleasantly by the world"}],
             "unpaired": ["no single sentence states this one"]},   # judged by nothing; it is what coverage reports
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


def segmented(*segments) -> "judges.PairJudgement":
    """A judgement whose segments tile their claim: (segment, relation_or_addition, span) triples. A string relation
    is `stated`/`one_step`; a (kind, text) tuple is an extracted addition, which is what makes a segment absent."""
    built = []
    for segment, verdict, span in segments:
        adds, relation = [], "stated"
        if isinstance(verdict, tuple):
            adds = [judges.SegmentAddition(kind=verdict[0], text=verdict[1])]
        else:
            relation = verdict
        built.append(judges.ClaimSegment(segment=segment, read_as=segment, evidence_span=span,
                                         adds=adds, relation=relation))
    return judges.PairJudgement(segments=built)


def test_faithfulness_reads_lenient_but_reports_strict_coverage_and_the_profile(monkeypatch):
    prompts = stub_judge(monkeypatch, lambda schema, prompt: segmented(
        ("sleep is pleasant", "stated", "held down pleasantly"))
        if "sleep is pleasant" in prompt else
        segmented(("the world", "stated", "by the world"), (" causes it", ("cause_means", "causes it"), None)))

    result = judges.faithfulness(record())

    assert result["A"]["pairs"] == 2 and result["A"]["unsupported"] == ["the world causes it"]
    assert result["A"]["passed"] is False            # M7: `passed` is the lenient view
    assert result["A"]["rate"] == 0.5 and result["A"]["rate_strict"] == 0.5
    assert result["A"]["unpaired"] == 1 and result["A"]["coverage"] == 2 / 3
    assert result["A"]["addition_profile"] == {"cause_means": 1} and result["A"]["judge_version"] == 2
    # the producer metric counts pairs, not items, and only the three defect families (DSH-63)
    assert result["A"]["defect_family_pairs"] == {"agent": 0, "cause_means": 1, "consequence": 0}
    assert result["A"]["stated_typings"] == 2       # Markim's condition: is the strict column meaningful at all
    assert result["A"]["repaired_absent"] == 0      # this absent is the model's, not code's
    assert [r["strict"] for r in result["A"]["pair_results"]] == [True, False]
    assert set(result) == {"A"}
    assert len(prompts) == 2


def test_an_extracted_addition_makes_the_pair_absent_whatever_the_relation_says(monkeypatch):
    """v4: the model no longer classifies the pair. An addition anywhere decides it, in code."""
    stub_judge(monkeypatch, lambda schema, prompt: judges.PairJudgement(segments=[
        judges.ClaimSegment(segment="Stars embody the results", read_as="Stars embody the results",
                            evidence_span="They embody the inaccessible results", relation="stated",
                            adds=[judges.SegmentAddition(kind="agent", text="Stars")])]))

    outcome = judges.judge_pair_detail("Stars embody the results", "They embody the inaccessible results")

    assert outcome.relations == ("absent",) and outcome.raw_relations == ("absent",)
    assert outcome.additions == ("agent",) and outcome.repaired_absent is False
    assert outcome.strict is False and outcome.lenient is False


def test_a_rename_claimed_as_an_addition_is_only_flagged(monkeypatch):
    """p11's shape: every word of the addition is already in the sentence. Detection is semantic, so code flags and
    never gates -- the subject swap it would otherwise erase is a real addition."""
    stub_judge(monkeypatch, lambda schema, prompt: judges.PairJudgement(segments=[
        judges.ClaimSegment(segment="the spectacle remolded reality", read_as="the spectacle remolded reality",
                            evidence_span="the ideology that has remolded all reality", relation="stated",
                            adds=[judges.SegmentAddition(kind="agent", text="the spectacle")])]))

    outcome = judges.judge_pair_detail("the spectacle remolded reality",
                                       "an ideology that has remolded all reality, not the spectacle")

    assert outcome.relations == ("absent",) and outcome.rename_suspects == ("agent:the spectacle",)
    assert outcome.invalid_add is False


def test_an_addition_that_is_not_text_of_its_segment_is_dropped_not_kept(monkeypatch):
    """DSH-46: keeping an unverifiable item failed p43, a `covered` pair, on something nothing could check. It is
    dropped and counted as extraction health, never as a verdict."""
    stub_judge(monkeypatch, lambda schema, prompt: one_addition(
        "sleep is pleasant", "a fragment nobody wrote"))

    outcome = judges.judge_pair_detail("sleep is pleasant", "held down pleasantly")

    assert outcome.invalid_add is True and outcome.additions == ()
    assert outcome.relations == ("stated",) and outcome.lenient is True
    assert "invalid:a fragment nobody wrote" in outcome.addition_texts


def test_an_addition_made_only_of_a_connective_is_not_an_addition(monkeypatch):
    """DSH-47(iii): p07's `other:while` was costing a positive pair. A connective carries no content, so it cannot
    be content the sentence lacks -- the same list C2 already exempts, applied to `adds`."""
    stub_judge(monkeypatch, lambda schema, prompt: one_addition(
        "while sleep is pleasant", "while", span="held down pleasantly"))

    outcome = judges.judge_pair_detail("while sleep is pleasant", "held down pleasantly")

    assert outcome.additions == () and outcome.relations == ("stated",)
    assert "connective:while" in outcome.addition_texts


def test_a_fabricated_span_is_downgraded_by_code_and_marked_as_a_repair(monkeypatch):
    stub_judge(monkeypatch, lambda schema, prompt: segmented(
        ("sleep is pleasant", "stated", "a span the sentence does not contain")))

    outcome = judges.judge_pair_detail("sleep is pleasant", "held down pleasantly")

    assert outcome.strict is False and outcome.invalid_span is True
    assert outcome.relations == ("absent",) and outcome.raw_relations == ("stated",)
    assert outcome.repaired_absent is True and outcome.additions == ("other",)


def test_a_dropped_structural_connective_is_exempt_but_a_causal_one_is_not(monkeypatch):
    """The p43 bug: "while" cost a `covered` pair its lenient pass on the first dry-run."""
    stub_judge(monkeypatch, lambda schema, prompt: judges.PairJudgement(segments=[
        judges.ClaimSegment(segment="while truth is profane", read_as="truth is profane",
                            evidence_span="truth is considered profane", relation="stated")]))
    outcome = judges.judge_pair_detail("while truth is profane", "truth is considered profane")
    assert outcome.lenient is True and outcome.exempted_terms == ("while",) and outcome.c2_repairs == 0

    stub_judge(monkeypatch, lambda schema, prompt: judges.PairJudgement(segments=[
        judges.ClaimSegment(segment="because truth is profane", read_as="truth is profane",
                            evidence_span="truth is considered profane", relation="stated")]))
    outcome = judges.judge_pair_detail("because truth is profane", "truth is considered profane")
    assert outcome.lenient is False and outcome.c2_repairs == 1


def one_addition(segment, text, kind="other", counterpart=None, span="held down pleasantly", relation="stated"):
    return judges.PairJudgement(segments=[judges.ClaimSegment(
        segment=segment, read_as=segment, evidence_span=span, relation=relation,
        adds=[judges.SegmentAddition(text=text, kind=kind, counterpart=counterpart)])])


def test_an_addition_with_a_real_counterpart_is_a_rename_and_stops_deciding(monkeypatch):
    """Arm A (DSH-41): the comparison the model already makes for the span, applied to the fragment it flagged."""
    stub_judge(monkeypatch, lambda schema, prompt: one_addition(
        "modern society prefers signs", "modern society", kind="quantity_generalization",
        counterpart="the present age", span="the present age prefers the sign"))

    outcome = judges.judge_pair_detail("modern society prefers signs", "the present age prefers the sign")

    # `raw` is the model's verdict after the counterpart pass: an item it quoted a counterpart for was never a claim
    # of addition, so nothing here was repaired by code.
    assert outcome.relations == ("stated",) and outcome.raw_relations == ("stated",)
    assert outcome.repaired_absent is False
    assert outcome.additions == () and outcome.renames == ("quantity_generalization:modern society->the present age",)
    assert outcome.lenient is True and outcome.model_relations == ("stated",)


def test_a_pronoun_is_not_a_counterpart(monkeypatch):
    """The fabrication the agent family would hide behind: "They" refers, it does not state."""
    stub_judge(monkeypatch, lambda schema, prompt: one_addition(
        "Stars embody the results", "Stars", kind="agent", counterpart="They",
        span="They embody the inaccessible results"))

    outcome = judges.judge_pair_detail("Stars embody the results", "They embody the inaccessible results")

    assert outcome.relations == ("absent",) and outcome.additions == ("agent",)
    assert outcome.renames == () and outcome.invalid_counterpart is True


def test_a_function_word_counterpart_is_kept_but_a_pointer_is_not(monkeypatch):
    """c14's failure in the first arm-A run was my own rule: "is" has no content word, and refusing it as a
    counterpart for "serves as" cost a `covered` pair. A bare pointer is still refused."""
    stub_judge(monkeypatch, lambda schema, prompt: one_addition(
        "ideology serves as the basis", "serves as", counterpart="is",
        span="ideology is the intellectual basis"))
    outcome = judges.judge_pair_detail("ideology serves as the basis", "ideology is the intellectual basis")
    assert outcome.renames == ("other:serves as->is",) and outcome.invalid_counterpart is False

    stub_judge(monkeypatch, lambda schema, prompt: one_addition(
        "ideology serves as the basis", "serves as", counterpart="it",
        span="it is the intellectual basis"))
    outcome = judges.judge_pair_detail("ideology serves as the basis", "it is the intellectual basis")
    assert outcome.renames == () and outcome.invalid_counterpart is True


def test_read_as_may_borrow_grammar_but_not_the_sentence_s_words(monkeypatch):
    """d12's failure in the first arm-A run: `read_as` used "occurs", a verb the claim lacks and the sentence does
    not have either -- grammar, not smuggling. Importing a word the sentence *does* carry still fails."""
    stub_judge(monkeypatch, lambda schema, prompt: judges.PairJudgement(segments=[judges.ClaimSegment(
        segment="in modern time", read_as="modern time occurs", evidence_span="in modern times",
        relation="one_step")]))
    outcome = judges.judge_pair_detail("in modern time", "in modern times")
    assert outcome.lenient is True and outcome.c2_repairs == 0

    stub_judge(monkeypatch, lambda schema, prompt: judges.PairJudgement(segments=[judges.ClaimSegment(
        segment="in modern time", read_as="modern time is alienated", evidence_span="in modern times",
        relation="one_step")]))
    outcome = judges.judge_pair_detail("in modern time", "in modern times, alienated from itself")
    assert outcome.lenient is False and outcome.c2_repairs == 1


def test_a_counterpart_the_sentence_does_not_contain_is_rejected(monkeypatch):
    stub_judge(monkeypatch, lambda schema, prompt: one_addition(
        "sleep is pleasant and good", "and good", counterpart="a phrase nobody wrote"))

    outcome = judges.judge_pair_detail("sleep is pleasant and good", "held down pleasantly")

    assert outcome.invalid_counterpart is True and outcome.additions == ("other",)
    assert any("not text of the sentence" in r for r in outcome.rewrites)


def test_a_tiling_failure_buys_one_retry_and_then_fails_the_pair(monkeypatch):
    prompts = stub_judge(monkeypatch, lambda schema, prompt: segmented(
        ("sleep is pleasant", "stated", "held down pleasantly")))      # drops "and the world causes it"

    outcome = judges.judge_pair_detail("sleep is pleasant and the world causes it", "held down pleasantly")

    assert outcome.strict is False and outcome.pair_error is not None
    assert len(prompts) == 2 and "failed the segmentation rule" in prompts[1]


def test_one_step_passes_lenient_only(monkeypatch):
    stub_judge(monkeypatch, lambda schema, prompt: segmented(
        ("sleep is agreeable", "one_step", "held down pleasantly")))

    outcome = judges.judge_pair_detail("sleep is agreeable", "held down pleasantly")

    assert outcome.strict is False and outcome.lenient is True and outcome.singleton is True


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


def test_judge_records_writes_a_row_per_pair_keyed_by_index_and_agreement_reads_both_views(monkeypatch, tmp_path):
    monkeypatch.setattr(judges, "faithfulness", lambda r, callbacks=None: {"A": {
        "pairs": 2, "unsupported": [], "passed": True,
        "pair_results": [{"strict": True, "lenient": True, "relations": ["stated"], "additions": [],
                          "repaired_absent": False, "invalid_span": False, "pair_error": None, "singleton": True},
                         {"strict": False, "lenient": True, "relations": ["one_step"], "additions": [],
                          "repaired_absent": False, "invalid_span": False, "pair_error": None, "singleton": True}]}})
    monkeypatch.setattr(judges, "attribution",
                        lambda r, callbacks=None: {"A": {"judged": "A", "passed": True}})

    rows = json.loads(judges.judge_records([record()], out_dir=tmp_path).read_text())

    assert set(rows[0]) == {"id", "book", "pair", "query", "claim", "sentence", "faithfulness", "attribution",
                            "human_faithful", "human_lenient", "human_source"}
    assert [(r["id"], r["book"], r["pair"]) for r in rows] == [("g01", "A", 0), ("g01", "A", 1)]
    assert [r["faithfulness"]["passed"] for r in rows] == [True, True]     # M7: passed is lenient
    assert [r["faithfulness"]["strict"] for r in rows] == [True, False]
    assert all(r["faithfulness"]["judge_version"] == 2 for r in rows)

    # a strict `true` label implies the lenient one: without that rule the lenient reader scores only negative rows
    rows[0]["human_faithful"] = True
    rows[1]["human_faithful"], rows[1]["human_lenient"] = False, False
    report = judges.judge_agreement(rows)

    assert report["faithfulness"] == {"labelled": 2, "agree": 1, "disagree": ["g01 A 1"]}
    assert report["faithfulness_strict"] == {"labelled": 2, "agree": 2, "disagree": []}
    assert report["attribution"] == {"labelled": 0, "agree": 0, "disagree": []}
