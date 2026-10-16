"""The delivery stats card (CC-07): what the picker and the composer were handed, then and under the contract.

Artifact for DSH-234/246. Two sides, both from files already on disk, no API call:
  - recorded runs (set40_run1/2): the text the pipeline actually delivered pre-G1, which is what the picker and
    the composer saw;
  - the closing configuration (g2_identity_round): what they would see under the contract.
The sentence splitter is the one agent._sentences uses on a delivered unit, declared here so the count has a
protocol instead of a convention.
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import date
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "eval"
RUNS = ("set40_run1_2026-10-12_2135.json", "set40_run2_2026-10-12_2145.json")
IDENTITY = DATA / "g2_identity_round_2026-10-16.json"


def sentences(text: str) -> list[str]:
    """agent._sentences on one delivered unit: same regex, same whitespace collapse."""
    return [s for s in re.split(r"(?<=[.!?;:])\s+", re.sub(r"\s+", " ", text).strip()) if s.strip()]


def median(xs):
    return statistics.median(xs) if xs else None


def main() -> int:
    recorded = {"per_book": [], "per_entry": {}}
    for name in RUNS:
        for record in json.loads((DATA / name).read_text()):
            total = 0
            for cid in ("A", "B"):
                chunks = record["chunks"].get(cid) or []
                sents = sum(len(sentences(c)) for c in chunks)
                recorded["per_book"].append({"run": name, "id": record["id"], "corpus_id": cid,
                                            "chunks": len(chunks), "chars": sum(len(c) for c in chunks),
                                            "sentences": sents})
                total += sents
            recorded["per_entry"][name + "|" + record["id"]] = total

    ident = json.loads(IDENTITY.read_text())
    contract = {"per_entry": ident["reach"], "config": ident["config"]}

    out = {
        "what": "the delivered unit as the picker and the composer see it: recorded runs vs the closing config",
        "date": str(date.today()),
        "sentence_splitter": "re.split(r\"(?<=[.!?;:])\\s+\", re.sub(r\"\\s+\", \" \", text).strip()) -- agent._sentences",
        "recorded_runs": {
            "sources": list(RUNS),
            "per_book": {"chunks_median": median([r["chunks"] for r in recorded["per_book"]]),
                         "chars_median": median([r["chars"] for r in recorded["per_book"]]),
                         "sentences_median": median([r["sentences"] for r in recorded["per_book"]]),
                         "sentences_max": max(r["sentences"] for r in recorded["per_book"])},
            "per_entry_sentences_median": median(list(recorded["per_entry"].values())),
            "rows": recorded["per_book"],
        },
        "contract_closing_config": {
            "source": IDENTITY.name,
            "config": contract["config"],
            "units_per_book_median": {cid: median([r[cid]["units"] for r in contract["per_entry"]]) for cid in ("A", "B")},
            "sentences_per_book_median": {cid: median([r[cid]["sentences"] for r in contract["per_entry"]]) for cid in ("A", "B")},
            "sentences_joint_median": median([r["A"]["sentences"] + r["B"]["sentences"] for r in contract["per_entry"]]),
            "islands_median": {cid: median([r[cid]["islands"] for r in contract["per_entry"]]) for cid in ("A", "B")},
            "islands_max": {cid: max(r[cid]["islands"] for r in contract["per_entry"]) for cid in ("A", "B")},
            "two_sided": ident["summary"]["two_sided"],
            "rows": contract["per_entry"],
        },
    }
    dest = DATA / ("g2_delivery_stats_" + str(date.today()) + ".json")
    dest.write_text(json.dumps(out, indent=1))
    r, c = out["recorded_runs"], out["contract_closing_config"]
    print("saved", dest)
    print("recorded  : per-book sentences median", r["per_book"]["sentences_median"], "| per-entry median", r["per_entry_sentences_median"])
    print("contract  : per-book sentences median", c["sentences_per_book_median"], "| per-entry median", c["sentences_joint_median"])
    print("contract  : units median", c["units_per_book_median"], "| islands median", c["islands_median"], "max", c["islands_max"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

