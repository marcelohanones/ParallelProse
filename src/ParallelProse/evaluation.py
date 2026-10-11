import json
import re
from collections import Counter
from hashlib import sha256
from pathlib import Path

from langsmith import Client, aevaluate

from pydantic import BaseModel, Field, ConfigDict, TypeAdapter, ValidationError, model_validator, field_validator
from typing import TypedDict, Literal, Annotated
from ParallelProse.catalog import CATALOG, DATA_DIR
from ParallelProse.ingest import load_corpus
from ParallelProse.judges import attribution, faithfulness
from ParallelProse.quote_check import _content_terms, match_form
from ParallelProse.survey import term_pattern
from ParallelProse.theme_batches import answer_query

GOLDEN_SET_SIZE = 16
SCATTERED_MIN_DISTANCE = 5000  # characters: farther apart than one default parent chunk (4000)
QUOTED_RUN = 4  # a query sharing this many consecutive words with an anchor quotes it
LANGSMITH_METADATA = {"dataset_split"}  # keys LangSmith adds to an example's metadata, not ours to rebuild from

golden_set_path = DATA_DIR / "golden_set_augustine_debord.json"


def _phrase_pattern(phrase: str) -> re.Pattern:
    """The phrase in match_form, as whole words: never the inside of a longer word. Unlike term_pattern's \\b,
    the edges also hold when the phrase starts or ends with punctuation."""
    return re.compile(r"(?<!\w)" + re.escape(match_form(phrase)) + r"(?!\w)")


def _word_runs(text: str, size: int = QUOTED_RUN) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", match_form(text))
    return {tuple(words[i:i + size]) for i in range(len(words) - size + 1)}


class OkExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["ok"]
    anchors: list[str] = Field(min_length=1, max_length=5)
    min_hits: int

    @field_validator("anchors")
    @classmethod
    def anchors_are_4_to_12_words(cls, value: list[str]) -> list[str]:
        """Long enough to occur once in the book, short enough to sit inside any retrieved chunk."""
        wrong = [anchor for anchor in value if not 4 <= len(anchor.split()) <= 12]
        if wrong:
            raise ValueError(f"anchors must be 4-12 words: {wrong}")
        return value

    @model_validator(mode="after")
    def anchors_match_min_hits(self) -> "OkExpectation":
        if len(self.anchors) == 1 and self.min_hits == 1:
            return self
        elif 2 <= self.min_hits <= len(self.anchors):
            return self
        else:
            rule = "1 anchor needs min_hits 1" if len(self.anchors) == 1 else \
                f"{len(self.anchors)} anchors need min_hits between 2 and {len(self.anchors)}"
            raise ValueError(f"{rule}, got min_hits={self.min_hits}")


class SilentExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["silent"]
    near_miss: bool
    absent_terms: list[str] = Field(min_length=2, max_length=5)


Expectation = Annotated[OkExpectation | SilentExpectation, Field(discriminator="label")]


class GoldenEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^g\d{2}$")
    theme: str = Field(min_length=1)
    query: str = Field(min_length=1)
    side: Literal["A", "B"] | None
    specificity: Literal["specific", "abstract"]
    wording: Literal["book", "paraphrase"]
    known_failure: bool
    expected: dict[str, Expectation]
    note: str = Field(min_length=1)

    @field_validator("expected")
    @classmethod
    def expected_covers_catalog(cls, value: dict[str, Expectation]) -> dict[str, Expectation]:
        if set(value) != set(CATALOG):
            raise ValueError(f"expected has books {sorted(value)}, needs {sorted(CATALOG)}")
        else:
            return value

    @field_validator("query")
    @classmethod
    def query_names_no_author(cls, value: str) -> str:
        """The same query is searched in both books, so an author's name in it only adds noise."""
        surnames = [book.author.split()[-1] for book in CATALOG.values()]
        named = [surname for surname in surnames if term_pattern(surname).search(value.lower())]
        if named:
            raise ValueError(f"query names an author: {', '.join(named)}")
        return value

    @model_validator(mode="after")
    def query_does_not_quote_anchors(self) -> "GoldenEntry":
        """A query that repeats its anchor's words passes the anchor check by word overlap alone."""
        query_runs = _word_runs(self.query)
        problems = []
        for cid, expectation in self.expected.items():
            if expectation.label != "ok":
                continue
            for anchor in expectation.anchors:
                if query_runs & _word_runs(anchor):
                    problems.append(f"{cid}: query repeats {QUOTED_RUN} words in a row from anchor {anchor!r}")
                shared = _content_terms(self.query) & _content_terms(anchor)
                if self.wording == "paraphrase" and shared:
                    problems.append(f"{cid}: paraphrase query shares {sorted(shared)} with anchor {anchor!r}")
        if problems:
            raise ValueError("; ".join(problems))
        return self


