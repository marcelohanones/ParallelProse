import asyncio
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from ParallelProse.agent import ComposerAnswer, run_query
from ParallelProse.catalog import CATALOG, DATA_DIR
from ParallelProse.consolidate_thesis import consolidate_thesis_file
from ParallelProse.quote_check import match_form, verified_flags, verify_quotes
from ParallelProse.witness_view import build_witness_view

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


def save_bite(path: Path, theme: str, thesis: str, code: str, query: str, answer: ComposerAnswer,
              extra: dict | None = None) -> None:
    """Appends one finished bite to the thesis file at path, creating it with theme/thesis if it doesn't exist yet. `extra` is stored beside the answer, never inside it."""
    if not path.exists():
        session = {"theme": theme, "thesis": thesis, "bites": []}
    else:
        session = json.loads(path.read_text())
    session["bites"].append({"code": code, "query": query, "answer": answer.model_dump(), **(extra or {})})
    path.write_text(json.dumps(session, indent=2))


def compute_bite_id(corpus_id: str, quote: str | None, query: str) -> str:
    """A bite's content-addressed id: the pair, the corpus and the quoted span, or the query when there's no
    quote (a silent book still needs an id addressable by reference, not by its position in the file)."""
    span = match_form(quote, is_quote=True) if quote is not None else match_form(query, is_quote=True)
    return sha256(json.dumps([PROJECT, corpus_id, span]).encode()).hexdigest()[:8]


def side_is_target(corpora: dict, side: str | None) -> dict[str, bool | None]:
    """Per book, whether that book is the one a twin query was tagged with. None for an untagged query, where neither side is the target."""
    return {cid: None if side is None else cid == side for cid in corpora}


def resolve_silence_cause(label: str, llm_cause: str | None, target: bool | None) -> str | None:
    """The final cause behind a 'silent' label, with the deterministic twin fact overriding the LLM's own guess:
    the critique has no visibility into side-tagging (run_query never receives it), so a book that is the
    non-target side of a twin query is 'non_target_twin' regardless of what the LLM said. None for any other
    label — a book that isn't silent has no silence to explain."""
    if label != "silent":
        return None
    if target is False:
        return "non_target_twin"
    return llm_cause


def retrieval_diagnostics(corpora: dict, side_target: dict[str, bool | None]) -> dict[str, dict]:
    """Per book, the label, reason, tool-call lineage and resolved silence cause the retrieval loop ended with.
    side_target.get(cid), not side_target[cid]: ComposerAnswer.unique_findings is only ever soft-guaranteed
    ("one entry per book") by a Field description, not enforced by the schema, so a book missing from the
    answer must not crash this — it just means the twin fact is unknown, not that the book is a non-target."""
    return {cid: {"label": slot["label"], "reason": slot["reason"], "lineage": slot["lineage"],
                 "silence_cause": resolve_silence_cause(slot["label"], slot["silence_cause"],
                                                        side_target.get(cid)),
                 "P": slot.get("P"), "retry_used": slot.get("retry_used", False)}
            for cid, slot in corpora.items()}


async def answer_query(query: str, side: str | None, callbacks=None) -> tuple[ComposerAnswer, dict, dict]:
    """One query through the pipeline: run the graph, verify every (claim, sentence) pair each book contributed.
    Returns the final answer, the bite's extra fields, and the final corpora (which still hold each book's retrieved
    chunks)."""
    result = await run_query(query, callbacks=callbacks)
    answer = result["answer"]
    quote_details = verify_quotes(answer, result["corpora"], query)
    side_target = side_is_target(result["corpora"], side)
    findings = {f.corpus_id: f for f in answer.unique_findings}
    extra = {
        "bite_id": {cid: [compute_bite_id(cid, pair.sentence, query)
                          for pair in (findings[cid].pairs if cid in findings else [])]
                    for cid in result["corpora"]},
        "side_is_target": side_target,
        "verified": verified_flags(quote_details),
        "verification": quote_details,
        "retrieval": retrieval_diagnostics(result["corpora"], side_target),
    }
    return answer, extra, result["corpora"]


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
        "books": {cid: {"title": book.book_title, "translator": book.translator,
                        "year": book.year, "publisher": book.publisher}
                  for cid, book in CATALOG.items()},
    }, indent=2, ensure_ascii=False))

    first_query = True
    for theme in themes:
        theme_dir = session / f"theme-{theme.number:02d}_{slugify(theme.title)}"
        theme_dir.mkdir()
        for thesis in theme.theses:
            path = theme_dir / f"thesis-{thesis.number:02d}.json"
            for code, query, side in thesis.queries:
                if not first_query:
                    await asyncio.sleep(QUERY_PAUSE_SECONDS)
                first_query = False
                answer, extra, _ = await answer_query(query, side)
                save_bite(path, theme.title, thesis.text, code, query, answer, extra=extra)

    thesis_path = consolidate_thesis_file(session)
    build_witness_view(thesis_path)
    return thesis_path


if __name__ == "__main__":
    print(asyncio.run(run_theme_batches(Path(sys.argv[1]))))
