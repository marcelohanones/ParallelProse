import asyncio
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ParallelProse.agent import ComposerAnswer, run_query
from ParallelProse.catalog import CATALOG, DATA_DIR
from ParallelProse.consolidate_thesis import consolidate_thesis_file
from ParallelProse.quote_check import select_quotes, verified_flags, verify_quotes
from ParallelProse.synthesis import save_bite

PROJECT = "augustine_debord"
BATCHES_PATH = DATA_DIR / "theme_batches"
QUERY_PAUSE_SECONDS = 30

THEME_RE = re.compile(r"^Theme (\d+):\s*(.+?)\s*$")
THESIS_RE = re.compile(r"^Thesis (\d+)\.(\d+):\s*(.+?)\s*$")
QUERY_RE = re.compile(r"^\s+Query (\d+)\.(\d+)([a-z])(?:\[([A-Z])\])?:\s*(.+?)\s*$")


@dataclass
class Thesis:
    number: int
    text: str
    queries: list[tuple[str, str, str | None]] = field(default_factory=list)  # (label, text, side)


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
            side = m.group(4)
            if side and side not in CATALOG:
                raise ValueError(f"line {lineno}: query {m.group(1)}.{m.group(2)}{m.group(3)} tagged with unknown book [{side}]")
            thesis.queries.append((f"{m.group(1)}.{m.group(2)}{m.group(3)}", m.group(5), side))
        else:
            raise ValueError(f"line {lineno}: not a theme, thesis or query line: {line!r}")
    return themes


def slugify(title: str, limit: int = 40) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    return slug[:limit].rstrip("-")


def restrict_to_side(answer: ComposerAnswer, side: str) -> ComposerAnswer:
    """Keeps only one book's unique findings and blanks the shared agreement/disagreement, for a query tagged with that book."""
    return ComposerAnswer(agreement="", disagreement="",
                          unique_findings=[f for f in answer.unique_findings if f.corpus_id == side])


def side_is_target(answer: ComposerAnswer, side: str | None) -> dict[str, bool | None]:
    """Per book, whether that book is the one a twin query was tagged with. None for an untagged query, where neither side is the target."""
    return {f.corpus_id: None if side is None else f.corpus_id == side for f in answer.unique_findings}


def retrieval_diagnostics(corpora: dict) -> dict[str, dict]:
    """Per book, the label, reason and tool-call lineage the retrieval loop ended with for this query."""
    return {cid: {"label": slot["label"], "reason": slot["reason"], "lineage": slot["lineage"]}
            for cid, slot in corpora.items()}


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
            for _, query, side in thesis.queries:
                if not first_query:
                    await asyncio.sleep(QUERY_PAUSE_SECONDS)
                first_query = False
                result = await run_query(query)
                answer, quote_selection = select_quotes(result["answer"], result["corpora"], query,
                                                        books={side} if side else None)
                quote_details = verify_quotes(answer, result["corpora"], query)
                save_bite(path, theme.title, thesis.text, query, answer, extra={
                    "quote_selection": quote_selection,
                    "side_is_target": side_is_target(result["answer"], side),
                    "verified": verified_flags(quote_details),
                    "verification": quote_details,
                    "retrieval": retrieval_diagnostics(result["corpora"]),
                })
            # synthesize() is disabled here on purpose: nine evaluation rounds (v3-v9) never used its claims or
            # uncovered_angle (quotes only ever came from thesis.json's bites), so item 12's own bar — "deferred
            # until the manual version proves useful" — came back negative. synthesize()/synthesis.py are kept,
            # unused, in case a cheaper mechanical gap-check (built on the survey) replaces this later.

    return consolidate_thesis_file(session)


if __name__ == "__main__":
    print(asyncio.run(run_theme_batches(Path(sys.argv[1]))))
