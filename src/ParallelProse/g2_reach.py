"""G2's measuring stick: what one probe reaches, per book, on the span-attested sample.

The sample is the 20 golden entries where both books carry a verified verbatim span (Markim's decision 4) --
the only non-circular ground truth the project has. Reach is mechanical: the entry's anchor appears inside some
parent the probe returned, matched the way the golden-set loader matches it, one parent at a time. No model sits
in the measured path, and the retrievers are called directly, so the same probe returns the same set twice.

Three readings off one ranking, because "it did not come back" and "it came back too deep to be handed on" need
different mechanisms:
  reach_at_k   -- does the entry pass min_hits at the production k? (the headline number)
  pass_at_k    -- the whole curve, so "raise k" is answered with a number instead of a reflex
  ceiling      -- the entries no k can pass here, by name: G2's bar is never set above this

The ranking is read once per (entry, book, channel) and the three readings share it: a probe embedded twice is
the same number paid for twice.

Cost. `channel="bm25"` is local and free: BM25 reads the children already in the Chroma collection and ranks
them in process. `channel="dense"` and `channel="ensemble"` embed each probe (~14 tokens; 20 entries over two
books is ~560 tokens per channel, US$0.00002 at text-embedding-3-small) -- a spend, however small, so it is never
the default and `main` refuses it without --spend. Raising k costs nothing extra: the embedding is of the probe,
and k only decides how many neighbours come back.
"""
from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from datetime import date
from hashlib import sha1
from typing import TypedDict

from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

from ParallelProse.catalog import CATALOG, DATA_DIR
from ParallelProse.evaluation import load_golden_set, golden_set_path, _phrase_pattern
from ParallelProse.mcp_tools import REGISTRY
from ParallelProse.quote_check import book_paragraphs, match_form
from ParallelProse.textform import STOPWORDS

PRODUCTION_K = 4  # BM25Retriever's default k, and parent_retriever's: the window production actually hands on
DEEP_K = 200      # children deep enough to tell "buried" from "absent"
CURVE = (4, 6, 8, 12, 16, 20, 30, 50)
CHANNELS = ("bm25", "dense", "ensemble")
UNITS = ("parent", "paragraph")
MAX_SAVED = 60  # units of the delivery kept per entry and book: deeper than any k the budget can buy
PLACE_PROBE = 60  # chars of a child's head and tail used to find the paragraphs it straddles into


# MARK: round configuration -- DSH-247
# Consolidates the measured configuration for a round in one place, preventing the error of using a module-level
# constant (DEEP_K=200) when the round specifies a different value (deep_k=800). This is saved with each round's
# output and checked by reproduction scripts. Add a new round here when measuring; never let config values live
# only in piecemeal command-line arguments or scattered constants.
class RoundConfig(TypedDict):
	"""Configuration for a measurement round."""
	channel: str  # "bm25", "dense", or "ensemble"
	deep_k: int  # how deep to rank children before parent dedup
	unit: str  # "parent" or "paragraph" (the delivered unit)
	rule: str  # e.g., "F1 alone" or "F1+F2+F3"
	asked_k: dict[str, int]  # per-book k (e.g., {"A": 32, "B": 26})
	cap: int  # character ceiling per query
	fraction: float  # per-book fraction ceiling (e.g., 0.15)


CLOSING_ROUND_CONFIG: RoundConfig = {
	"channel": "dense",
	"deep_k": 800,
	"unit": "paragraph",
	"rule": "F1 alone",
	"asked_k": {"A": 32, "B": 26},
	"cap": 88120,
	"fraction": 0.15,
}


# MARK: the probe set (candidate, measured by the round -- not on the retrieval path until it passes)
# The contract asks for three fixed formulations per side (§6) and condition 5 asks the derivation to be a pure
# function of the document's query. These three are deletions: each one removes tokens from the query and adds
# none, so no formulation can carry vocabulary the query did not already have -- which is what keeps a model out
# of the probe (zero LLM calls) and keeps the anchor out of the probe. Deletion can still create an adjacency the
# query lacked, so condition 6's run check still applies and every rejection is recorded (DSH-190).
FRAME = frozenset("""what why how when where which who whom whose is are was were do does did can could will
would has have had the a an""".split())


