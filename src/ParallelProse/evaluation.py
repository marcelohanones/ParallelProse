import json
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field, ConfigDict, TypeAdapter, ValidationError, model_validator, field_validator
from typing import TypedDict, Literal, Annotated
from ParallelProse.catalog import CATALOG, DATA_DIR
from ParallelProse.survey import term_pattern

GOLDEN_SET_SIZE = 16
SCATTERED_MIN_DISTANCE = 5000  # characters: farther apart than one default parent chunk (4000)

golden_set_path = DATA_DIR / "golden_set_augustine_debord.json"


class OkExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["ok"]
    anchors: list[str] = Field(min_length=1, max_length=5)
    min_hits: int

    @model_validator(mode="after")
    def anchors_match_min_hits(self) -> "OkExpectation":
        if len(self.anchors) == 1 and self.min_hits == 1:
            return self
        elif 2 <= self.min_hits <= len(self.anchors):
            return self
        else:
            raise ValueError(
                f"{len(self.anchors)} anchors need at least {len(self.anchors) - 1} min_hits, got min_hits={self.min_hits}")


OkExpectation(label="ok", anchors=["a b c d"] * 4, min_hits=2)


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
            problems.append(f"{_entry_id(raw, position)} {'.'.join(map(str, where))}: {err['msg']}")
    if problems:
        raise ValueError("\n".join(problems))  # the book checks below assume well-formed entries

    return entries

# load_golden_set(golden_set_path)
