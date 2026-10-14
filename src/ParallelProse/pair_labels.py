"""The hand labels on (claim, sentence) pairs -- the calibration set the faithfulness judge has never had (item 47).

The sheet (`data/eval/faithfulness_pair_labels*.md`) is read by a person and by this module, so its format is the
contract: one `### <ref>` block per pair (`p07` for a natural pair, `c07` for a constructed one), then `- claim:`,
`- sentence:`, `- human_faithful:`, `- lenient:` and `- note:` lines; any other `- key:` line is ignored. Two fields encode three classes of how far the sentence covers the claim:

    human_faithful   lenient   class
    true             blank     covered            the sentence states everything the claim states
    false            true      covered_one_step   the same content, reworded or one level more abstract
    false            false     not_covered        the claim states something the sentence does not
    null             blank     undecided          out of every count

A `false` with a blank `lenient` is *unclassified*, not "no step": the field is explicit so that "looked and found no
step" stays distinguishable from "did not look". Anything above the first `### <ref>` block is header and is ignored.
"""

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ParallelProse.catalog import DATA_DIR

EVAL_DIR = DATA_DIR / "eval"
MAP_PATH = EVAL_DIR / "faithfulness_pair_labels_map.json"
CLASSES = ("covered", "covered_one_step", "not_covered", "undecided")


@dataclass(frozen=True)
class PairLabel:
    ref: str
    claim: str
    sentence: str
    human_faithful: str  # "true" | "false" | "null" | "" (not labelled yet), lowercased
    lenient: str  # "true" | "false" | ""
    note: str

    @property
    def klass(self) -> str | None:
        """The class the two fields encode, or None while they are blank or contradict each other."""
        hf, le = self.human_faithful, self.lenient
        if hf == "true" and not le:
            return "covered"
        if hf == "false" and le == "true":
            return "covered_one_step"
        if hf == "false" and le == "false":
            return "not_covered"
        if hf == "null" and not le:
            return "undecided"
        return None


def parse_sheet(text: str) -> list[PairLabel]:
    """Every `### pNN` block, in file order. A missing `human_faithful`, `lenient` or `note` line reads as blank, so a
    sheet from before the `lenient` field still parses -- and then reports every `false` as unclassified."""
    first = re.search(r"^### [a-z]\d+$", text, re.MULTILINE)
    if first is None:
        return []
    labels = []
    for block in re.split(r"\n(?=### [a-z]\d+\n)", text[first.start():]):
        ref = block.split("\n", 1)[0][4:].strip()

        def line(field: str) -> str | None:
            found = re.search(rf"^- {field}:[ ]*(.*)$", block, re.MULTILINE)
            return found.group(1).strip() if found else None

        claim, sentence = line("claim"), line("sentence")
        if claim is None or sentence is None:
            raise ValueError(f"{ref}: the block has no '- claim:' or no '- sentence:' line")
        note = block.split("\n- note:", 1)[1].strip() if "\n- note:" in block else ""
        labels.append(PairLabel(ref, claim, sentence, (line("human_faithful") or "").lower(),
                                (line("lenient") or "").lower(), note))
    return labels


def load_expected(map_path: Path = MAP_PATH) -> dict[str, tuple[str, str]]:
    """ref -> (claim, sentence) as the sheet was generated, so a label cannot end up on an edited pair."""
    return {p["ref"]: (p["claim"], p["sentence"]) for p in json.loads(map_path.read_text())["pairs"]}


def _label_problems(label: PairLabel) -> list[str]:
    hf, le = label.human_faithful, label.lenient
    problems = []
    if not label.claim:
        problems.append("claim is empty")
    if not label.sentence:
        problems.append("sentence is empty")
    if hf == "":
        problems.append("not labelled")
    elif hf not in ("true", "false", "null"):
        problems.append(f"human_faithful is {hf!r}, not true/false/null")
    if le not in ("", "true", "false"):
        problems.append(f"lenient is {le!r}, not true/false")
    elif hf == "false" and le == "":
        problems.append("false with a blank lenient: not classified yet")
    elif hf in ("true", "null") and le != "":
        problems.append(f"lenient is filled on a {hf} pair; it applies only to false")
    return problems


def sheet_problems(labels: list[PairLabel], expected: dict[str, tuple[str, str]] | None = None) -> list[str]:
    """Everything that stops the sheet from being a calibration set, one line each, ref first."""
    problems = []
    for ref, count in Counter(label.ref for label in labels).items():
        if count > 1:
            problems.append(f"{ref}: appears {count} times")
    if expected is not None:
        have = {label.ref for label in labels}
        problems += [f"{ref}: missing from the sheet" for ref in sorted(set(expected) - have)]
        problems += [f"{ref}: not a pair of this sheet" for ref in sorted(have - set(expected))]
        for label in labels:
            if label.ref in expected and (label.claim, label.sentence) != expected[label.ref]:
                problems.append(f"{label.ref}: claim or sentence was edited")
    for label in labels:
        problems += [f"{label.ref}: {problem}" for problem in _label_problems(label)]
    return problems


def load_pair_labels(path: Path, expected: dict[str, tuple[str, str]] | None = None) -> list[PairLabel]:
    """A sheet that is complete and consistent, or a ValueError naming every problem at once."""
    labels = parse_sheet(Path(path).read_text())
    problems = sheet_problems(labels, expected)
    if problems:
        raise ValueError(f"{Path(path).name}: {len(problems)} problem(s)\n" + "\n".join(problems))
    return labels


def reference(labels: list[PairLabel], view: Literal["strict", "lenient"]) -> dict[str, bool]:
    """ref -> should this pair pass. `strict` passes only covered; `lenient` also passes covered_one_step. Undecided
    and unclassified pairs are left out, so a view never counts a pair nobody decided."""
    passing = {"covered"} | ({"covered_one_step"} if view == "lenient" else set())
    return {label.ref: label.klass in passing for label in labels if label.klass not in (None, "undecided")}


def class_counts(labels: list[PairLabel]) -> Counter:
    return Counter(label.klass or "unclassified" for label in labels)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check a faithfulness pair-label sheet and count its classes.")
    parser.add_argument("sheet", type=Path)
    args = parser.parse_args()
    labels = parse_sheet(args.sheet.read_text())
    problems = sheet_problems(labels, load_expected())
    if problems:
        print(f"{args.sheet.name}: {len(problems)} problem(s)")
        print("\n".join(problems))
        raise SystemExit(1)
    counts = class_counts(labels)
    print(f"{args.sheet.name}: {len(labels)} pairs, complete and consistent")
    for name in CLASSES:
        print(f"  {name:18s} {counts.get(name, 0):3d}")
    print(f"  strict passes {sum(reference(labels, 'strict').values())}, "
          f"lenient passes {sum(reference(labels, 'lenient').values())}, "
          f"of {len(reference(labels, 'strict'))} decided")


if __name__ == "__main__":
    main()