def formulations(query: str) -> tuple[str, str, str]:
    """The three fixed formulations, in order: the query as written; its content terms alone, in order; the query
    without its leading interrogative frame. Same query in, same three out -- no model, no state, no catalogue."""
    words = query.strip().rstrip("?.!").split()
    content = [w for w in words if len(w.strip(",;:.")) > 2
               and w.strip(",;:.").lower() not in STOPWORDS]
    rest = list(words)
    while rest and rest[0].strip(",;:.").lower() in FRAME:
        rest.pop(0)
    return query, " ".join(content), " ".join(rest)


def attested_entries():
    """The 20 entries both books are attested on. Raises if the golden set no longer loads -- the loader checks
    every anchor against the current paragraphs, so a rebuild that moved them is caught here, not downstream."""
    return [entry for entry in load_golden_set(golden_set_path)
            if all(expectation.label == "ok" for expectation in entry.expected.values())]


def _deep_bm25(retrieval, deep_k: int):
    """BM25 over the same children the collection holds, k raised: `make_bm_25_retriever` with a deeper window."""
    children = retrieval.vector_store.get(include=["documents", "metadatas"])
    docs = [Document(page_content=text, metadata=meta)
            for text, meta in zip(children["documents"], children["metadatas"])]
    bm25 = BM25Retriever.from_documents(documents=docs, bm25_params={"k1": 1.5, "b": 0.75})
    bm25.k = deep_k
    return bm25


def _digest(doc) -> str:
    return sha1(doc.page_content.encode()).hexdigest()[:12]


def _with_ids(retrieval, children: list):
    """The parents of these children, best first, each carrying the docstore key it came from. `parents_of` drops
    the key, and the key is what makes the delivery -- and so condition 3's fraction -- conferrable per entry."""
    ids = list(dict.fromkeys(child.metadata["doc_id"] for child in children))
    parents = retrieval.doc_store.mget(ids)
    return [(key, parent) for key, parent in zip(ids, parents) if parent is not None]


@contextmanager
def _deep_dense(retrieval, deep_k: int):
    """The production parent retriever with its child window raised, restored on the way out: REGISTRY is shared
    with the production tools, so a measurement never leaves them widened."""
    before = retrieval.parent_retriever.search_kwargs
    retrieval.parent_retriever.search_kwargs = {**before, "k": deep_k}
    try:
        yield retrieval.parent_retriever
    finally:
        retrieval.parent_retriever.search_kwargs = before


def _channel_runner(corpus_id: str, channel: str, deep_k: int, unit: str = "parent"):
    """One callable per (book, channel) returning ranked parents for a probe, built once and reused across the
    sample. `ensemble` is `make_ensemble_retriever`'s construction -- the same two halves, the same 0.5/0.5 RRF --
    with both windows deep, since the shipped method fixes its halves at the production k."""
    retrieval = REGISTRY[corpus_id]
    if channel == "bm25":
        bm25 = _deep_bm25(retrieval, deep_k)
        if unit == "paragraph":  # the paragraph ranking is keyed on the child's rank, before the parent dedup
            return (lambda probe: bm25.invoke(probe)), None
        return (lambda probe: _with_ids(retrieval, bm25.invoke(probe))), None
    if channel == "dense":
        manager = _deep_dense(retrieval, deep_k)
        dense = manager.__enter__()
        if unit == "paragraph":  # the child hits themselves, so the paragraph ranking keeps the child's order
            return (lambda probe: retrieval.vector_store.similarity_search(probe, k=deep_k)), manager
        return (lambda probe: _with_ids(retrieval, retrieval.vector_store.similarity_search(probe, k=deep_k))),             manager
    if channel == "ensemble":
        bm25_half = _deep_bm25(retrieval, deep_k) | RunnableLambda(retrieval.parents_of)
        manager = _deep_dense(retrieval, deep_k)
        dense_half = manager.__enter__()
        ensemble = EnsembleRetriever(retrievers=[bm25_half, dense_half], weights=[0.5, 0.5])
        # the RRF merge hands back parents without the key either half fetched them by, so the identity here is
        # a content digest -- stable inside one build, which is all a saved delivery can claim anyway (CC-205)
        return (lambda probe: [(_digest(doc), doc) for doc in ensemble.invoke(probe)]), manager
    raise ValueError(f"unknown channel {channel!r}")


