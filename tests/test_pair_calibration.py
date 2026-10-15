"""The scoring core of item 48's calibration: cells, floors, gate and abort rule, with no API call.

The two accuracy examples are the ones recorded in the spec (section 7): a matrix that passes can score below the
constant-rejecter floor, and a matrix that fails can score far above it -- which is why the matrix is the bar.
"""

import json

import pytest

from ParallelProse import pair_calibration as pc


@pytest.fixture(scope="module")
def labels():
    return pc.load_labels()


@pytest.fixture(scope="module")
def families():
    return json.loads(pc.FAMILIES_PATH.read_text())


def typings(labels, *, covered="stated", disputed="stated", one_step="one_step", not_covered="absent",
            overrides=None):
    """A whole round's typings, one value per reference row, with named exceptions."""
    by_row = {"covered": covered, "covered_disputed": disputed, "covered_one_step": one_step,
              "not_covered": not_covered}
    out = {ref: by_row[pc.rows_of(labels, ref)] for ref in labels}
    out.update(overrides or {})
    return out


def test_the_rows_are_the_label_set_as_m1_splits_it(labels):
    rows = pc.matrix(labels, typings(labels))
    assert {row: cell["n"] for row, cell in rows.items()} == {
        "covered": 14, "covered_disputed": 5, "covered_one_step": 25, "not_covered": 96}
    assert rows["covered"]["correct"] == 14 and rows["not_covered"]["correct"] == 96


def test_a_perfect_round_passes_every_cell(labels, families):
    report = pc.gate(labels, [typings(labels)] * 3, families)
    assert report["passed"] is True
    assert report["reps"][0]["accuracies"]["strict"]["agree"] == 140


def test_a_passing_matrix_can_score_below_the_strict_floor(labels, families):
    """f = 14 not-covered false passes typed `stated`, 4 one_step pairs typed `stated`, the disputed typed
    `one_step`: every cell holds and strict accuracy is 117/140, below the 121 a constant rejecter reaches. The 14
    leaks are taken outside the gated agent refs on purpose -- inside them, one leak would disqualify."""
    gated = set(families["gate"]["refs"])
    not_covered_refs = [ref for ref in labels
                        if labels[ref][1].klass == "not_covered" and ref not in gated][:14]
    one_step_refs = [ref for ref in labels if labels[ref][1].klass == "covered_one_step"][:4]
    round_typings = typings(labels, disputed="one_step",
                            overrides={**{ref: "stated" for ref in not_covered_refs},
                                       **{ref: "stated" for ref in one_step_refs}})
    report = pc.gate(labels, [round_typings] * 3, families)

    assert report["passed"] is True
    assert report["checks"]["covered_at_least_13_of_14"] and report["checks"]["not_covered_at_least_82"]
    assert report["checks"]["not_a_rejecter_model_absent_at_most_120"]
    assert report["positives_non_absent"] == [39, 39, 39]
    assert report["reps"][0]["accuracies"]["strict"] == {"agree": 117, "of": 140, "floor_on_140": 121}


def test_a_failing_matrix_can_score_far_above_it(labels, families):
    """One covered pair typed `absent` -- a hard false negative -- and nothing else wrong: 139/140 strict, and the
    gate fails anyway. Under M7 the same pair typed `one_step` would not fail: that boundary is not a gate."""
    one_covered = next(ref for ref in labels if pc.rows_of(labels, ref) == "covered")

    covered = [ref for ref in labels if pc.rows_of(labels, ref) == "covered"][:2]
    two_absent = pc.gate(labels, [typings(labels, overrides={r: "absent" for r in covered})] * 3, families)
    assert two_absent["passed"] is False and two_absent["checks"]["covered_at_least_13_of_14"] is False
    assert two_absent["reps"][0]["accuracies"]["strict"]["agree"] == 138

    # the re-scope tolerates the one known false negative (p39) and still cannot be met by a rejecter
    one_absent = pc.gate(labels, [typings(labels, overrides={one_covered: "absent"})] * 3, families)
    assert one_absent["passed"] is True and one_absent["covered_non_absent"] == [13, 13, 13]

    rejecter = pc.gate(labels, [{ref: "absent" for ref in labels}] * 3, families)
    assert rejecter["passed"] is False
    assert rejecter["checks"]["not_a_rejecter_model_absent_at_most_120"] is False
    assert rejecter["checks"]["not_covered_at_least_82"] is True      # a rejecter aces the negative cell alone


def test_the_strict_column_is_reported_as_vacuous_when_stated_is_never_used(labels, families):
    """Markim's fourth condition on M7: a round where the judge never types `stated` says the label went unused, not
    that the text is faithful -- the second column must be marked, never published as a number."""
    all_one_step = pc.gate(labels, [typings(labels, covered="one_step", disputed="one_step")] * 3, families)
    assert all_one_step["strict_column_is_vacuous"] is True and all_one_step["stated_typings"] == [0, 0, 0]
    assert all_one_step["passed"] is True          # and the gate still passes: lenient is the headline

    normal = pc.gate(labels, [typings(labels)] * 3, families)
    assert normal["strict_column_is_vacuous"] is False