def _entry_id(raw: list, position: int) -> str:
    """The id an entry gives itself, or its position in the file when it has none."""
    entry = raw[position]
    return entry["id"] if isinstance(entry, dict) and entry.get("id") else f"entry {position + 1}"


def load_golden_set(path: Path) -> list[GoldenEntry]:
    """Reads the golden set and rejects it, before any run, if an entry could never be passed by any run
    or the set misses a composition row of docs/golden_set_spec.md.
    Raises one ValueError listing every problem, each naming the entry id and, where it applies, the book."""
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise ValueError("the golden set must be a JSON list of entries")
    problems = []

    # 1 — STRUCTURE. Reads: the file only; no book is opened. Every check on a single entry lives in the
    # models above; only a repeated id needs all entries at once.
    ids = Counter(entry.get("id") for entry in raw if isinstance(entry, dict) and entry.get("id"))
    problems += [f"{entry_id}: id used {count} times" for entry_id, count in ids.items() if count > 1]
    try:
        entries = TypeAdapter(list[GoldenEntry]).validate_python(raw)
    except ValidationError as error:
        for err in error.errors():
            position, *where = err["loc"]
            place = " ".join([_entry_id(raw, position), ".".join(map(str, where))]).strip()
            problems.append(f"{place}: {err['msg']}")
    if problems:
        raise ValueError("\n".join(problems))  # the book checks below assume well-formed entries

    # 2 — BOOK TEXT. Reads: both books. Checks nothing; only builds.
    books = {cid: _book_paragraphs(book) for cid, book in CATALOG.items()}

    # 3 — EACH ENTRY AGAINST ITS BOOK: could any run pass it?  4 — THE WHOLE SET: does it fill every row?
    problems = _book_problems(entries, books) + _composition_problems(entries)
    if problems:
        raise ValueError("\n".join(problems))
    return entries


PROJECT = "augustine_debord"


def push_golden_set(entries: list[GoldenEntry], client=None) -> str:
    """Creates (or reuses) one LangSmith dataset holding the golden set, and returns its name. The name carries a
    hash of the entries, so unchanged content reuses its dataset and edited content gets a new one, leaving the old
    dataset's experiments comparable. Raises if a dataset of that name holds a different number of examples."""
    dumped = [entry.model_dump() for entry in entries]
    digest = sha256(json.dumps(dumped, sort_keys=True).encode()).hexdigest()[:8]
    name = f"golden-{PROJECT}-{digest}"
    client = client or Client()

    if client.has_dataset(dataset_name=name):
        stored = sum(1 for _ in client.list_examples(dataset_name=name))
        if stored != len(entries):  # a create_examples that failed partway would otherwise be reused in silence
            raise ValueError(f"dataset {name} holds {stored} examples, expected {len(entries)}: "
                             f"delete it in LangSmith and push again")
        return name

    dataset = client.create_dataset(name, description=f"ParallelProse golden set ({PROJECT}), "
                                                      f"written to docs/golden_set_spec.md")
    client.create_examples(dataset_id=dataset.id, examples=[
        {"inputs": {"id": entry["id"], "query": entry["query"], "side": entry["side"]},
         "outputs": {"expected": entry["expected"]},
         "metadata": {key: entry[key] for key in ("theme", "specificity", "wording", "known_failure", "note")}}
        for entry in dumped])
    return name


