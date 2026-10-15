"""Scores the faithfulness judge against the 140 hand labels (roadmap item 48, sections 7, 10 and 11).

The bar is a 3x3 typing matrix, never a percentage: each reference class has exactly one correct typing, and the two
accuracies are reported with their floors beside them because they can move opposite to the matrix (a passing matrix
can score 83.6% strict, below the 86.4% a judge that rejects everything gets). The scoring core here is pure -- it
takes labels and typings -- so the cells, the floors and the gate are tested without an API call; `run_round` is the
thin part that spends money.

    label class        correct typing   meaning
    covered            stated           every segment `stated`
    covered_one_step   one_step         no segment `absent`, at least one `one_step`
    not_covered        absent           at least one segment `absent`
"""

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ParallelProse.catalog import DATA_DIR
from ParallelProse.pair_labels import PairLabel, parse_sheet

EVAL_DIR = DATA_DIR / "eval"
SHEETS = {"natural": "faithfulness_pair_labels_2.md", "mined": "faithfulness_pair_labels_mined.md",
          "constructed_1": "faithfulness_pair_labels_constructed.md",
          "constructed_2": "faithfulness_pair_labels_constructed_2.md"}
FAMILIES_PATH = EVAL_DIR / "faithfulness_pair_families.json"
WATCH_PATH = EVAL_DIR / "faithfulness_watch_refs.json"

DISPUTED = ("d06", "d07", "d08", "d09", "d11")          # contested labels: reported, never gated (M1/M4)
DOUBT_NOTED = ("p13", "p38", "m07", "m09", "m20", "c09", "m22", "p65")   # decided labels, inside the gate
# Section 10: the 13 pairs the dry-run reads before the round is paid for -- the 7 watch refs, the three pure subject
# substitutions, one added means, one long multi-clause claim, one quote-heavy sentence.
DRY_RUN_REFS = ("c03", "c14", "m27", "p39", "p43", "p68", "p82",      # the watch column
                "m10", "p19", "p72",                                  # pure subject substitutions, the gated family
                "p62",                                                # an added means
                "p31", "p86",                                         # a long multi-clause claim, a quote-heavy sentence
                "p07",                                                # claim subject "It", resolved by the sentence: the
                                                                      # false-negative probe for the agent rule (DSH-33)
                "c09",                                                # a one_step pair with a recorded doubt
                "p36",                                                # generalization: the family a lexical check cannot see
                # Widened for v5 (DSH-43): fitting a mechanism to 8 failing positives is how v2 and v4 both swung.
                # Seven more `one_step` pairs (constructed_2's own, the ones review left as one_step) and two mined
                # near-copy positives.
                "d01", "d02", "d03", "d04", "d05", "d10", "d12", "m02", "m13",
                # Modality-negative regression probes (DSH-49): both are `not_covered` on *content* words, not on
                # mood, so an example that teaches "stance without added content is a rendering" must not flip them.
                "p48", "p53",
                # Arm C (DSH-55.3): the seven failing `one_step` pairs the 27 did not carry, so all 11 of the full
                # run's misses are measured...
                "c02", "c06", "c07", "m07", "m20", "p13", "p38",
                # ...and six consequence-heavy `not_covered` pairs as the regression, because rule 4 now asks about
                # support rather than presence, and that is the direction that leaks.
                "p61", "p66", "p45", "p69", "p32", "m05")

CORRECT_TYPING = {"covered": "stated", "covered_one_step": "one_step", "not_covered": "absent"}
FLOORS = {"strict": 121, "lenient": 96}                 # a judge that rejects every one of the 140 pairs


def load_labels(sheet_dir: Path = EVAL_DIR) -> dict[str, tuple[str, PairLabel]]:
    """ref -> (origin, label), over the four sheets that make up the 140."""
    labels = {}
    for origin, name in SHEETS.items():
        for label in parse_sheet((sheet_dir / name).read_text()):
            labels[label.ref] = (origin, label)
    return labels


