"""The null-search registry (roadmap item 43): one record per falsification test that was run and came back
empty. The registry is what a unit's `promotion` points at, so "nothing was found" is never read as a
verdict — the record says a search happened, when, against which side, and in which corpus."""

import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from ParallelProse.catalog import DATA_DIR

null_search_path = DATA_DIR / "null_searches_augustine_debord.json"


class NullSearch(BaseModel):
    """One recorded falsification search that came back empty. It records that the search happened; it is
    never a verdict, and never evidence that the claim it was run against holds."""
    model_config = ConfigDict(extra="forbid")
    ref: str = Field(min_length=1, description="unique id a unit's promotion.null_search_ref points at")
    unit: str = Field(pattern=r"^u\d{2,}$", description="the idea unit whose falsification test this search runs")
    term: str = Field(min_length=1, description="the term or query actually searched")
    side: Literal["A", "B"] = Field(description="the target side whose claim the search tries to break")
    corpus: Literal["A", "B"] = Field(description="the corpus the term was searched in")
    date: str = Field(min_length=1, description="when the search was run")


def _entry_ref(raw: list, position: int) -> str:
    entry = raw[position]
    return entry["ref"] if isinstance(entry, dict) and entry.get("ref") else f"entry {position + 1}"


def load_null_searches(path: Path) -> dict[str, NullSearch]:
    """Reads the registry and rejects it, before any promotion is read, if an entry is malformed or a ref is
    repeated. Returns ref -> record. A missing file is an empty registry, so a unit bank with no promotions
    loads against it unchanged."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise ValueError("the null-search registry must be a JSON list of entries")
    problems = []
    refs = Counter(entry.get("ref") for entry in raw if isinstance(entry, dict) and entry.get("ref"))
    problems += [f"{ref}: ref used {count} times" for ref, count in refs.items() if count > 1]
    try:
        records = TypeAdapter(list[NullSearch]).validate_python(raw)
    except ValidationError as error:
        for err in error.errors():
            position, *where = err["loc"]
            place = " ".join([_entry_ref(raw, position), ".".join(map(str, where))]).strip()
            problems.append(f"{place}: {err['msg']}")
    if problems:
        raise ValueError("\n".join(problems))
    return {record.ref: record for record in records}


def record_null_search(path: Path, record: NullSearch) -> None:
    """Appends one null search to the registry, creating the file if it does not exist. A ref already present
    is left as it is: the registry keeps one search per falsification test, and re-running a test does not
    make a second search."""
    existing = json.loads(path.read_text()) if path.exists() else []
    if any(entry.get("ref") == record.ref for entry in existing):
        return
    existing.append(record.model_dump())
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n")
