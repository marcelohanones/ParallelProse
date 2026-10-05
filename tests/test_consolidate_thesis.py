import json

from ParallelProse.consolidate_thesis import consolidate_thesis_file


def write_thesis(path, theme, thesis, synthesis):
    path.parent.mkdir(parents=True, exist_ok=True)
    session = {"theme": theme, "thesis": thesis, "bites": []}
    if synthesis is not None:
        session["synthesis"] = synthesis
    path.write_text(json.dumps(session))


def test_consolidate_thesis_file_puts_book_mapping_first_and_flattens_theses(tmp_path):
    session = tmp_path / "2026-10-05_1430"
    books = {"A": "The Confessions of Saint Augustine", "B": "The Society of the Spectacle"}
    session.mkdir(parents=True)
    (session / "manifest.json").write_text(json.dumps({"project": "augustine_debord", "books": books}))
    write_thesis(session / "theme-02_second" / "thesis-01.json", "Second", "t2", {"claims": ["c2"]})
    write_thesis(session / "theme-01_first" / "thesis-01.json", "First", "t1a", {"claims": ["c1a"]})
    write_thesis(session / "theme-01_first" / "thesis-02.json", "First", "t1b", None)

    out = consolidate_thesis_file(session)

    assert out == session / "2026-10-05_1430_thesis.json"
    data = json.loads(out.read_text())
    assert list(data) == ["session", "books", "theses"]
    assert data["session"] == "2026-10-05_1430"
    assert data["books"] == books
    assert [(t["theme_folder"], t["file"], t["thesis"]) for t in data["theses"]] == [
        ("theme-01_first", "thesis-01.json", "t1a"),
        ("theme-01_first", "thesis-02.json", "t1b"),
        ("theme-02_second", "thesis-01.json", "t2"),
    ]
    assert data["theses"][0] == {
        "theme_folder": "theme-01_first",
        "file": "thesis-01.json",
        "theme": "First",
        "thesis": "t1a",
        "bites": [],
        "synthesis": {"claims": ["c1a"]},
    }
    assert "synthesis" not in data["theses"][1]


def test_consolidate_thesis_file_without_manifest_writes_null_books(tmp_path):
    session = tmp_path / "2026-10-05_1500"
    write_thesis(session / "theme-01_only" / "thesis-01.json", "Only", "t", {"claims": []})

    data = json.loads(consolidate_thesis_file(session).read_text())

    assert data["books"] is None
    assert len(data["theses"]) == 1