def test_one_leak_on_a_gated_agent_ref_disqualifies_on_its_own(labels, families):
    gated_agent = [ref for ref, row in families["pairs"].items()
                   if row["gate"] and row["family"] == "agent_subject"]
    assert len(gated_agent) == 9

    clean = typings(labels)
    leaked = typings(labels, overrides={gated_agent[0]: "one_step"})
    report = pc.gate(labels, [leaked, clean, clean], families)

    assert report["passed"] is False
    assert report["checks"]["zero_false_pass_on_gated_agent_refs"] is False
    assert report["gated_agent_leaks"] == [gated_agent[0]]
    # the same leak also shows in the union count, which is what a flipping pair exists to catch
    assert report["not_covered_false_pass_union"] == 1


def test_instability_is_counted_across_repetitions(labels, families):
    flipper = next(ref for ref in labels if labels[ref][1].klass == "covered_one_step")
    report = pc.gate(labels, [typings(labels), typings(labels, overrides={flipper: "absent"}),
                              typings(labels)], families)
    assert report["unstable"] == [flipper] and report["checks"]["stability_at_most_5_unstable"] is True


def test_the_abort_rule_fires_on_the_first_uncontested_covered_miss(labels):
    one_covered = next(ref for ref in labels if pc.rows_of(labels, ref) == "covered")
    one_disputed = pc.DISPUTED[0]

    assert pc.abort(labels, typings(labels)) == []
    assert pc.abort(labels, typings(labels, overrides={one_covered: "absent"})) == [one_covered]
    # a disputed pair is reported, never gated, so it cannot abort a round
    assert pc.abort(labels, typings(labels, overrides={one_disputed: "absent"})) == []


def test_typing_reads_the_two_views_off_one_outcome():
    class Outcome:
        def __init__(self, strict, lenient):
            self.strict, self.lenient = strict, lenient

    assert pc.typing_of(Outcome(True, True)) == "stated"
    assert pc.typing_of(Outcome(False, True)) == "one_step"
    assert pc.typing_of(Outcome(False, False)) == "absent"


def test_run_round_assembles_a_record_without_touching_an_api(monkeypatch, tmp_path):
    """The record path, stubbed end to end, asserting the whole key set. The first v4 dry-run paid for 16 calls and
    then died writing this structure (a property that `asdict` drops), so nothing here is exercised for the first
    time by a paid run (DSH-45.4)."""
    from ParallelProse import judges

    def fake_detail(claim, sentence, client=None, callbacks=None, retries=1):
        return judges.PairOutcome(
            strict=False, lenient=False, relations=("absent",), raw_relations=("stated",),
            model_relations=("stated",), additions=("other",), addition_texts=("other:x",),
            renames=("agent:a->b",), invalid_span=True, invalid_add=False, invalid_counterpart=False,
            rename_suspects=(), exempted_terms=("while",), c2_repairs=0, pair_error=None,
            singleton=True, rewrites=("r",))

    monkeypatch.setattr(judges, "judge_pair_detail", fake_detail)
    path = pc.run_round(refs=["p01", "p39"], reps=2, out_dir=tmp_path, tag="stub")
    record = json.loads(path.read_text())

    assert set(record) == {"what", "model", "judge_version", "prompt_revision", "instructions_sha", "reps", "n",
                           "refs", "ran_at", "gate", "watch", "natural_cells", "abort_refs_per_rep", "disputed",
                           "doubt_noted", "defect_family_pairs", "repairs", "usage", "typings", "outcomes"}
    assert record["n"] == 2 and record["reps"] == 2 and record["judge_version"] == 2
    assert record["prompt_revision"] and len(record["instructions_sha"]) == 12
    assert record["typings"] == [{"p01": "absent", "p39": "absent"}] * 2
    assert record["repairs"][0] == {"invalid_span": 2, "invalid_add": 0, "c2_repairs": 0, "repaired_absent": 2,
                                    "model_absent": 0, "invalid_counterpart": 0, "renames": ["agent:a->b"],
                                    "rename_suspects": [], "exempted": ["while"], "pair_error": 0, "singletons": 2}
    assert record["abort_refs_per_rep"] == [["p39"], ["p39"]]        # p39 is an uncontested covered pair
    # a probe set withholds pass/fail and reports its cells instead (DSH-45.3)
    assert record["gate"]["scope"] == "subset" and record["gate"]["passed"] is None
    assert record["gate"]["cells_on_this_set"]["covered_at_least_13_of_14"] is False
    assert record["gate"]["stated_pairs"] == [0, 0]


def test_a_full_set_still_passes_or_fails(labels, families):
    report = pc.gate(labels, [typings(labels)] * 3, families, scope="full")
    assert report["scope"] == "full" and report["passed"] is True and report["cells_on_this_set"] is None


def test_the_natural_cells_carry_their_own_rejecter_baseline(labels):
    """DSH-52: 93% on the natural subset is two pairs above a judge that rejects all 86, so the aggregate never
    travels without the baseline and without the cleared/leaked pair."""
    all_absent = pc.natural_cells(labels, {ref: "absent" for ref in labels})
    assert all_absent["n"] == 86 and all_absent["rejecter_baseline"] == "78/86"
    assert all_absent["faithful_cleared"] == "0/8" and all_absent["edge_over_rejecter_in_pairs"] == 0

    perfect = pc.natural_cells(labels, {
        ref: ("absent" if labels[ref][1].klass == "not_covered" else "one_step") for ref in labels})
    assert perfect["faithful_cleared"] == "8/8" and perfect["over_claims_leaked"] == "0/78"
    assert perfect["edge_over_rejecter_in_pairs"] == 8