def _book_paragraphs(book) -> tuple[list[str], list[int]]:
    """The book's paragraphs in match_form, and where each one starts in the paragraphs joined with a space.
    _load_epub joins a chapter's paragraphs with a blank line, so splitting on it gives them back."""
    paragraphs = [match_form(p) for chapter in load_corpus(str(book.path))
                  for p in chapter.page_content.split("\n\n") if p.strip()]
    starts, position = [], 0
    for paragraph in paragraphs:
        starts.append(position)
        position += len(paragraph) + 1
    return paragraphs, starts


def _book_problems(entries: list[GoldenEntry], books: dict[str, tuple[list[str], list[int]]]) -> list[str]:
    """Anchors: exactly one occurrence in the book (which also proves it exists and sits inside one paragraph),
    a paragraph used by one entry only, scattered anchors far apart. Absent terms: no occurrence at all."""
    problems = []
    used = {}  # (book, paragraph index) -> the entry that uses it
    for entry in entries:
        for cid, expectation in entry.expected.items():
            paragraphs, starts = books[cid]
            if expectation.label == "silent":
                for term in expectation.absent_terms:
                    pattern = _phrase_pattern(term)
                    count = sum(len(pattern.findall(p)) for p in paragraphs)
                    if count:
                        problems.append(f"{entry.id} {cid}: absent term {term!r} occurs {count} times in the book")
                continue

            found = []  # (paragraph index, position in the whole book), one per anchor found exactly once
            for anchor in expectation.anchors:
                pattern = _phrase_pattern(anchor)
                hits = [(i, starts[i] + m.start()) for i, p in enumerate(paragraphs) for m in pattern.finditer(p)]
                if len(hits) != 1:
                    problems.append(f"{entry.id} {cid}: anchor {anchor!r} found {len(hits)} times in the book, "
                                    f"needs exactly 1")
                    continue
                found.append(hits[0])

            paragraph_ids = [i for i, _ in found]
            if len(set(paragraph_ids)) < len(paragraph_ids):
                problems.append(f"{entry.id} {cid}: two anchors come from the same paragraph")
            for i in set(paragraph_ids):
                owner = used.setdefault((cid, i), entry.id)
                if owner != entry.id:
                    problems.append(f"{entry.id} {cid}: anchor paragraph already used by {owner}")

            if len(expectation.anchors) > 1 and len(found) == len(expectation.anchors):
                spread = max(p for _, p in found) - min(p for _, p in found)
                if spread < SCATTERED_MIN_DISTANCE:
                    problems.append(f"{entry.id} {cid}: scattered anchors span {spread} characters, "
                                    f"need {SCATTERED_MIN_DISTANCE}")
    return problems


