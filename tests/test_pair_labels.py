import pytest

from ParallelProse import pair_labels as pl


def sheet(*pairs):
    """A sheet text: a header, then one block per (ref, hf, le[, note]) tuple."""
    out = "# Faithfulness labels\n\nsome header text, with a - claim: line that is not a block\n"
    for ref, hf, le, *note in pairs:
        out += (f"\n### {ref}\n- claim: claim {ref}\n- sentence: sentence {ref}\n- human_faithful: {hf}\n"
                f"- lenient: {le}\n- note: {note[0] if note else ''}\n")
    return out


def by_ref(text):
    return {label.ref: label for label in pl.parse_sheet(text)}


def test_two_fields_encode_three_classes_and_the_undecided_one():
    labels = by_ref(sheet(("p01", "true", ""), ("p02", "false", "true"), ("p03", "false", "false"),
                          ("p04", "null", "")))

    assert [labels[ref].klass for ref in ("p01", "p02", "p03", "p04")] == [
        "covered", "covered_one_step", "not_covered", "undecided"]


def test_a_false_with_a_blank_lenient_is_unclassified_not_not_covered():
    labels = pl.parse_sheet(sheet(("p01", "false", "")))

    assert labels[0].klass is None
    assert pl.sheet_problems(labels) == ["p01: false with a blank lenient: not classified yet"]


def test_lenient_belongs_only_to_false_pairs():
    problems = pl.sheet_problems(pl.parse_sheet(sheet(("p01", "true", "false"), ("p02", "null", "true"))))

    assert problems == ["p01: lenient is filled on a true pair; it applies only to false",
                        "p02: lenient is filled on a null pair; it applies only to false"]


def test_blank_and_invalid_values_are_reported_by_ref():
    problems = pl.sheet_problems(pl.parse_sheet(sheet(("p01", "", ""), ("p02", "maybe", ""), ("p03", "false", "yes"))))

    assert problems == ["p01: not labelled",
                        "p02: human_faithful is 'maybe', not true/false/null",
                        "p03: lenient is 'yes', not true/false"]


def test_an_empty_claim_is_a_problem_even_when_the_pair_is_labelled():
    text = "### c01\n- claim:\n- sentence: s\n- human_faithful: true\n- lenient:\n- note:\n"

    assert pl.sheet_problems(pl.parse_sheet(text)) == ["c01: claim is empty"]


def test_values_are_read_case_insensitively():
    assert by_ref(sheet(("p01", "True", ""), ("p02", "FALSE", "True")))["p02"].klass == "covered_one_step"


def test_a_multiline_note_is_kept_whole():
    text = sheet(("p01", "false", "false", "first line\nsecond line")) + sheet(("p02", "true", ""))[
        sheet(("p02", "true", "")).index("\n### p02"):]

    assert by_ref(text)["p01"].note == "first line\nsecond line"
    assert by_ref(text)["p02"].klass == "covered"


def test_a_sheet_without_lenient_lines_reads_every_false_as_unclassified():
    old = "### p01\n- claim: c\n- sentence: s\n- human_faithful: false\n"

    assert pl.parse_sheet(old)[0].lenient == ""
    assert pl.sheet_problems(pl.parse_sheet(old)) == ["p01: false with a blank lenient: not classified yet"]


def test_a_block_without_claim_or_sentence_is_rejected():
    with pytest.raises(ValueError, match="p01"):
        pl.parse_sheet("### p01\n- human_faithful: true\n")


def test_the_expected_pairs_catch_a_missing_repeated_and_edited_pair():
    expected = {"p01": ("claim p01", "sentence p01"), "p02": ("claim p02", "sentence p02"),
                "p03": ("claim p03", "sentence p03")}
    text = sheet(("p01", "true", ""), ("p01", "true", ""), ("p03", "true", "")).replace("claim p03", "claim edited")

    problems = pl.sheet_problems(pl.parse_sheet(text), expected)

    assert "p01: appears 2 times" in problems
    assert "p02: missing from the sheet" in problems
    assert "p03: claim or sentence was edited" in problems


def test_load_raises_with_every_problem_and_returns_a_complete_sheet(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text(sheet(("p01", "", ""), ("p02", "false", "")))
    good = tmp_path / "good.md"
    good.write_text(sheet(("p01", "true", ""), ("p02", "false", "false")))

    with pytest.raises(ValueError, match=r"2 problem\(s\)"):
        pl.load_pair_labels(bad)
    assert [label.klass for label in pl.load_pair_labels(good)] == ["covered", "not_covered"]


def test_the_two_references_differ_only_on_the_one_step_class():
    labels = pl.parse_sheet(sheet(("p01", "true", ""), ("p02", "false", "true"), ("p03", "false", "false"),
                                  ("p04", "null", "")))

    assert pl.reference(labels, "strict") == {"p01": True, "p02": False, "p03": False}
    assert pl.reference(labels, "lenient") == {"p01": True, "p02": True, "p03": False}  # p04 is in neither