def _child_paragraphs(corpus_id: str):
    """Every embedded child mapped to EVERY paragraph it covers, plus the paragraphs themselves. One paragraph per
    child was wrong and it cost a real entry: B's g18 anchor sits in a 111-char paragraph that lives whole inside
    child 7, which BM25 ranks 9th -- and a first-150-chars rule placed that child nowhere, because it straddles two
    paragraphs, so the paragraph was never delivered. A straddler covers its paragraphs; it does not lose them."""
    paragraphs, _ = book_paragraphs(CATALOG[corpus_id])
    children = REGISTRY[corpus_id].vector_store.get(include=["documents"])
    mapping, unplaced = {}, 0
    for text in children["documents"]:
        form = match_form(text)
        head, tail = form[:PLACE_PROBE], form[-PLACE_PROBE:]
        covered = [i for i, paragraph in enumerate(paragraphs)
                   if paragraph in form or head in paragraph or tail in paragraph]
        unplaced += not covered
        mapping[form] = covered
    return paragraphs, mapping, unplaced, len(children["documents"])


def _as_paragraphs(corpus_id: str, children: list, placement) -> list[str]:
    """The ranked children turned into the delivered unit the contract asks for (`passage` = paragraph, §6):
    the paragraph each ranked child sits in, deduplicated, best first. Never shallower than the parent ranking --
    a parent covers ~2.7 paragraphs of A, so it can carry an anchor whose own child never ranked."""
    paragraphs, mapping, _, _ = placement
    ranked, identity, seen = [], [], set()
    for child in children:
        for index in mapping.get(match_form(child.page_content)) or ():
            if index in seen:
                continue
            seen.add(index)
            ranked.append(paragraphs[index])
            identity.append(index)
    return ranked, identity


def rank_table(channel: str = "bm25", deep_k: int = DEEP_K, entries=None, unit: str = "parent",
               config: RoundConfig | None = None) -> dict:
    """One rank per anchor: the position of the first returned parent containing it, or None when no parent in
    the deep window contains it. None is the only answer no k can change, which is why it is kept distinct.
    Keyed (entry id, book); the probe is the entry's query exactly as written, never reformulated.

    If config is passed, it overrides channel, deep_k, and unit with the config's values. This ensures scripts
    that reproduce a round use the exact configuration that was measured, not module-level defaults."""
    if config is not None:
        channel, deep_k, unit = config["channel"], config["deep_k"], config["unit"]
    entries = entries if entries is not None else attested_entries()
    books = sorted(entries[0].expected)
    table, delivery, managers, placement = {}, {}, [], {}
    try:
        for corpus_id in books:
            run, manager = _channel_runner(corpus_id, channel, deep_k, unit)
            managers.append(manager)
            if unit == "paragraph":
                placement[corpus_id] = _child_paragraphs(corpus_id)
            for entry in entries:
                returned = run(entry.query)
                if unit == "paragraph":
                    texts, identity = _as_paragraphs(corpus_id, returned, placement[corpus_id])
                else:
                    texts = [match_form(parent.page_content) for key, parent in returned]
                    identity = [key for key, parent in returned]
                table[(entry.id, corpus_id)] = [
                    next((i + 1 for i, text in enumerate(texts) if _phrase_pattern(anchor).search(text)), None)
                    for anchor in entry.expected[corpus_id].anchors]
                delivery[(entry.id, corpus_id)] = [{"id": str(unit_id), "chars": len(text)}
                                                   for unit_id, text in zip(identity, texts[:MAX_SAVED])]
    finally:
        for manager in managers:
            if manager is not None:
                manager.__exit__(None, None, None)
    return table, delivery


def _passes(entry, corpus_id: str, ranks: list[int | None], k: int) -> bool:
    hits = sum(1 for rank in ranks if rank is not None and rank <= k)
    return hits >= entry.expected[corpus_id].min_hits


