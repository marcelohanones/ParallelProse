import asyncio
import json
from collections import Counter

import pytest

from ParallelProse import theme_batches as tb
from ParallelProse.agent import ComposerAnswer, CorpusFinding

BATCH = """Theme 1: Crowds and the gaze

Thesis 1.1: Both books describe the crowd as a force that reshapes the self.
  Query 1.1a: How does a crowd influence the behavior of the people who belong to it?
  Query 1.1b: What does a person lose of himself in a crowd?

Thesis 1.2: Both books treat approval as a loss of self.
  Query 1.2a: What causes the pursuit of approval?

Theme 2: Time, memory & the self

Thesis 2.1: Both books tie experienced time to the self.
  Query 2.1a: How is time experienced by people?
"""


def answer(text):
    return ComposerAnswer(agreement=text, disagreement="none", unique_findings=[
        CorpusFinding(corpus_id="A", finding="a", quote="qa"),
        CorpusFinding(corpus_id="B", finding="b", quote="qb"),
    ])


def corpora_for(chunk_a="qa", chunk_b="qb"):
    return {
        "A": {"chunks": [f"some text {chunk_a} more text"], "label": "ok", "reason": "fine", "lineage": []},
        "B": {"chunks": [f"other text {chunk_b} more text"], "label": "ok", "reason": "fine", "lineage": []},
    }


def test_parse_batch_reads_themes_theses_and_queries():
    themes = tb.parse_batch(BATCH)

    assert [t.title for t in themes] == ["Crowds and the gaze", "Time, memory & the self"]
    first = themes[0]
    assert [th.number for th in first.theses] == [1, 2]
    assert [th.text for th in first.theses] == [
        "Both books describe the crowd as a force that reshapes the self.",
        "Both books treat approval as a loss of self.",
    ]
    assert first.theses[0].queries == [
        ("1.1a", "How does a crowd influence the behavior of the people who belong to it?", None),
        ("1.1b", "What does a person lose of himself in a crowd?", None),
    ]
    assert first.theses[1].queries == [("1.2a", "What causes the pursuit of approval?", None)]


def test_parse_batch_reads_side_tag_outside_the_query_text():
    themes = tb.parse_batch("Theme 1: T\nThesis 1.1: x\n  Query 1.1a[A]: a friend in a garden\n  Query 1.1b[B]: emancipation with others\n")

    assert themes[0].theses[0].queries == [
        ("1.1a", "a friend in a garden", "A"),
        ("1.1b", "emancipation with others", "B"),
    ]


@pytest.mark.parametrize("bad, message", [
    ("Thesis 1.1: orphan\n", "thesis before any theme"),
    ("Theme 1: T\n  Query 1.1a: q\n", "query before any thesis"),
    ("Theme 1: T\nThesis 2.1: x\n", "sits under theme 1"),
    ("Theme 1: T\nThesis 1.1: x\n  Query 2.1a: q\n", "sits under thesis 1.1"),
    ("Theme 1: T\nThesis 1.1: x\n  Query 1.2a: q\n", "sits under thesis 1.1"),
    ("Theme 1: T\nThesis 1.1: x\nvariants: stray\n", "not a theme, thesis or query"),
    ("Theme 1: T\nThesis 1.1: x\n  Query 1.1a[Z]: q\n", "unknown book \\[Z\\]"),
])
def test_parse_batch_rejects_malformed_lines(bad, message):
    with pytest.raises(ValueError, match=message):
        tb.parse_batch(bad)


def test_restrict_to_side_keeps_one_book_and_blanks_the_shared_fields():
    restricted = tb.restrict_to_side(answer("shared"), "B")

    assert restricted.agreement == "" and restricted.disagreement == ""
    assert [f.corpus_id for f in restricted.unique_findings] == ["B"]


def test_run_theme_batches_stores_both_sides_with_side_is_target(tmp_path, monkeypatch):
    monkeypatch.setattr(tb, "BATCHES_PATH", tmp_path)
    monkeypatch.setattr(tb, "QUERY_PAUSE_SECONDS", 0)

    async def fake_run_query(query):
        return {"answer": answer(f"agree on {query[:10]}"), "corpora": corpora_for()}

    monkeypatch.setattr(tb, "run_query", fake_run_query)
    batch_file = tmp_path / "themes.md"
    batch_file.write_text("Theme 1: Twins\n\nThesis 1.1: Both books treat a friend as a way out.\n"
                          "  Query 1.1a[A]: a friend in a garden\n"
                          "  Query 1.1b: a shared query\n")

    asyncio.run(tb.run_theme_batches(batch_file))

    stored = json.loads(next(tmp_path.glob("augustine_debord/*/theme-01*/thesis-01.json")).read_text())
    tagged_bite, shared_bite = stored["bites"]
    assert {f["corpus_id"] for f in tagged_bite["answer"]["unique_findings"]} == {"A", "B"}
    assert tagged_bite["side_is_target"] == {"A": True, "B": False}
    assert shared_bite["side_is_target"] == {"A": None, "B": None}


