import json

import pytest
from pydantic import ValidationError

from ParallelProse import idea_units as iu
from ParallelProse.idea_units import IdeaUnit, build_bites_index, load_idea_units


def convergence_unit(**overrides):
    base = dict(
        id="u01", type="convergence",
        mechanism_a="when X, Y happens, because Z", mechanism_b="when P, Q happens, because R",
        form_a="confession", form_b="thesis",
        shared_structure="a shared structure", divergence_axis="where the agent sits",
        falsification_test={"query": "a falsification query", "side": "A"},
        anchoring=["id1"],
    )
    base.update(overrides)
    return base


def single_voice_unit(**overrides):
    base = dict(
        id="u02", type="single_voice",
        mechanism_a="when X, Y happens, because Z", mechanism_b=None,
        form_a="scene", form_b=None,
        shared_structure="n/a", divergence_axis="n/a",
        falsification_single_voice="a query that would break the silence",
        anchoring=["id1"],
    )
    base.update(overrides)
    return base


def test_convergence_unit_is_valid():
    IdeaUnit.model_validate(convergence_unit())


def test_single_voice_unit_is_valid():
    IdeaUnit.model_validate(single_voice_unit())


@pytest.mark.parametrize("overrides", [
    {"mechanism_b": None},
    {"form_b": None},
])
def test_non_single_voice_rejects_a_missing_mechanism_or_form(overrides):
    with pytest.raises(ValidationError):
        IdeaUnit.model_validate(convergence_unit(**overrides))


def test_single_voice_rejects_both_mechanisms_set():
    with pytest.raises(ValidationError):
        IdeaUnit.model_validate(single_voice_unit(mechanism_b="also set", form_b="scene"))


def test_single_voice_rejects_neither_mechanism_set():
    with pytest.raises(ValidationError):
        IdeaUnit.model_validate(single_voice_unit(mechanism_a=None, form_a=None))


def test_single_voice_rejects_mismatched_form():
    with pytest.raises(ValidationError):
        IdeaUnit.model_validate(single_voice_unit(form_a=None))


def test_convergence_requires_falsification_test_not_single_voice_field():
    with pytest.raises(ValidationError):
        IdeaUnit.model_validate(convergence_unit(falsification_test=None, falsification_single_voice="x"))


def test_single_voice_requires_single_voice_field_not_falsification_test():
    with pytest.raises(ValidationError):
        IdeaUnit.model_validate(single_voice_unit(
            falsification_single_voice=None,
            falsification_test={"query": "q", "side": "A"}))


def test_build_bites_index_scans_every_witness_view_under_the_project(tmp_path):
    session = tmp_path / "2026-01-01_0000"
    session.mkdir()
    (session / "witness_view_augustine_debord_2026-01-01_0000.json").write_text(json.dumps({
        "session": "2026-01-01_0000", "project": "augustine_debord",
        "records": [
            {"bite_id": "id1", "corpus_id": "A", "quote": "a real quote"},
            {"bite_id": "id2", "corpus_id": "B", "quote": None},
        ],
    }))

    index = build_bites_index(tmp_path)

    assert index == {"id1": {"corpus_id": "A", "quote": "a real quote"}}


def test_load_idea_units_rejects_an_unknown_anchoring_id(tmp_path):
    path = tmp_path / "idea_units.json"
    path.write_text(json.dumps([convergence_unit(anchoring=["missing"])]))

    with pytest.raises(ValueError, match="unknown bite_id"):
        load_idea_units(path, bites_index={})


def test_load_idea_units_rejects_a_quote_not_in_the_book(tmp_path, monkeypatch):
    monkeypatch.setattr(iu, "book_paragraphs", lambda book: (["nothing like the quote at all"], [0]))
    path = tmp_path / "idea_units.json"
    path.write_text(json.dumps([convergence_unit(anchoring=["id1"])]))

    with pytest.raises(ValueError, match="not found in book"):
        load_idea_units(path, bites_index={"id1": {"corpus_id": "A", "quote": "a real quote"}})


def test_load_idea_units_rejects_a_repeated_id(tmp_path, monkeypatch):
    monkeypatch.setattr(iu, "book_paragraphs", lambda book: (["a real quote"], [0]))
    path = tmp_path / "idea_units.json"
    path.write_text(json.dumps([convergence_unit(id="u01"), convergence_unit(id="u01")]))

    with pytest.raises(ValueError, match="id used 2 times"):
        load_idea_units(path, bites_index={"id1": {"corpus_id": "A", "quote": "a real quote"}})


def test_load_idea_units_accepts_a_good_file_and_returns_no_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(iu, "book_paragraphs", lambda book: (["a real quote"], [0]))
    path = tmp_path / "idea_units.json"
    path.write_text(json.dumps([convergence_unit(anchoring=["id1"])]))

    units, flags = load_idea_units(path, bites_index={"id1": {"corpus_id": "A", "quote": "a real quote"}})

    assert len(units) == 1 and flags == []


def test_a_one_sided_unit_borrowing_the_other_books_word_is_flagged_not_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(iu, "book_paragraphs", lambda book: (["a real quote"], [0]))
    path = tmp_path / "idea_units.json"
    path.write_text(json.dumps([convergence_unit(
        anchoring=["id1"], mechanism_a="the spectacle governs this", mechanism_b="and so does Z")]))

    units, flags = load_idea_units(path, bites_index={
        "id1": {"corpus_id": "A", "quote": "a real quote"}})

    assert len(units) == 1
    assert len(flags) == 1 and "spectacle" in flags[0]


def test_a_genuinely_cross_book_unit_is_never_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(iu, "book_paragraphs", lambda book: (["a real quote"], [0]))
    path = tmp_path / "idea_units.json"
    path.write_text(json.dumps([convergence_unit(
        anchoring=["id1", "id2"], mechanism_a="the spectacle governs this", mechanism_b="and the soul resists")]))

    units, flags = load_idea_units(path, bites_index={
        "id1": {"corpus_id": "A", "quote": "a real quote"},
        "id2": {"corpus_id": "B", "quote": "a real quote"},
    })

    assert flags == []