def typing_of(outcome) -> str:
    """The judge's typing of one pair, from its relations: the three values the matrix compares against."""
    if outcome.strict:
        return "stated"
    return "one_step" if outcome.lenient else "absent"


def rows_of(labels: dict[str, tuple[str, PairLabel]], ref: str) -> str:
    """Which matrix row a ref belongs to: the disputed covered pairs are their own row (M1)."""
    klass = labels[ref][1].klass
    return "covered_disputed" if (klass == "covered" and ref in DISPUTED) else klass


def matrix(labels: dict[str, tuple[str, PairLabel]], typings: dict[str, str]) -> dict:
    """The 3x3 (plus the disputed row): per row, how many pairs got each typing, and how many got the correct one."""
    cells: dict[str, Counter] = {}
    for ref, typing in typings.items():
        cells.setdefault(rows_of(labels, ref), Counter())[typing] += 1
    report = {}
    for row, counts in cells.items():
        correct = CORRECT_TYPING.get(row.replace("_disputed", ""))
        report[row] = {"n": sum(counts.values()), "typings": dict(sorted(counts.items())),
                       "correct": counts.get(correct, 0) if correct else None}
    return report


def accuracies(labels: dict[str, tuple[str, PairLabel]], typings: dict[str, str]) -> dict:
    """Strict and lenient accuracy over the pairs scored, with the floor a constant rejecter reaches on all 140.
    Reported, never a gate: see the module docstring."""
    out = {}
    for view, passing in (("strict", {"stated"}), ("lenient", {"stated", "one_step"})):
        agree = 0
        for ref, typing in typings.items():
            klass = labels[ref][1].klass
            should_pass = klass == "covered" or (view == "lenient" and klass == "covered_one_step")
            if (typing in passing) == should_pass:
                agree += 1
        out[view] = {"agree": agree, "of": len(typings), "floor_on_140": FLOORS[view]}
    return out