def reach_at_k(table: dict, entries, k: int = PRODUCTION_K) -> dict:
    """The headline reading: per book and -- the number that closes G2 -- how many entries pass on BOTH books in
    the same probe. A book's own score says nothing by itself: 20/20 on one side with 0/20 on the other is the
    silence the stage exists not to report."""
    books = sorted(entries[0].expected)
    rows, two_sided = [], 0
    for entry in entries:
        passed = {cid: _passes(entry, cid, table[(entry.id, cid)], k) for cid in books}
        two_sided += all(passed.values())
        rows.append({"id": entry.id, "wording": entry.wording, "specificity": entry.specificity,
                     "passed": passed, "ranks": {cid: table[(entry.id, cid)] for cid in books}})
    per_book = {cid: sum(row["passed"][cid] for row in rows) for cid in books}
    return {"k": k, "n": len(entries), "per_book": per_book, "two_sided": two_sided, "rows": rows}


def pass_at_k(table: dict, entries, curve=CURVE) -> list[dict]:
    """The curve, so 'return more' is priced instead of assumed: one row per k, counted in parents handed on."""
    books = sorted(entries[0].expected)
    return [{"k": k,
             "per_book": {cid: sum(_passes(entry, cid, table[(entry.id, cid)], k) for entry in entries)
                          for cid in books},
             "two_sided": sum(all(_passes(entry, cid, table[(entry.id, cid)], k) for cid in books)
                              for entry in entries)}
            for k in curve]


def ceiling(table: dict, entries) -> dict:
    """The entries whose anchors are nowhere in THIS window, by name -- not a ceiling of the channel or the unit.
    Measured: BM25's parent figure is 15/20 at deep_k=200, 16/20 at 400 and 20/20 at 800, so the number names the
    window it was read at and nothing more. Reach at a declared character budget is the quantity that decides."""
    books = sorted(entries[0].expected)
    out = {}
    for corpus_id in books:
        lost = [entry.id for entry in entries
                if sum(1 for rank in table[(entry.id, corpus_id)] if rank is not None)
                < entry.expected[corpus_id].min_hits]
        out[corpus_id] = {"unreachable_entries": lost, "ceiling": len(entries) - len(lost)}
    two_sided_lost = {entry_id for data in out.values() for entry_id in data["unreachable_entries"]}
    out["two_sided"] = {"unreachable_entries": sorted(two_sided_lost),
                        "ceiling": len(entries) - len(two_sided_lost)}
    return out


def book_chars(corpus_id: str) -> int:
    """The book's size in the same form the delivery is measured in -- the denominator of condition 3's fraction."""
    paragraphs, _ = book_paragraphs(CATALOG[corpus_id])
    return sum(len(paragraph) for paragraph in paragraphs)


def _admit(sizes_by_book: dict, k_by_book: dict, cap: int, fraction_cap: dict) -> tuple[dict, int]:
    """What one entry actually hands over, under both of condition 3's halves. The per-book fraction is applied
    first, then the joint cap by truncating the tail -- dropping the deepest admitted unit, which is the last one
    of whichever book has more admitted (both sides are prefixes of a ranking, so more admitted means deeper).
    Returns the surviving k per book and the chars used, so the bar is read on what was delivered, not on what
    was asked for."""
    admitted = {cid: list(sizes[:k_by_book[cid]]) for cid, sizes in sizes_by_book.items()}
    for cid, units in admitted.items():
        while units and sum(units) > fraction_cap[cid]:
            units.pop()
    while sum(sum(units) for units in admitted.values()) > cap:
        cid = max(admitted, key=lambda c: (len(admitted[c]), c))
        if not admitted[cid]:
            break
        admitted[cid].pop()
    return ({cid: len(units) for cid, units in admitted.items()},
            sum(sum(units) for units in admitted.values()))


