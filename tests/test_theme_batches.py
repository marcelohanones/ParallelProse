import asyncio
import json

import pytest

from ParallelProse import theme_batches as tb
from ParallelProse.agent import ComposerAnswer, CorpusFinding
from ParallelProse.synthesis import Synthesis, UncoveredAngle

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
        ("1.1a", "How does a crowd influence the behavior of the people who belong to it?"),
        ("1.1b", "What does a person lose of himself in a crowd?"),
    ]
    assert first.theses[1].queries == [("1.2a", "What causes the pursuit of approval?")]


@pytest.mark.parametrize("bad, message", [
    ("Thesis 1.1: orphan\n", "thesis before any theme"),
    ("Theme 1: T\n  Query 1.1a: q\n", "query before any thesis"),
    ("Theme 1: T\nThesis 2.1: x\n", "sits under theme 1"),
    ("Theme 1: T\nThesis 1.1: x\n  Query 2.1a: q\n", "sits under thesis 1.1"),
    ("Theme 1: T\nThesis 1.1: x\n  Query 1.2a: q\n", "sits under thesis 1.1"),
    ("Theme 1: T\nThesis 1.1: x\nvariants: stray\n", "not a theme, thesis or query"),
])
def test_parse_batch_rejects_malformed_lines(bad, message):
    with pytest.raises(ValueError, match=message):
        tb.parse_batch(bad)


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
        return {"answer": answer(f"agree on {query[:10]}")}

    monkeypatch.setattr(tb, "run_query", fake_run_query)
    monkeypatch.setattr(tb, "synthesize", lambda theme, thesis, bites: Synthesis(
        claims=[], uncovered_angle=UncoveredAngle(angle="x", checked_bites=[q for q, _ in bites]),
        candidate_query=None))
    batch_file = tmp_path / "themes.md"
    batch_file.write_text(BATCH)

    out = asyncio.run(tb.run_theme_batches(batch_file))

    session = out.parent
    assert session.parent == tmp_path / "augustine_debord"
    assert out.name == f"{session.name}_synthesis.json"
    assert len(queries_run) == 4
    assert (session / "source.md").read_text() == BATCH
    manifest = json.loads((session / "manifest.json").read_text())
    assert manifest["source"] == "themes.md" and manifest["project"] == "augustine_debord"

    theme_dirs = sorted(p.name for p in session.iterdir() if p.is_dir())
    assert theme_dirs == ["theme-01_crowds-and-the-gaze", "theme-02_time-memory-the-self"]
    first_thesis = json.loads((session / theme_dirs[0] / "thesis-01.json").read_text())
    assert len(first_thesis["bites"]) == 2
    assert first_thesis["synthesis"]["uncovered_angle"]["checked_bites"] == [
        "How does a crowd influence the behavior of the people who belong to it?",
        "What does a person lose of himself in a crowd?",
    ]

    consolidated = json.loads(out.read_text())
    assert [t["folder"] for t in consolidated["themes"]] == theme_dirs
    assert consolidated["themes"][1]["theses"][0]["synthesis"] is not None
