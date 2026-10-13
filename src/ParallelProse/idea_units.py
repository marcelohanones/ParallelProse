import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from ParallelProse.catalog import CATALOG
from ParallelProse.evaluation import _phrase_pattern
from ParallelProse.null_search import NullSearch
from ParallelProse.quote_check import book_paragraphs
from ParallelProse.survey import term_pattern

# A half-dozen words per side, used only to flag a one-sided unit that borrows the other book's vocabulary —
# never to reject. Not a revival of item 34's removed query-time vocabulary system (that scored 1 catch in 118
# queries); this is editorial-time, on a bank that grows one unit at a time.
SIGNATURE_WORDS = {
    "A": ["god", "soul", "sin", "grace", "divine", "spiritual", "confession"],
    "B": ["spectacle", "commodity", "alienation", "capital", "image", "representation"],
}


class FalsificationTest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, description="phrased as an ordinary batch query")
    side: Literal["A", "B"] = Field(description="the target side this test tries to break")


class Promotion(BaseModel):
    """The decision to promote, named. null_search_ref must resolve in the null-search registry, and that
    search must have been run for this unit's own falsification test — a promotion is never licensed by
    silence alone."""
    model_config = ConfigDict(extra="forbid")
    decider: str = Field(min_length=1)
    null_search_ref: str = Field(min_length=1)
    date: str = Field(min_length=1)


class IdeaUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^u\d{2,}$")
    type: Literal["convergence", "divergence", "single_voice", "false_positive"]
    mechanism_a: str | None = Field(default=None, description="what A asserts: when X, Y happens, because Z")
    mechanism_b: str | None = Field(default=None, description="what B asserts, same form")
    form_a: Literal["scene", "thesis", "confession", "diagnosis"] | None = None
    form_b: Literal["scene", "thesis", "confession", "diagnosis"] | None = None
    shared_structure: str = Field(min_length=1, description="the form the two mechanisms share")
    divergence_axis: str = Field(min_length=1, description="the one nameable variable they differ on")
    falsification_test: FalsificationTest | None = None
    falsification_single_voice: str | None = Field(
        default=None, description="what, if found, would break a single_voice claim — no target side")
    anchoring: list[str] = Field(min_length=1, description="bite_ids, never quoted text")
    promotion: Promotion | None = None

    @model_validator(mode="after")
    def mechanisms_and_forms_match_type(self) -> "IdeaUnit":
        if self.type == "single_voice":
            if (self.mechanism_a is None) == (self.mechanism_b is None):
                raise ValueError("single_voice needs exactly one of mechanism_a/mechanism_b")
            if (self.mechanism_a is None) != (self.form_a is None):
                raise ValueError("form_a must be set exactly when mechanism_a is set")
            if (self.mechanism_b is None) != (self.form_b is None):
                raise ValueError("form_b must be set exactly when mechanism_b is set")
        else:
            if self.mechanism_a is None or self.mechanism_b is None:
                raise ValueError(f"{self.type} needs both mechanism_a and mechanism_b")
            if self.form_a is None or self.form_b is None:
                raise ValueError(f"{self.type} needs both form_a and form_b")
        return self

    @model_validator(mode="after")
    def falsification_matches_type(self) -> "IdeaUnit":
        if self.type == "single_voice":
            if self.falsification_single_voice is None or self.falsification_test is not None:
                raise ValueError("single_voice needs falsification_single_voice, not falsification_test")
        else:
            if self.falsification_test is None or self.falsification_single_voice is not None:
                raise ValueError(f"{self.type} needs falsification_test, not falsification_single_voice")
        return self


def build_bites_index(project_dir: Path) -> dict[str, dict]:
    """bite_id -> {"corpus_id", "sentence"}, scanned from every witness_view_*.json under a project's sessions."""
    index = {}
    for path in project_dir.glob("*/witness_view_*.json"):
        for record in json.loads(path.read_text())["records"]:
            if record["sentence"] is not None:
                index[record["bite_id"]] = {"corpus_id": record["corpus_id"], "sentence": record["sentence"]}
    return index