def reach_at_budget(table: dict, delivery: dict, entries, cap: int, fraction: float = 0.15,
                    rule: str = "max", depth: int | None = None) -> dict:
    """The best two-sided reach a character cap can buy, with condition 3 verified per entry rather than modelled.
    Sweeps every (kA, kB); for each entry, `_admit` truncates to what the caps allow and the pass is read on the
    truncated delivery. `rule="max"` is the literal reading of a per-entry condition -- every entry fits, because
    an entry that does not fit is truncated until it does. `rule="p95"` keeps the asked-for k and only reports the
    entries above the cap, which is the looser reading; both are returned side by side so the choice is visible.

    The comparison this exists for -- parent against paragraph -- is only informative where the parent unit itself
    gets near the bar at the same cap: at reach near zero on both sides, "paragraph >= parent - 1" is satisfied by
    two numbers that mean nothing (DSH-203). `decides` carries that verdict rather than leaving it to the reader."""
    books = sorted(entries[0].expected)
    sizes = {key: [unit["chars"] for unit in units] for key, units in delivery.items()}
    depth = depth or min(len(units) for units in sizes.values())
    fraction_cap = {cid: int(fraction * book_chars(cid)) for cid in books}

    best = None
    for k_a in range(1, depth + 1):
        for k_b in range(1, depth + 1):
            asked = {books[0]: k_a, books[1]: k_b}
            per_entry, over = [], []
            per_book = {cid: 0 for cid in books}
            two_sided = 0
            for entry in entries:
                if rule == "p95":  # the looser reading: nothing is truncated, the cap binds the p95 instead
                    keep = asked
                    used = sum(sum(sizes[(entry.id, cid)][:asked[cid]]) for cid in books)
                    if used > cap:
                        over.append(entry.id)
                else:
                    keep, used = _admit({cid: sizes[(entry.id, cid)] for cid in books}, asked, cap, fraction_cap)
                per_entry.append(used)
                passed = {cid: _passes(entry, cid, table[(entry.id, cid)], keep[cid]) for cid in books}
                for cid in books:
                    per_book[cid] += passed[cid]
                two_sided += all(passed.values())
            if rule == "p95" and sorted(per_entry)[int(0.95 * (len(per_entry) - 1))] > cap:
                continue  # the constraint of the looser reading, which has to bind something
            key = (two_sided, min(per_book.values()), -max(per_entry))
            if best is None or key > best[0]:
                best = (key, {"rule": rule, "cap": cap, "fraction": fraction, "asked_k": asked,
                              "per_book": per_book, "two_sided": two_sided, "n": len(entries),
                              "chars_max": max(per_entry),
                              "chars_p95": sorted(per_entry)[int(0.95 * (len(per_entry) - 1))],
                              "entries_over_cap": over})
    return best[1] if best else {"cap": cap, "two_sided": 0, "note": "no (kA,kB) fits this cap"}


def unit_verdict(parent: dict, paragraph: dict, floor: int = 10) -> dict:
    """DSH-203's rule, written down instead of eyeballed: the parent-vs-paragraph comparison only decides where
    the parent unit itself reaches `floor` at that cap. Below it, both units are near zero and the comparison is
    satisfied in the void."""
    if parent["two_sided"] < floor:
        return {"decides": False, "why": f"parent reaches {parent['two_sided']}/{parent['n']} at this cap, "
                                         f"below the {floor} floor: the comparison is vacuous"}
    keeps = paragraph["two_sided"] >= parent["two_sided"] - 1
    return {"decides": True, "keeps_paragraph": keeps,
            "why": f"paragraph {paragraph['two_sided']} vs parent {parent['two_sided']} two-sided"}


def report(channel: str, deep_k: int = DEEP_K, unit: str = "parent") -> dict:
    """The three readings off one ranking: what a G2 round reports, per channel and delivered unit."""
    entries = attested_entries()
    table, delivery = rank_table(channel, deep_k, entries, unit)
    return {"channel": channel, "deep_k": deep_k, "unit": unit,
            "entries": [entry.id for entry in entries],
            "head": reach_at_k(table, entries), "curve": pass_at_k(table, entries),
            "located_within_window": ceiling(table, entries), "table": table, "delivery": delivery}


def save_report(data: dict, directory=None) -> str:
    """The rank table to disk, so every weighting, every k and every budget question after it is local and free.
    A printed table dies with the terminal, and the ranking is the only part of a round that was paid for."""
    directory = directory or (DATA_DIR / "eval")
    path = directory / f"g2_reach_{data['channel']}_{data['unit']}_{date.today()}.json"
    path.write_text(json.dumps({**data,
                                "table": {f"{eid}|{cid}": ranks for (eid, cid), ranks in data["table"].items()},
                                "delivery": {f"{eid}|{cid}": units
                                             for (eid, cid), units in data["delivery"].items()}},
                               indent=1, ensure_ascii=False))
    return str(path)


