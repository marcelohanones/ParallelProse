"""The exact-search reading of the closing round — the artifact for CC-04 (DSH-250).

Why. The ANN query is approximate in the tail: two identical queries can return different orders there, and the
ANN top-50 shares 47 of 50 children with the exact top-50 (the ANN's 50 sit inside the exact top 53). The exact
ranking is deterministic numpy over every stored child vector, so it separates "the measurement moved" from
"the retriever moved" — and it is the only reading of the bar that can be re-derived byte for byte.

Config comes from g2_reach.CLOSING_ROUND_CONFIG (DSH-247), never from a module constant: that inheritance error
is exactly what produced the withdrawn reproduction finding (DSH-244).

Cost: one embedding per entry and book = 40 embeddings, zero LLM calls. Saves, per entry and book, the probe, a
sha1 of its vector and both readings (exact and ANN), so a re-check of the numbers needs no further spend.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ParallelProse.g2_reach as G  # noqa: E402
from ParallelProse.quote_check import match_form  # noqa: E402

CONFIG = G.CLOSING_ROUND_CONFIG
BOOKS = ("A", "B")


def paragraphs_ranked(forms_ranked: list[str], mapping: dict[str, list[int]]) -> list[int]:
    """_as_paragraphs' rule, on forms: every paragraph the ranked children cover, dedup, best first."""
    out, seen = [], set()
    for form in forms_ranked:
        for index in mapping.get(form) or ():
            if index not in seen:
                seen.add(index)
                out.append(index)
                if len(out) >= G.MAX_SAVED:
                    return out
    return out


def admit(units: list[int], size_of: dict[int, int], cid: str) -> list[int]:
    """g2_reach._admit's rule, per book: the fraction first, then the joint cap in main()."""
    keep = units[:CONFIG["asked_k"][cid]]
    fraction_cap = int(CONFIG["fraction"] * G.book_chars(cid))
    while keep and sum(size_of[i] for i in keep) > fraction_cap:
        keep.pop()
    return keep


def main() -> int:
    entries = G.attested_entries()
    placement, mapping_of, embeddings, forms_of = {}, {}, {}, {}
    for cid in BOOKS:
        placement[cid] = G._child_paragraphs(cid)
        children = G.REGISTRY[cid].vector_store.get(include=["documents", "embeddings"])
        forms_of[cid] = [match_form(text) for text in children["documents"]]
        paragraphs = placement[cid][0]
        mapping_of[cid] = {}
        for form in forms_of[cid]:
            head, tail = form[:G.PLACE_PROBE], form[-G.PLACE_PROBE:]
            mapping_of[cid][form] = [i for i, paragraph in enumerate(paragraphs)
                                     if paragraph in form or head in paragraph or tail in paragraph]
        embeddings[cid] = np.array(children["embeddings"], dtype=np.float32)

    rows, probes, kept_by_book, size_by_book = [], {}, defaultdict(dict), defaultdict(dict)
    for cid in BOOKS:
        vector_store = G.REGISTRY[cid].vector_store
        paragraphs = placement[cid][0]
        for entry in entries:
            probe = G.formulations(entry.query)[0]
            query = np.array(vector_store.embeddings.embed_query(probe), dtype=np.float32)
            probes[entry.id + "|" + cid] = {"probe": probe,
                                            "vector_sha1": hashlib.sha1(query.tobytes()).hexdigest()[:16]}
            exact = [forms_of[cid][i] for i in np.argsort(np.linalg.norm(embeddings[cid] - query, axis=1),
                                                          kind="stable")]
            ann = [match_form(doc.page_content) for doc in vector_store.similarity_search(probe, k=CONFIG["deep_k"])]
            for label, ranked in (("exact", exact), ("ann", ann)):
                units = paragraphs_ranked(ranked, mapping_of[cid])
                size_by_book[(label, entry.id, cid)] = {i: len(paragraphs[i]) for i in units}
                kept_by_book[(label, entry.id)][cid] = admit(units, size_by_book[(label, entry.id, cid)], cid)

    reach = {label: [] for label in ("exact", "ann")}
    for label in ("exact", "ann"):
        for entry in entries:
            kept = {cid: list(kept_by_book[(label, entry.id)][cid]) for cid in BOOKS}
            while sum(sum(size_by_book[(label, entry.id, cid)][i] for i in kept[cid]) for cid in BOOKS) > CONFIG["cap"]:
                cid = max(BOOKS, key=lambda c: (len(kept[c]), c))
                if not kept[cid]:
                    break
                kept[cid].pop()
            row = {"id": entry.id, "two_sided": True}
            for cid in BOOKS:
                paragraphs = placement[cid][0]
                found = sum(1 for anchor in entry.expected[cid].anchors
                            if any(G._phrase_pattern(anchor).search(paragraphs[i]) for i in kept[cid]))
                passed = found >= entry.expected[cid].min_hits
                row["two_sided"] = row["two_sided"] and passed
                row[cid] = {"units": len(kept[cid]), "chars": sum(size_by_book[(label, entry.id, cid)][i] for i in kept[cid]),
                            "found": found, "need": entry.expected[cid].min_hits, "pass": passed,
                            "paragraphs": kept[cid]}
            reach[label].append(row)

    out = {"what": "the closing round read by exact search, side by side with the ANN query (CC-04 artifact)",
           "date": str(date.today()), "config": CONFIG, "cost": {"embeddings": 2 * len(entries), "llm_calls": 0},
           "summary": {label: {"two_sided": sum(1 for r in reach[label] if r["two_sided"]),
                               "per_book": {cid: sum(1 for r in reach[label] if r[cid]["pass"]) for cid in BOOKS}}
                       for label in ("exact", "ann")},
           "probes": probes, "rows": reach}
    dest = G.DATA_DIR / "eval" / ("g2_exact_round_" + str(date.today()) + ".json")
    dest.write_text(json.dumps(out, indent=1))
    print("saved", dest)
    print("exact:", out["summary"]["exact"], "| ann:", out["summary"]["ann"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

