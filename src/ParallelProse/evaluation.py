import json
from pathlib import Path

from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import TypedDict, Literal, Annotated
from ParallelProse.catalog import CATALOG, DATA_DIR
from ParallelProse.ingest import load_corpus
from ParallelProse.quote_check import _content_terms, match_form

GOLDEN_SET_SIZE = 16
SCATTERED_MIN_DISTANCE = 5000  # characters: farther apart than one default parent chunk (4000)

golden_set_path = DATA_DIR / "golden_set_augustine_debord.json"



class OkExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["ok"]
    anchors: list[str] = Field(min_length=1, max_length=5)
    min_hits: int
    model_validator: @model_validator(mode="after")
    def anchors_match_min_hits(self) -> "OkExpectation":
        if len(self.anchors) == 1 and self.min_hits == 1:
            return self
        elif (len(self.anchors) >= 2 or len(self.anchors) <= 5) and (
                2 <= self.min_hits <= self.min_hits):
            return self
        else:
            raise ValueError(f"{len(self.anchors)} anchors need at least {self.min_hits -1}..., got min_hits={self.min_hits}")

OkExpectation(label="ok", anchors=["a b c d"] * 4, min_hits=2)

class SilentExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["silent"]
    near_miss: bool
    absent_terms: list[str]


Expectation = Annotated[OkExpectation | SilentExpectation, Field(discriminator="label")]


class GoldenEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")


def load_golden_set(path: Path) -> list[dict]:
    """Reads the golden set and rejects it, before any run, if an entry could never be passed by any run
    or the set misses a composition row of docs/golden_set_spec.md.
    Raises one ValueError listing every problem, each naming the entry id and, where it applies, the book."""
    entries = json.loads(path.read_text())
    problems = []
    for i in entries:
        i["expected"]



load_golden_set(golden_set_path)
