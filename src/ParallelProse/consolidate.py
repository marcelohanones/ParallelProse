import json
import sys
from pathlib import Path


def consolidate_session(session_dir: Path) -> Path:
    themes = []
    for theme_dir in sorted(p for p in session_dir.iterdir() if p.is_dir() and p.name.startswith("theme-")):
        theses = []
        theme_title = None
        for thesis_file in sorted(theme_dir.glob("thesis-*.json")):
            session = json.loads(thesis_file.read_text())
            theme_title = theme_title or session["theme"]
            theses.append({"file": thesis_file.name, "thesis": session["thesis"],
                           "synthesis": session.get("synthesis")})
        themes.append({"folder": theme_dir.name, "theme": theme_title, "theses": theses})

    manifest_path = session_dir / "manifest.json"
    consolidated = {
        "session": session_dir.name,
        "manifest": json.loads(manifest_path.read_text()) if manifest_path.exists() else None,
        "themes": themes,
    }
    out = session_dir / f"{session_dir.name}_synthesis.json"
    out.write_text(json.dumps(consolidated, indent=2, ensure_ascii=False))
    return out


if __name__ == "__main__":
    print(consolidate_session(Path(sys.argv[1])))
