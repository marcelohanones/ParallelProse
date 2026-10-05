import json
import sys
from pathlib import Path


def consolidate_thesis_file(session_dir: Path) -> Path:
    manifest_path = session_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    theses = []
    for theme_dir in sorted(p for p in session_dir.iterdir() if p.is_dir() and p.name.startswith("theme-")):
        for thesis_file in sorted(theme_dir.glob("thesis-*.json")):
            thesis = json.loads(thesis_file.read_text())
            theses.append({"theme_folder": theme_dir.name, "file": thesis_file.name, **thesis})

    consolidated = {
        "session": session_dir.name,
        "books": manifest.get("books"),
        "theses": theses,
    }
    out = session_dir / f"{session_dir.name}_thesis.json"
    out.write_text(json.dumps(consolidated, indent=2, ensure_ascii=False))
    return out


if __name__ == "__main__":
    print(consolidate_thesis_file(Path(sys.argv[1])))