def gate(labels, per_rep: list[dict[str, str]], families: dict, scope: str = "full") -> dict:
    """The bar of section 7, cell by cell, over however many repetitions were run. Every cell must hold in *each*
    repetition; the `not_covered` union is counted across them, because a pair the instrument sometimes certifies is
    still a pair it certifies."""
    gated_agent = [ref for ref, row in families["pairs"].items()
                   if row["gate"] and row["family"] == "agent_subject"]
    reps = [{"matrix": matrix(labels, typings), "accuracies": accuracies(labels, typings)} for typings in per_rep]

    def cell(row, key):
        return [rep["matrix"].get(row, {}).get(key, 0) for rep in reps]

    covered = cell("covered", "correct")
    one_step_correct = cell("covered_one_step", "correct")
    one_step_leak = [rep["matrix"].get("covered_one_step", {}).get("typings", {}).get("stated", 0) for rep in reps]
    # The >=22 floor is a non-regression line against the v1 instrument, which passed 22 of these 25 pairs with no
    # middle typing at all -- so its v2 equivalent is "passes lenient", i.e. typed one_step *or* stated, never
    # `absent`. Reading it as "typed one_step" would contradict the leak cell below: with 4 pairs typed stated, at
    # most 21 of 25 can be typed one_step.
    one_step_lenient = [c + leak for c, leak in zip(one_step_correct, one_step_leak)]
    not_covered = cell("not_covered", "correct")
    false_pass_union = len({ref for typings in per_rep for ref, typing in typings.items()
                            if labels[ref][1].klass == "not_covered" and typing != "absent"})
    agent_leaks = sorted({ref for typings in per_rep for ref in gated_agent
                          if typings.get(ref, "absent") != "absent"})
    n_covered = reps[0]["matrix"].get("covered", {}).get("n", 0)
    unstable = sorted(ref for ref in per_rep[0] if len({typings.get(ref) for typings in per_rep}) > 1)

    # M7 (2026-10-14, Markim): the headline view is lenient, so the positive cell is the 39 uncontested positives
    # (14 `covered` + 25 `covered_one_step`) typed anything but `absent`, and the `stated`/`one_step` boundary stops
    # being a gate. 36 is the non-regression floor: the v1 instrument passed 14 of those covered and 22 of the 25
    # one_step pairs. The `covered` row keeps a loose guard of its own -- a covered pair typed `absent` is a hard
    # false negative, not a boundary call, and it is what the abort rule fires on -- and the negative cell is
    # unchanged, which is where the item's value is.
    positives_non_absent = [sum(1 for ref, typing in typings.items()
                                if rows_of(labels, ref) in ("covered", "covered_one_step") and typing != "absent")
                            for typings in per_rep]
    covered_non_absent = [sum(1 for ref, typing in typings.items()
                              if rows_of(labels, ref) == "covered" and typing != "absent") for typings in per_rep]
    one_step_non_absent = [sum(1 for ref, typing in typings.items()
                               if rows_of(labels, ref) == "covered_one_step" and typing != "absent")
                           for typings in per_rep]
    model_absent_counts = [sum(1 for typing in typings.values() if typing == "absent") for typings in per_rep]
    covered_absent = [sum(1 for ref, typing in typings.items()
                          if rows_of(labels, ref) == "covered" and typing == "absent") for typings in per_rep]
    stated_typings = [sum(1 for typing in typings.values() if typing == "stated") for typings in per_rep]

    # The re-scope, [Markim] 2026-10-14 after the full 140 and three failed arms (v4 prose, arm B examples, arm C's
    # support framing: 2 of 11 cleared and a covered pair lost). The gate scores what this frame can represent --
    # does the claim state content the sentence lacks -- and `covered_one_step` becomes a reported tolerance zone,
    # because that class encodes human tolerance for an abstraction step and D1 reads the sentence literally. It
    # rests on the validity note that was in the spec before the run: 19 of the 39 positives are constructed and 12
    # mined, against a production distribution that is 91% negative. Conditions attached (DSH-56): the bar cannot be
    # met by a rejecter (hence the model_absent cap), the zone is reported with its composition, and the natural-pair
    # figures travel with their own rejecter baseline.
    model_absent_cap = 120
    checks = {
        "covered_at_least_13_of_14": all(c >= 13 for c in covered_non_absent),
        "not_a_rejecter_model_absent_at_most_120": all(c <= model_absent_cap for c in model_absent_counts),
        # Zero, not one: the abort rule already stops a round at the first covered pair typed `absent`, so a gate
        # that tolerated one would be weaker than the gate that precedes it.

        "not_covered_at_least_82": all(c >= 82 for c in not_covered),
        "not_covered_union_at_most_16": false_pass_union <= 16,
        "zero_false_pass_on_gated_agent_refs": not agent_leaks,
        "stability_at_most_5_unstable": len(unstable) <= 5,
    }
    # A probe set is not a round (DSH-45.3): `not_covered_at_least_82` on 7 pairs is false by construction, so a
    # subset reports rates and withholds pass/fail. Only a full 140 can pass or fail the bar.
    stated_pairs = [sum(1 for ref, typing in typings.items() if typing == "stated") for typings in per_rep]
    return {"scope": scope, "passed": all(checks.values()) if scope == "full" else None,
            "checks": checks if scope == "full" else {k: None for k in checks},
            "cells_on_this_set": checks if scope != "full" else None,
            "stated_pairs": stated_pairs,
            "positives_non_absent": positives_non_absent, "covered_absent": covered_absent,
            "covered_correct_stated": covered, "one_step_correct": one_step_correct,
            "one_step_lenient": one_step_lenient, "one_step_strict_leak": one_step_leak,
            "not_covered_correct": not_covered, "not_covered_false_pass_union": false_pass_union,
            "gated_agent_refs": gated_agent, "gated_agent_leaks": agent_leaks,
            "covered_non_absent": covered_non_absent,
            # The tolerance zone: reported every round, never gated, and with its composition -- the full-140 run's
            # 11 misses were ~8 implied consequence/means, ~2 subject generalizations (counterpart recall) and ~2
            # other (DSH-54).
            "tolerance_zone_one_step_non_absent": one_step_non_absent,
            "model_absent": model_absent_counts, "model_absent_cap": model_absent_cap,
            # Markim's fourth condition on M7: a round where the judge never types `stated` makes the strict second
            # column vacuous -- it would report the label going unused, not the text being faithful. Say so here.
            "stated_typings": stated_typings,
            "strict_column_is_vacuous": all(c == 0 for c in stated_typings),
            "unstable": unstable, "reps": reps}


