import json

from ParallelProse.consolidate import consolidate_session


def write_thesis(path, theme, thesis, synthesis):
    path.parent.mkdir(parents=True, exist_ok=True)
    session = {"theme": theme, "thesis": thesis, "bites": []}
    if synthesis is not None:
        session["synthesis"] = synthesis
    path.write_text(json.dumps(session))


def test_consolidate_merges_every_thesis_synthesis_under_its_theme(tmp_path):
    session = tmp_path / "2026-10-05_1430"
    write_thesis(session / "theme-02_second" / "thesis-01.json", "Second", "t2", {"claims": ["c2"]})
    write_thesis(session / "theme-01_first" / "thesis-01.json", "First", "t1a", {"claims": ["c1a"]})
    write_thesis(session / "theme-01_first" / "thesis-02.json", "First", "t1b", None)
    (session / "manifest.json").write_text(json.dumps({"tryout": "bundle-a"}))

    out = consolidate_session(session)

    assert out == session / "2026-10-05_1430_synthesis.json"
    data = json.loads(out.read_text())
    assert data["session"] == "2026-10-05_1430"
    assert data["manifest"] == {"tryout": "bundle-a"}
    assert [t["folder"] for t in data["themes"]] == ["theme-01_first", "theme-02_second"]
    first = data["themes"][0]
    assert first["theme"] == "First"
    assert first["theses"] == [
        {"file": "thesis-01.json", "thesis": "t1a", "synthesis": {"claims": ["c1a"]}},
        {"file": "thesis-02.json", "thesis": "t1b", "synthesis": None},
    ]


def test_consolidate_without_manifest_writes_null(tmp_path):
    session = tmp_path / "2026-10-05_1500"
    write_thesis(session / "theme-01_only" / "thesis-01.json", "Only", "t", {"claims": []})

    data = json.loads(consolidate_session(session).read_text())

    assert data["manifest"] is None
    assert len(data["themes"]) == 1