def _composition_problems(entries: list[GoldenEntry]) -> list[str]:
    """Every row of the composition table in docs/golden_set_spec.md, against its minimum."""
    a, b = sorted(CATALOG)
    pairs = Counter((entry.expected[a].label, entry.expected[b].label) for entry in entries)
    rows = [
        ("both books ok", pairs["ok", "ok"], 6),
        (f"{a} ok, {b} silent", pairs["ok", "silent"], 3),
        (f"{a} silent, {b} ok", pairs["silent", "ok"], 3),
        ("both books silent", pairs["silent", "silent"], 1),
        ('"wording": "book"', sum(entry.wording == "book" for entry in entries), 5),
        ('"wording": "paraphrase"', sum(entry.wording == "paraphrase" for entry in entries), 5),
        ("known_failure", sum(entry.known_failure for entry in entries), 2),
        ("distinct themes", len({entry.theme for entry in entries}), 8),
    ]
    for cid in sorted(CATALOG):
        expectations = [(entry, entry.expected[cid]) for entry in entries]
        rows.append((f"{cid} silent with near_miss",
                     sum(x.label == "silent" and x.near_miss for _, x in expectations), 1))
        for shape in ("single", "scattered"):
            for specificity in ("specific", "abstract"):
                count = sum(x.label == "ok" and (len(x.anchors) > 1) == (shape == "scattered")
                            and entry.specificity == specificity for entry, x in expectations)
                rows.append((f"{cid} ok {shape}/{specificity}", count, 2))

    problems = [f"set: {name} has {count}, needs at least {minimum}" for name, count, minimum in rows if
                count < minimum]
    if len(entries) != GOLDEN_SET_SIZE:
        problems.insert(0, f"set: has {len(entries)} entries, needs exactly {GOLDEN_SET_SIZE}")
    return problems


async def run_golden_query(entry_id: str, query: str, side: str | None) -> dict:
    """One golden query through the same pipeline the batch runs use. Returns a bite's shape plus the entry's id and
    each book's retrieved chunks, which the anchor check reads and a bite drops. Takes the three fields the run needs
    rather than a whole entry, so LangSmith's target can call it with an example's inputs alone."""
    answer, extra, corpora = await answer_query(query, side)
    return {
        "id": entry_id,
        "query": query,
        "answer": answer.model_dump(),
        **extra,
        "chunks": {cid: slot["chunks"] or [] for cid, slot in corpora.items()},
    }


async def run_golden_entry(entry: GoldenEntry) -> dict:
    """The target, for callers that already hold the whole entry."""
    return await run_golden_query(entry.id, entry.query, entry.side)


def anchor_hits(record: dict, entry: GoldenEntry) -> dict[str, dict]:
    """Per book expected ok: how many of its anchors appear in the chunks this run retrieved, matched the way the loader
    matches them, one chunk at a time (never joined, so no match can cross a seam). Silent books are left to the
    label check."""
    results = {}
    for cid, expectation in entry.expected.items():
        if expectation.label != "ok":
            continue
        chunks = [match_form(chunk) for chunk in record["chunks"][cid]]
        missing = [anchor for anchor in expectation.anchors
                   if not any(_phrase_pattern(anchor).search(chunk) for chunk in chunks)]
        found = len(expectation.anchors) - len(missing)
        results[cid] = {"found": found, "needed": expectation.min_hits,
                        "passed": found >= expectation.min_hits, "missing": missing}
    return results


def label_agreement(record: dict, entry: GoldenEntry) -> dict[str, dict]:
    """Per book, the final label the graph ended on against the golden one. Only an exact match agrees, so a final
    miss (retries ran out) never does; expected and final stay beside the verdict so the failures can be told apart:
    ok->miss gave up, ok->silent false silence, silent->ok false ok, silent->miss never conceded."""
    results = {}
    for cid, expectation in entry.expected.items():
        final = record["retrieval"][cid]["label"]
        results[cid] = {"expected": expectation.label, "final": final, "agree": final == expectation.label}
    return results


# MARK: LANGSMITH ADAPTERS
# Thin wrappers only: LangSmith hands each reader one part of an example and stores {key, score} rows, while the
# functions above take a whole entry and return per-book dicts. Nothing above depends on LangSmith.

def _entry_from(example) -> GoldenEntry:
    """A GoldenEntry rebuilt from the three parts push_golden_set split it into."""
    metadata = {key: value for key, value in (example.metadata or {}).items() if key not in LANGSMITH_METADATA}
    return GoldenEntry(**example.inputs, **example.outputs, **metadata)


async def golden_target(inputs: dict) -> dict:
    """The target LangSmith calls, once per example (and once per repetition)."""
    return await run_golden_query(inputs["id"], inputs["query"], inputs["side"])