def natural_cells(labels, typings: dict[str, str]) -> dict:
    """The production distribution, reported with the baseline that makes it readable (DSH-52): the 86 natural pairs
    are 91% `not_covered`, so a judge that rejects every one of them already scores 78/86 = 90.7%. The pair that
    carries information is "faithful pairs cleared" against "over-claims leaked", never the aggregate alone."""
    natural = [ref for ref, (origin, _) in labels.items() if origin == "natural" and ref in typings]
    positives = [ref for ref in natural if labels[ref][1].klass in ("covered", "covered_one_step")]
    negatives = [ref for ref in natural if labels[ref][1].klass == "not_covered"]
    cleared = sum(1 for ref in positives if typings[ref] != "absent")
    leaked = sum(1 for ref in negatives if typings[ref] != "absent")
    agree = cleared + (len(negatives) - leaked)
    return {"n": len(natural), "faithful_cleared": f"{cleared}/{len(positives)}",
            "over_claims_leaked": f"{leaked}/{len(negatives)}",
            "agreement": f"{agree}/{len(natural)}",
            "rejecter_baseline": f"{len(negatives)}/{len(natural)}",
            "edge_over_rejecter_in_pairs": agree - len(negatives)}


def watch_report(per_rep: list[dict[str, str]], watch: dict) -> dict:
    """The paraphrase column (section 6.4), pair by pair: a miss here reads as the relation collapsing to a lexical
    reading, which is a different diagnosis from a weak judge."""
    refs = sorted(watch["watch"])
    return {ref: [typings.get(ref) for typings in per_rep] for ref in refs}


def abort(labels, typings: dict[str, str]) -> list[str]:
    """Threshold 1 (section 11): one uncontested `covered` pair typed `absent` makes the round unreportable. Under
    M7 that is the real hard error -- a positive pair the judge says adds something -- while `stated` versus
    `one_step` on such a pair is a boundary the reference itself does not reproduce. The calls still finish: the
    negative-side diagnostics are what a revision needs."""
    return sorted(ref for ref, typing in typings.items()
                  if rows_of(labels, ref) == "covered" and typing == "absent")


