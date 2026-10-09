import json
import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field, ConfigDict, TypeAdapter, ValidationError, model_validator, field_validator
from typing import TypedDict, Literal, Annotated
from ParallelProse.catalog import CATALOG, DATA_DIR
from ParallelProse.ingest import load_corpus
from ParallelProse.quote_check import _content_terms, match_form
from ParallelProse.survey import term_pattern

GOLDEN_SET_SIZE = 16
SCATTERED_MIN_DISTANCE = 5000  # characters: farther apart than one default parent chunk (4000)
QUOTED_RUN = 4  # a query sharing this many consecutive words with an anchor quotes it

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