def _rows(name: str, per_book: dict[str, dict], passed: str) -> dict:
    """Per book, one result keyed f"{name}_{book}": LangSmith averages each key on its own, so the two books stay
    separate columns. A book with nothing to answer is simply absent, never a zero (which would drag the average)."""
    return {"results": [
        {"key": f"{name}_{cid}", "score": int(bool(result[passed])),
         "comment": json.dumps({k: v for k, v in result.items() if k != passed}, ensure_ascii=False)}
        for cid, result in sorted(per_book.items())]}


def anchors_evaluator(outputs: dict, example) -> dict:
    """Per book expected ok: did this run retrieve at least min_hits of its anchors?"""
    return _rows("anchor_hits", anchor_hits(outputs, _entry_from(example)), "passed")


def labels_evaluator(outputs: dict, example) -> dict:
    """Per book: does the final label match the golden one?"""
    return _rows("label_agreement", label_agreement(outputs, _entry_from(example)), "agree")


def faithfulness_evaluator(outputs: dict) -> dict:
    """Per judged book: is every claim of the finding supported by its quote alone?"""
    return _rows("faithfulness", faithfulness(outputs), "passed")


def attribution_evaluator(outputs: dict) -> dict:
    """Per judged book: is the finding credited to the book whose passages state it?"""
    return _rows("attribution", attribution(outputs), "passed")


EVALUATORS = [anchors_evaluator, labels_evaluator]            # deterministic, free
JUDGES = [faithfulness_evaluator, attribution_evaluator]      # one judge-model call per judged book


def configuration() -> dict:
    """What the live objects are set to, read rather than typed, so an experiment's record cannot disagree with the
    code that produced it. Scores move with the chunk sizes and with either model, so all of them belong here."""
    from ParallelProse.agent import llm                 # imported here: both open stores / clients at import time
    from ParallelProse.judges import JUDGE_MODEL
    from ParallelProse.mcp_tools import REGISTRY

    splitters = {}
    for cid, retrieval in sorted(REGISTRY.items()):
        for part, config in (("child", retrieval.child_config), ("parent", retrieval.parent_config)):
            splitters[f"{part}_chunk_size_{cid}"] = config.chunk_size
            splitters[f"{part}_overlap_{cid}"] = config.chunk_overlap
    return {**splitters, "system_model": llm.model_name, "judge_model": JUDGE_MODEL}


async def run_experiment(entries: list[GoldenEntry], *, judges: bool = False, repetitions: int = 3,
                         concurrency: int = 2, prefix: str = "pp") -> str:
    """Runs the golden set as one LangSmith experiment and returns its name. The dataset is pushed (or reused) first,
    so the experiment is always tied to the golden set it was scored against. Concurrency is capped because every
    example shares one MCP server and one model rate limit; a throttled example lands as a low score, not a crash."""
    dataset = push_golden_set(entries)
    results = await aevaluate(
        golden_target,
        data=dataset,
        evaluators=EVALUATORS + (JUDGES if judges else []),
        metadata={**configuration(), "judges": judges, "golden_set": dataset, "repetitions": repetitions},
        num_repetitions=repetitions,
        max_concurrency=concurrency,
        experiment_prefix=prefix,
    )
    return results.experiment_name


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Validate the golden set, push it, and optionally run an experiment.")
    parser.add_argument("--run", action="store_true", help="run a LangSmith experiment over the golden set")
    parser.add_argument("--judges", action="store_true", help="also run the two LLM judges (one call per book)")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()

    golden_entries = load_golden_set(golden_set_path)
    print(f"{len(golden_entries)} entries accepted")
    print(f"dataset: {push_golden_set(golden_entries)}")
    if args.run:
        print(f"configuration: {configuration()}")
        name = asyncio.run(run_experiment(golden_entries, judges=args.judges, repetitions=args.repetitions,
                                          concurrency=args.concurrency))
        print(f"experiment: {name}")