def print_report(data: dict) -> None:
    head, books = data["head"], sorted(data["head"]["per_book"])
    print(f"\n=== channel={data['channel']}  unit={data['unit']}  deep_k={data['deep_k']}  n={head['n']} ===")
    print(f"at production k={head['k']}: per book {head['per_book']}  TWO-SIDED {head['two_sided']}/{head['n']}")
    print("\nid    wording      specificity  ranks per book (None = not in the deep window)")
    for row in head["rows"]:
        print(f"{row['id']}  {row['wording']:11s}  {row['specificity']:11s}  " +
              "  ".join(f"{cid} {row['ranks'][cid]}{'' if row['passed'][cid] else ' MISS'}" for cid in books))
    print(f"\npass-at-k, k counted in {data['unit']}s handed on")
    for row in data["curve"]:
        print(f"  k={row['k']:>3}  {row['per_book']}  two-sided {row['two_sided']}/{head['n']}")
    print(f"located within the window (deep_k={data['deep_k']}) -- NOT a ceiling: a deeper window locates more")
    for cid, info in data["located_within_window"].items():
        print(f"  {cid:>9}: {info['ceiling']}/{head['n']}  lost: {info['unreachable_entries']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="bm25", choices=[*CHANNELS, "all"])
    parser.add_argument("--unit", default="parent", choices=UNITS,
                        help="what gets handed on: today's parent chunk, or the contract's paragraph (§6)")
    parser.add_argument("--deep-k", type=int, default=DEEP_K)
    parser.add_argument("--save", action="store_true", help="persist the rank table under data/eval")
    parser.add_argument("--spend", action="store_true",
                        help="required for dense/ensemble/all: they embed every probe")
    args = parser.parse_args()
    channels = CHANNELS if args.channel == "all" else (args.channel,)
    if any(channel != "bm25" for channel in channels) and not args.spend:
        raise SystemExit("dense/ensemble embed every probe (~US$0.00002 per channel over the sample). "
                         "Pass --spend to say so out loud.")
    for channel in channels:
        data = report(channel, args.deep_k, args.unit)
        print_report(data)
        if args.save:
            print(f"saved: {save_report(data)}")


if __name__ == "__main__":
    main()


# MARK: today's delivery, re-measured without a graph run
RECORDED_RUNS = ("set40_run1_2026-10-12_2135.json", "set40_run2_2026-10-12_2145.json")


def _recorded_calls(paths=RECORDED_RUNS) -> list[dict]:
    """The last iteration's retrieval calls of every recorded entry and book. Only the last one, because the
    retriever node REPLACES a book's chunks on a retry (`corpora_updates[corpus_id]["chunks"] = chunks_list`), so
    what the composer and E see is that iteration's result, not the accumulation of all of them."""
    calls = []
    for name in paths:
        for record in json.loads((DATA_DIR / "eval" / name).read_text()):
            for corpus_id, slot in record["retrieval"].items():
                lineage = slot.get("lineage") or []
                if not lineage:
                    continue
                last = max(call.get("iteration", 0) for call in lineage)
                calls.append({"run": name, "id": record["id"], "corpus_id": corpus_id,
                              "calls": [call for call in lineage if call.get("iteration", 0) == last]})
    return calls


def replay_recorded_delivery(paths=RECORDED_RUNS) -> dict:
    """What today's mechanism would hand over NOW: the recorded tool and query of every call, replayed against the
    rebuilt stores. No model anywhere -- the agent's choices are read from the record instead of made again -- so
    the only cost is embedding each recorded query. This is the denominator of condition 3's cap, re-measured after
    G1 rather than inherited from a pre-G1 run (DSH-205)."""
    per_book, per_entry, skipped = [], {}, []
    for item in _recorded_calls(paths):
        retrieval = REGISTRY[item["corpus_id"]]
        chunks = []
        for call in item["calls"]:
            query = call["args"]["query"]
            if call["tool"] == "call_bm_25_retriever":
                docs = retrieval.make_bm_25_retriever().invoke(query)
            elif call["tool"] == "call_ensemble_retriever":
                docs = retrieval.make_ensemble_retriever().invoke(query)
            elif call["tool"] == "call_search_self_query":
                skipped.append({"id": item["id"], "corpus_id": item["corpus_id"], "query": query})
                continue  # SelfQueryRetriever.from_llm makes a model call, and this replay is a zero-LLM run
            else:
                docs = retrieval.parent_retriever.invoke(query)
            chunks.extend(doc.page_content for doc in docs)
        used = sum(len(chunk) for chunk in chunks)
        per_book.append({"run": item["run"], "id": item["id"], "corpus_id": item["corpus_id"],
                         "chunks": len(chunks), "chars": used})
        per_entry[(item["run"], item["id"])] = per_entry.get((item["run"], item["id"]), 0) + used
    joint = sorted(per_entry.values())
    chars = sorted(row["chars"] for row in per_book)

    def at(values, quantile):
        return values[int(quantile * (len(values) - 1))]

    return {"calls_replayed": sum(len(item["calls"]) for item in _recorded_calls(paths)),
            "skipped_self_query": skipped,
            "book_entries": len(per_book), "entries": len(joint),
            "per_book": {"median": at(chars, 0.5), "p95": at(chars, 0.95), "max": chars[-1]},
            "joint": {"median": at(joint, 0.5), "p95": at(joint, 0.95), "max": joint[-1]},
            "chunks": {"median": at(sorted(r["chunks"] for r in per_book), 0.5),
                       "max": max(r["chunks"] for r in per_book)},
            "rows": per_book}


# MARK: the probe set measured, one embedding pass serving every fusion rule
def _ranking(run, corpus_id: str, probe: str, unit: str, placement) -> list[tuple[str, str]]:
    returned = run(probe)
    if unit == "paragraph":
        texts, identity = _as_paragraphs(corpus_id, returned, placement)
        return [(str(index), text) for index, text in zip(identity, texts)]
    return [(key, match_form(parent.page_content)) for key, parent in returned]


def _fuse(rankings: list[list[tuple[str, str]]], rule: str, rrf_k: int = 60) -> list[str]:
    """One list out of several. `min_rank` keeps each unit's best position; `rrf` adds 1/(k+position) across the
    rankings, so a unit several formulations agree on outranks one a single formulation loved. `first` is F1 alone,
    the baseline the fusion has to beat."""
    if rule == "first":
        return [text for _, text in rankings[0]]
    score, text_of = {}, {}
    for ranking in rankings:
        for position, (key, text) in enumerate(ranking, 1):
            text_of[key] = text
            if rule == "rrf":
                score[key] = score.get(key, 0.0) + 1.0 / (rrf_k + position)
            else:
                score[key] = max(score.get(key, 0.0), 1.0 / position)
    return [text_of[key] for key in sorted(score, key=lambda key: -score[key])]


def probe_set_report(channel: str = "bm25", deep_k: int = DEEP_K, unit: str = "parent",
                     rules=("first", "rrf", "min_rank")) -> dict:
    """Every fusion rule off ONE pass of embeddings: the three formulations are embedded once per book and entry,
    and the rules only re-sort what came back. Returns a table and a delivery per rule, ready for the bar."""
    entries = attested_entries()
    books = sorted(entries[0].expected)
    out = {rule: {"table": {}, "delivery": {}} for rule in rules}
    managers = []
    try:
        for corpus_id in books:
            run, manager = _channel_runner(corpus_id, channel, deep_k, unit)
            managers.append(manager)
            placement = _child_paragraphs(corpus_id) if unit == "paragraph" else None
            for entry in entries:
                rankings = [_ranking(run, corpus_id, probe, unit, placement)
                            for probe in formulations(entry.query)]
                for rule in rules:
                    texts = _fuse(rankings, rule)
                    out[rule]["table"][(entry.id, corpus_id)] = [
                        next((i + 1 for i, text in enumerate(texts) if _phrase_pattern(anchor).search(text)), None)
                        for anchor in entry.expected[corpus_id].anchors]
                    out[rule]["delivery"][(entry.id, corpus_id)] = [{"id": str(i), "chars": len(text)}
                                                                    for i, text in enumerate(texts[:MAX_SAVED])]
    finally:
        for manager in managers:
            if manager is not None:
                manager.__exit__(None, None, None)
    return {"channel": channel, "unit": unit, "deep_k": deep_k, "entries": [e.id for e in entries], "rules": out}
