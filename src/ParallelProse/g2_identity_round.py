"""G3's missing card, measured: the closing dense round re-run with the IDENTITY of every delivered unit
saved, not only its size.

Why this file exists. The save path in g2_reach.py writes {"id": str(i), "chars": ...} -- the position in the
fused ranking, never the unit (DSH-232). The paragraph index is produced by _as_paragraphs and dropped at the
save, so the round's own file cannot answer "which paragraph was delivered", which is what the delivery bar
needs and what the address question is about. This script re-runs the same configuration through the same
functions and keeps the identity.

Cost: 20 entries x 2 books x 1 formulation = 40 embeddings, zero LLM calls.
Check: the sizes of the 60-deep window must reproduce g2_dense_round_2026-10-16.json exactly; every mismatch
is reported per entry and book instead of being assumed away.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ParallelProse.g2_reach as G  # noqa: E402
import ParallelProse.quote_check as Q  # noqa: E402

CAP = 88120
ROUND_DEEP_K = 800  # the round ran deep_k=800; g2_reach.DEEP_K is 200 and does NOT reproduce the record (DSH-244)
FRACTION = 0.15
ASKED_K = {"A": 32, "B": 26}
PREVIOUS = G.DATA_DIR / "eval" / "g2_dense_round_2026-10-16.json"


def sentences_of(text: str) -> list[str]:
    """The same split agent._sentences uses on a delivered unit, so the count is the picker's list size."""
    return [s for s in re.split(r"(?<=[.!?;:])\s+", re.sub(r"\s+", " ", text).strip()) if s.strip()]


def admit_positions(sizes: list[int], k: int, fraction_cap: int) -> list[int]:
    """The rule of g2_reach._admit, returning the surviving POSITIONS instead of a count: the per-book
    fraction first, then the joint cap, dropping the deepest unit of whichever book holds more."""
    keep = list(range(min(k, len(sizes))))
    while keep and sum(sizes[i] for i in keep) > fraction_cap:
        keep.pop()
    return keep


def main() -> int:
    entries = G.attested_entries()
    books = sorted(entries[0].expected)
    previous = json.loads(PREVIOUS.read_text())
    prev_delivery = previous["units"]["paragraph"]["rules"]["first"]["delivery"]
    fraction_cap = {cid: int(FRACTION * G.book_chars(cid)) for cid in books}

    delivery: dict[str, list[dict]] = {}
    texts: dict[str, dict[str, str]] = {}
    check: dict[str, dict] = {}
    embeddings_issued = 0

    managers = []
    try:
        for cid in books:
            run, manager = G._channel_runner(cid, "dense", ROUND_DEEP_K, "paragraph")
            managers.append(manager)
            placement = G._child_paragraphs(cid)
            for entry in entries:
                probe = G.formulations(entry.query)[0]
                pairs = G._ranking(run, cid, probe, "paragraph", placement)
                embeddings_issued += 1
                key = entry.id + "|" + cid
                window = [{"rank": i, "unit": unit, "chars": len(text)}
                          for i, (unit, text) in enumerate(pairs[:G.MAX_SAVED])]
                delivery[key] = window
                texts[key] = {unit: text for unit, text in pairs[:G.MAX_SAVED]}
                old = [u["chars"] for u in prev_delivery[key]][:len(window)]
                new = [u["chars"] for u in window]
                check[key] = {"n": len(window), "same_sizes": new == old,
                              "first_diff": next((i for i, (a, b) in enumerate(zip(new, old)) if a != b), None)}
    finally:
        for manager in managers:
            if manager is not None:
                manager.__exit__(None, None, None)

    admitted: dict[str, dict] = {}
    reach: list[dict] = []
    for entry in entries:
        kept: dict[str, list[dict]] = {}
        for cid in books:
            key = entry.id + "|" + cid
            window = delivery[key]
            sizes = [u["chars"] for u in window]
            positions = admit_positions(sizes, ASKED_K[cid], fraction_cap[cid])
            kept[cid] = [window[i] for i in positions]
        while sum(sum(u["chars"] for u in kept[cid]) for cid in books) > CAP:
            cid = max(books, key=lambda c: (len(kept[c]), c))
            if not kept[cid]:
                break
            kept[cid].pop()
        row = {"id": entry.id, "two_sided": True}
        for cid in books:
            key = entry.id + "|" + cid
            units = [u["unit"] for u in kept[cid]]
            admitted[key] = {"k": len(units), "chars": sum(u["chars"] for u in kept[cid]), "units": units}
            idx = sorted(int(u) for u in units)
            islands = 1 + sum(1 for a, b in zip(idx, idx[1:]) if b != a + 1) if idx else 0
            sents = sum(len(sentences_of(texts[key][u])) for u in units)
            found = sum(1 for anchor in entry.expected[cid].anchors
                        if any(G._phrase_pattern(anchor).search(texts[key][u]) for u in units))
            passed = found >= entry.expected[cid].min_hits
            row["two_sided"] = row["two_sided"] and passed
            row[cid] = {"found": found, "need": entry.expected[cid].min_hits, "pass": passed,
                        "units": len(units), "chars": admitted[key]["chars"], "islands": islands, "sentences": sents}
        reach.append(row)

    mismatches = {k: v for k, v in check.items() if not v["same_sizes"]}
    joint = [admitted[e.id + "|A"]["chars"] + admitted[e.id + "|B"]["chars"] for e in entries]
    out = {
        "what": "the closing dense round re-run with the delivered unit identity saved (G3 missing card)",
        "date": str(date.today()),
        "config": {"channel": "dense", "deep_k": ROUND_DEEP_K, "unit": "paragraph", "rule": "F1 alone",
                   "asked_k": ASKED_K, "cap": CAP, "fraction": FRACTION, "fraction_cap": fraction_cap},
        "cost": {"embeddings": embeddings_issued, "llm_calls": 0},
        "reproduction_check": {"windows": len(check), "mismatched": len(mismatches), "detail": mismatches},
        "summary": {
            "two_sided": sum(1 for r in reach if r["two_sided"]),
            "per_book": {cid: sum(1 for r in reach if r[cid]["pass"]) for cid in books},
            "joint_chars": {"median": statistics.median(joint), "max": max(joint)},
            "sentences_joint_median": statistics.median([r["A"]["sentences"] + r["B"]["sentences"] for r in reach]),
            "islands": {cid: {"median": statistics.median([r[cid]["islands"] for r in reach]),
                              "max": max(r[cid]["islands"] for r in reach)} for cid in books},
        },
        "delivery": delivery,
        "admitted": admitted,
        "reach": reach,
    }
    dest = G.DATA_DIR / "eval" / ("g2_identity_round_" + str(date.today()) + ".json")
    dest.write_text(json.dumps(out, indent=1))
    print("saved", dest)
    print("reproduction: mismatched windows =", len(mismatches), "of", len(check))
    print("cost: embeddings =", embeddings_issued, "| llm calls = 0")
    print("two-sided:", out["summary"]["two_sided"], "| per book:", out["summary"]["per_book"])
    print("joint chars:", out["summary"]["joint_chars"])
    print("sentences per entry (median):", out["summary"]["sentences_joint_median"])
    print("islands:", out["summary"]["islands"])
    for r in reach:
        print("  ", r["id"], "A", r["A"]["found"], "/", r["A"]["need"], "u", r["A"]["units"], "s", r["A"]["sentences"],
              "isl", r["A"]["islands"], "| B", r["B"]["found"], "/", r["B"]["need"], "u", r["B"]["units"],
              "s", r["B"]["sentences"], "isl", r["B"]["islands"], "|", "PASS" if r["two_sided"] else "FAIL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