def test_flagged_words_drops_stopwords_and_short_words():
    assert tb.flagged_words("Why is the auditor not called on to relieve?") == ["auditor", "called", "relieve"]


def test_vocabulary_report_flags_a_word_missing_from_its_tagged_book_only():
    themes = tb.parse_batch("Theme 1: T\nThesis 1.1: x\n  Query 1.1a[A]: ponticianus and the garden\n")
    vocab = {"A": Counter({"garden": 3, "pontitianus": 4}), "B": Counter({"garden": 1})}

    report = tb.vocabulary_report(themes, vocab)

    assert '[A] "ponticianus" not found' in report
    assert 'Nearest: "pontitianus" (4)' in report
    assert "[B]" not in report  # untagged books are not checked for a tagged query


def test_vocabulary_report_checks_an_untagged_query_against_every_book():
    themes = tb.parse_batch("Theme 1: T\nThesis 1.1: x\n  Query 1.1a: xyzxyz in the garden\n")
    vocab = {"A": Counter({"garden": 3}), "B": Counter({"garden": 1})}

    report = tb.vocabulary_report(themes, vocab)

    assert '[A] "xyzxyz" not found' in report
    assert '[B] "xyzxyz" not found' in report


def test_vocabulary_report_says_so_when_nothing_is_flagged():
    themes = tb.parse_batch("Theme 1: T\nThesis 1.1: x\n  Query 1.1a: the garden\n")

    report = tb.vocabulary_report(themes, {"A": Counter({"garden": 1}), "B": Counter({"garden": 1})})

    assert report == "# Vocabulary check\n\nNo flagged words.\n"


def test_slugify_is_ascii_hyphenated_and_capped():
    assert tb.slugify("Time, memory & the self") == "time-memory-the-self"
    assert tb.slugify("Símbolo e Ação") == "simbolo-e-acao"
    assert len(tb.slugify("word " * 30)) <= 40
    assert not tb.slugify("word " * 30).endswith("-")


def test_run_theme_batches_builds_the_session_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(tb, "BATCHES_PATH", tmp_path)
    monkeypatch.setattr(tb, "QUERY_PAUSE_SECONDS", 0)
    queries_run = []

    async def fake_run_query(query):
        queries_run.append(query)
        return {"answer": answer(f"agree on {query[:10]}"), "corpora": corpora_for()}

    monkeypatch.setattr(tb, "run_query", fake_run_query)
    batch_file = tmp_path / "themes.md"
    batch_file.write_text(BATCH)

    out = asyncio.run(tb.run_theme_batches(batch_file))

    session = out.parent
    assert session.parent == tmp_path / "augustine_debord"
    assert out.name == f"{session.name}_thesis.json"  # synthesize() is disabled; consolidate_thesis_file is the output
    assert len(queries_run) == 4
    assert (session / "source.md").read_text() == BATCH
    manifest = json.loads((session / "manifest.json").read_text())
    assert manifest["source"] == "themes.md" and manifest["project"] == "augustine_debord"

    theme_dirs = sorted(p.name for p in session.iterdir() if p.is_dir())
    assert theme_dirs == ["theme-01_crowds-and-the-gaze", "theme-02_time-memory-the-self"]
    first_thesis = json.loads((session / theme_dirs[0] / "thesis-01.json").read_text())
    assert len(first_thesis["bites"]) == 2
    assert "synthesis" not in first_thesis
    assert first_thesis["bites"][0]["verified"] == {"A": True, "B": True}
    assert first_thesis["bites"][0]["retrieval"]["A"] == {"label": "ok", "reason": "fine", "lineage": []}

    consolidated = json.loads(out.read_text())
    assert consolidated["session"] == session.name
    assert set(consolidated["books"]) == {"A", "B"}
    assert [t["theme_folder"] for t in consolidated["theses"]] == [theme_dirs[0], theme_dirs[0], theme_dirs[1]]
    assert consolidated["theses"][0]["thesis"] == "Both books describe the crowd as a force that reshapes the self."
