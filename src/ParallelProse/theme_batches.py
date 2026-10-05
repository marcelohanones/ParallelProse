import asyncio
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ParallelProse.agent import run_query
from ParallelProse.catalog import CATALOG, DATA_DIR
from ParallelProse.consolidate import consolidate_session
from ParallelProse.synthesis import load_bites, save_bite, save_synthesis, synthesize

PROJECT = "augustine_debord"
BATCHES_PATH = DATA_DIR / "theme_batches"
QUERY_PAUSE_SECONDS = 30

THEME_RE = re.compile(r"^Theme (\d+):\s*(.+?)\s*$")
THESIS_RE = re.compile(r"^Thesis (\d+)\.(\d+):\s*(.+?)\s*$")
QUERY_RE = re.compile(r"^\s+Query (\d+)\.(\d+)([a-z]):\s*(.+?)\s*$")


@dataclass
class Thesis:
    number: int
    text: str
    queries: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Theme:
    number: int
    title: str
    theses: list[Thesis] = field(default_factory=list)


def parse_batch(text: str) -> list[Theme]:
    themes: list[Theme] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("```"):
            continue
        if m := THEME_RE.match(line):
            themes.append(Theme(int(m.group(1)), m.group(2)))
        elif m := THESIS_RE.match(line):
            if not themes:
                raise ValueError(f"line {lineno}: thesis before any theme")
            if int(m.group(1)) != themes[-1].number:
                raise ValueError(f"line {lineno}: thesis {m.group(1)}.{m.group(2)} sits under theme {themes[-1].number}")
            themes[-1].theses.append(Thesis(int(m.group(2)), m.group(3)))
        elif m := QUERY_RE.match(line):
            if not themes or not themes[-1].theses:
                raise ValueError(f"line {lineno}: query before any thesis")
            theme, thesis = themes[-1], themes[-1].theses[-1]
            if int(m.group(1)) != theme.number or int(m.group(2)) != thesis.number:
                raise ValueError(f"line {lineno}: query {m.group(1)}.{m.group(2)}{m.group(3)} sits under thesis {theme.number}.{thesis.number}")
            thesis.queries.append((f"{m.group(1)}.{m.group(2)}{m.group(3)}", m.group(4)))
        else:
            raise ValueError(f"line {lineno}: not a theme, thesis or query line: {line!r}")
    return themes


def slugify(title: str, limit: int = 40) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    return slug[:limit].rstrip("-")


async def run_theme_batches(batch_file: Path) -> Path:
    text = batch_file.read_text()
    themes = parse_batch(text)
    started = datetime.now()
    session = BATCHES_PATH / PROJECT / started.strftime("%Y-%m-%d_%H%M")
    session.mkdir(parents=True)
    (session / "source.md").write_text(text)
    (session / "manifest.json").write_text(json.dumps({
        "source": batch_file.name,
        "started": started.isoformat(timespec="seconds"),
        "project": PROJECT,
        "books": {cid: book.book_title for cid, book in CATALOG.items()},
    }, indent=2, ensure_ascii=False))

    first_query = True
    for theme in themes:
        theme_dir = session / f"theme-{theme.number:02d}_{slugify(theme.title)}"
        theme_dir.mkdir()
        for thesis in theme.theses:
            path = theme_dir / f"thesis-{thesis.number:02d}.json"
            for _, query in thesis.queries:
                if not first_query:
                    await asyncio.sleep(QUERY_PAUSE_SECONDS)
                first_query = False
                result = await run_query(query)
                save_bite(path, theme.title, thesis.text, query, result["answer"])
            if thesis.queries:
                _, _, bites = load_bites(path)
                save_synthesis(path, synthesize(theme.title, thesis.text, bites))

    return consolidate_session(session)


if __name__ == "__main__":
    print(asyncio.run(run_theme_batches(Path(sys.argv[1]))))