def run_round(refs: list[str] | None = None, reps: int = 3, out_dir: Path = EVAL_DIR, tag: str = "round") -> Path:
    """The part that spends money: judge every ref, `reps` times, and write the record. Imported here so that the
    scoring core above stays importable without opening a client."""
    from ParallelProse.judges import (DEFECT_FAMILIES, JUDGE_MODEL, JUDGE_VERSION, PAIR_INSTRUCTIONS,
                                      PROMPT_REVISION, judge_pair_detail)
    from ParallelProse.run_record import RoleUsageTracker

    labels = load_labels()
    families = json.loads(FAMILIES_PATH.read_text())
    watch = json.loads(WATCH_PATH.read_text())
    chosen = list(refs) if refs else sorted(labels)

    per_rep, outcomes_by_rep, usage = [], [], []
    for _ in range(reps):
        tracker = RoleUsageTracker()
        outcomes = {ref: judge_pair_detail(labels[ref][1].claim, labels[ref][1].sentence, callbacks=[tracker])
                    for ref in chosen}
        per_rep.append({ref: typing_of(outcome) for ref, outcome in outcomes.items()})
        # `repaired_absent` is a property, not a field, so asdict drops it -- and the first v4 dry-run was lost to
        # exactly that after the calls were paid for. It is written explicitly, and test_pair_calibration covers the
        # assembly with a stubbed judge so the record path is never exercised for the first time by a paid run.
        outcomes_by_rep.append({ref: {**asdict(outcome), "repaired_absent": outcome.repaired_absent}
                                for ref, outcome in outcomes.items()})
        usage.append(tracker.as_dict())

    record = {
        "what": tag, "model": JUDGE_MODEL, "judge_version": JUDGE_VERSION,
        # The prompt's own identity, so two records can never be compared as if one instruction block produced both
        # (DSH-45.1): judge_version is the data era, prompt_revision and instructions_sha are the wording.
        "prompt_revision": PROMPT_REVISION,
        "instructions_sha": hashlib.sha256(PAIR_INSTRUCTIONS.encode()).hexdigest()[:12],
        "reps": reps,
        "n": len(chosen), "refs": chosen, "ran_at": f"{datetime.now():%Y-%m-%d %H:%M}",
        "gate": gate(labels, per_rep, families, scope="full" if len(chosen) >= 140 else "subset"),
        "watch": watch_report(per_rep, watch),
        "natural_cells": [natural_cells(labels, typings) for typings in per_rep],
        "abort_refs_per_rep": [abort(labels, typings) for typings in per_rep],
        "disputed": {ref: [typings.get(ref) for typings in per_rep] for ref in DISPUTED if ref in chosen},
        "doubt_noted": {ref: [typings.get(ref) for typings in per_rep] for ref in DOUBT_NOTED if ref in chosen},
        # Code repair and model judgement are counted apart (DSH-15/DSH-35): a C2 firing on a positive pair is an
        # instrument bug -- it says fix the code, not the prompt -- and `repaired_absent` is how many `absent`s code
        # put there. `exempted` lists the droppable connectives that actually fired, so that list stays evidence-driven.
        # The producer item's metric (DSH-63): pairs carrying at least one item of a defect family, per repetition.
        "defect_family_pairs": [{family: sum(1 for o in rep.values() if family in o["additions"])
                                 for family in DEFECT_FAMILIES} for rep in outcomes_by_rep],
        "repairs": [{"invalid_span": sum(o["invalid_span"] for o in rep.values()),
                     "invalid_add": sum(o["invalid_add"] for o in rep.values()),
                     "c2_repairs": sum(o["c2_repairs"] for o in rep.values()),
                     "repaired_absent": sum(o["repaired_absent"] for o in rep.values()),
                     "model_absent": sum(1 for o in rep.values()
                                         if "absent" in o["raw_relations"]),
                     "invalid_counterpart": sum(o["invalid_counterpart"] for o in rep.values()),
                     "renames": sorted({r for o in rep.values() for r in o["renames"]}),
                     "rename_suspects": sorted({s for o in rep.values() for s in o["rename_suspects"]}),
                     "exempted": sorted({e for o in rep.values() for e in o["exempted_terms"]}),
                     "pair_error": sum(o["pair_error"] is not None for o in rep.values()),
                     "singletons": sum(o["singleton"] for o in rep.values())} for rep in outcomes_by_rep],
        "usage": usage,
        "typings": per_rep,
        "outcomes": outcomes_by_rep,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"item48_{tag}_{JUDGE_MODEL}_{datetime.now():%Y-%m-%d_%H%M}.json"
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False))
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the faithfulness judge against the 140 hand labels.")
    parser.add_argument("--dry-run", action="store_true", help="the 13 pairs of section 10 instead of all 140")
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--tag", default=None)
    args = parser.parse_args()
    refs = list(DRY_RUN_REFS) if args.dry_run else None
    tag = args.tag or ("dryrun" if args.dry_run else "round")
    path = run_round(refs=refs, reps=args.reps, tag=tag)
    record = json.loads(path.read_text())
    print(f"{path.name}: {record['n']} pairs x {record['reps']} reps on {record['model']}")
    print(json.dumps({"gate": record["gate"]["checks"], "repairs": record["repairs"],
                      "abort": record["abort_refs_per_rep"]}, indent=1))


if __name__ == "__main__":
    main()