def _anchoring_problems(unit: IdeaUnit, bites_index: dict[str, dict]) -> list[str]:
    """Every anchoring id resolves to a real bite, and that bite's quote is independently found in its book —
    the same _phrase_pattern check _book_problems runs for golden-set anchors, never trusting the bite's own
    stored verification.status."""
    problems = []
    for bite_id in unit.anchoring:
        if bite_id not in bites_index:
            problems.append(f"{unit.id}: anchoring cites unknown bite_id {bite_id!r}")
            continue
        entry = bites_index[bite_id]
        paragraphs, _ = book_paragraphs(CATALOG[entry["corpus_id"]])
        if not any(_phrase_pattern(entry["sentence"]).search(p) for p in paragraphs):
            problems.append(f"{unit.id}: anchoring bite {bite_id!r} not found in book {entry['corpus_id']}")
    return problems


def _contamination_flags(unit: IdeaUnit, bites_index: dict[str, dict]) -> list[str]:
    """A unit anchored entirely in one side that still uses the other side's signature words — flagged, never
    rejected, since a genuinely cross-book unit must name both vocabularies."""
    sides = {bites_index[bite_id]["corpus_id"] for bite_id in unit.anchoring if bite_id in bites_index}
    if len(sides) != 1:
        return []
    anchored_side = next(iter(sides))
    other_side = next(cid for cid in CATALOG if cid != anchored_side)
    text = " ".join(filter(None, [unit.mechanism_a, unit.mechanism_b, unit.shared_structure])).lower()
    hits = [word for word in SIGNATURE_WORDS[other_side] if term_pattern(word).search(text)]
    return [f"{unit.id}: anchored only in {anchored_side} but uses {other_side}'s words {hits}"] if hits else []


def _promotion_problems(unit: IdeaUnit, null_searches: dict[str, NullSearch] | None) -> list[str]:
    """A promotion must point at a registered null search run for this unit's own test: the gate reads the
    search, never the silence. With no registry given, any promotion is unverifiable and rejected."""
    if unit.promotion is None:
        return []
    ref = unit.promotion.null_search_ref
    if null_searches is None:
        return [f"{unit.id}: promotion cites {ref!r} but no null-search registry was given"]
    record = null_searches.get(ref)
    if record is None:
        return [f"{unit.id}: promotion cites unknown null_search_ref {ref!r}"]
    problems = []
    if record.unit != unit.id:
        problems.append(f"{unit.id}: null search {ref!r} belongs to {record.unit}")
    if unit.falsification_test is not None and record.side != unit.falsification_test.side:
        problems.append(f"{unit.id}: null search {ref!r} ran against side {record.side}, "
                        f"but the unit's test targets {unit.falsification_test.side}")
    return problems


def _unit_id(raw: list, position: int) -> str:
    entry = raw[position]
    return entry["id"] if isinstance(entry, dict) and entry.get("id") else f"entry {position + 1}"


def load_idea_units(path: Path, bites_index: dict[str, dict],
                    null_searches: dict[str, NullSearch] | None = None) -> tuple[list[IdeaUnit], list[str]]:
    """Reads the idea unit bank and rejects it, before any script reads it, if an entry is malformed, cites a
    quote that doesn't actually exist in its book, or carries a promotion that no registered null search
    backs. A one-sided unit borrowing the other book's vocabulary is returned with a flag instead, since that
    pattern can be legitimate. Raises one ValueError listing every rejection; returns (units, flags) when the
    file is structurally and referentially sound."""
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise ValueError("the idea unit bank must be a JSON list of entries")
    problems = []

    ids = Counter(entry.get("id") for entry in raw if isinstance(entry, dict) and entry.get("id"))
    problems += [f"{uid}: id used {count} times" for uid, count in ids.items() if count > 1]
    try:
        units = TypeAdapter(list[IdeaUnit]).validate_python(raw)
    except ValidationError as error:
        for err in error.errors():
            position, *where = err["loc"]
            place = " ".join([_unit_id(raw, position), ".".join(map(str, where))]).strip()
            problems.append(f"{place}: {err['msg']}")
    if problems:
        raise ValueError("\n".join(problems))

    for unit in units:
        problems += _anchoring_problems(unit, bites_index)
        problems += _promotion_problems(unit, null_searches)
    if problems:
        raise ValueError("\n".join(problems))

    flags = [flag for unit in units for flag in _contamination_flags(unit, bites_index)]
    return units, flags
