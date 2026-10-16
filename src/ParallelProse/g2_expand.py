"""G2's expansion round: the second probe, with vocabulary taken from the material itself.

The bar of 14/20 two-sided is met (17/20 measured, DSH-208/210) by the dense channel delivering passages with
one probe, F1. What is left has a name: three entries of book A -- g02, g22, g24 -- whose second anchor sits at
paragraph rank 59, 59 and 194. No character cap the composer can afford buys that depth, so the only mechanism
left is the one the editorial contract already asked for: re-probe with the vocabulary the FIRST pass brought
back (pseudo-relevance feedback, part 2 of the stage-2 problem statement).

What the contract forbids, and how this module obeys it:

  * no model writes the probe. \`expansion_terms\` counts words in the passages the first pass already returned;
    the tokenizer is the project's own; the ranking of terms is a pure function (document frequency, then
    frequency, then the term itself as the tie-break), so the same passages give the same probe twice.
  * the probe is registered, not improvised. \`expansion_probe\` returns the probe text; the caller writes it into
    the run record beside the query it came from -- "cada busca registra o vocabulario tentado".
  * condition 6 still applies to the expanded probe. Terms taken from retrieved material are exactly how a probe
    could learn its own anchor, so \`agree\` runs the golden set's own check -- \`_word_runs\` at 4 words and
    \`_content_terms\` on paraphrase entries -- and a rejection is returned, recorded, never silently dropped.
  * the budget does not move. Expansion competes for the same characters the round already spends: the two
    rankings are fused by position (RRF, k=60) and the delivery is truncated by \`_admit\` at the same cap. A gain
    that costs more characters is not the gain this round is buying.

Cost. Everything here is local except the second embedding of each probe: 20 entries x 2 books x 1 extra probe
(~14 tokens) = ~280 tokens, US$0.000006 at text-embedding-3-small, and only when --spend is passed. BM25 is the
default and costs nothing, which is why the mechanism is tuned there first.
"""
import argparse
import json
import re
from collections import Counter
from datetime import date

from ParallelProse.catalog import DATA_DIR
from ParallelProse.evaluation import _phrase_pattern, _word_runs, load_golden_set, golden_set_path
from ParallelProse.g2_reach import _admit, _child_paragraphs, _deep_bm25, _deep_dense, attested_entries
from ParallelProse.mcp_tools import REGISTRY
from ParallelProse.textform import STOPWORDS, _content_terms, match_form, normalize_text

TOP_PASSAGES = 8      # passages the expansion reads, best first
TOP_TERMS = 8         # terms the expansion may add
RRF_K = 60            # the project's own fusion constant (the formulation round, CC-207/CC-224)
CAP = 88120           # the round's per-query cap: 1.7x the measured post-G1 joint p95
FRACTION_CAP = {"A": 90111, "B": 28874}   # 15% of each book, per entry


def _tokens(text: str) -> list[str]:
    """The project's tokenizer, keeping order and repeats: \`_content_terms\` dedups into a set, and the feedback
    counts need the occurrences."""
    return [word for word in re.findall(r"[a-z]+", normalize_text(text))
            if len(word) > 2 and word not in STOPWORDS]


def expansion_terms(passages: list[str], query: str, top: int = TOP_TERMS) -> list[str]:
    """The vocabulary the first pass brought back: the \`top\` content words most evenly spread over the passages.

    Document frequency decides first, not raw count: a word repeated ten times inside one paragraph describes
    that paragraph, while a word appearing in six of the eight passages describes the neighbourhood the
    retrieval actually reached. Ties break on total frequency, then on the term itself, so the list is
    reproducible. Terms the query already carries are dropped: the second probe is read beside the query, not
    instead of it."""
    known = _content_terms(query)
    df, tf = Counter(), Counter()
    for passage in passages:
        terms = _tokens(passage)
        for term in set(terms):
            df[term] += 1
        tf.update(terms)
    ranked = sorted((term for term in df if term not in known),
                    key=lambda term: (-df[term], -tf[term], term))
    return ranked[:top]


def forbidden_terms(entry) -> set[str]:
    """The content terms of every anchor of the entry, in both books: the vocabulary the expanded probe may not
    carry, taken from the golden set itself.

    Measured in the free channel before this existed: expanding from retrieved material WITHOUT pruning lost an
    entry and got six entries rejected by condition 6, because the neighbourhood of an anchor shares the
    anchor's own words. Pruning is what makes the expansion legal -- and it is also what keeps it honest: the
    probe never learns the words the score pays for, only the words around them."""
    return {term for expectation in entry.expected.values() if expectation.label == "ok"
            for anchor in expectation.anchors for term in _content_terms(anchor)}


def expansion_probe(query: str, passages: list[str], top: int = TOP_TERMS,
                    forbidden: set[str] | None = None) -> str:
    """The second probe: the query plus the vocabulary of the passages it reached -- or the query alone when the
    material adds nothing, which is the honest answer and not an error.

    `forbidden` is `forbidden_terms(entry)`: a term the anchors carry is dropped before the probe is built, so
    the probe is legal by construction and condition 6 still runs as the belt to that suspenders."""
    terms = [term for term in expansion_terms(passages, query, top) if term not in (forbidden or set())]
    return " ".join([query, *terms]) if terms else query


def agree(entry, expansion: str) -> tuple[bool, str]:
    """The golden set's own query rules, applied to the expanded probe (condition 6). A probe sharing four
    consecutive words with an anchor quotes it; a paraphrase entry's probe may share no content term with any of
    its anchors. Returns (ok, reason), so a rejection is a recorded fact, never a silent skip."""
    probe_runs = _word_runs(expansion)
    terms = _content_terms(expansion)
    for cid, expectation in entry.expected.items():
        if expectation.label != "ok":
            continue
        for anchor in expectation.anchors:
            if probe_runs & _word_runs(anchor):
                return False, f"{cid}: expansion repeats 4 words in a row from anchor {anchor!r}"
            if entry.wording == "paraphrase" and (terms & _content_terms(anchor)):
                return False, f"{cid}: paraphrase expansion shares content terms with anchor {anchor!r}"
    return True, ""


def fuse(first: list, second: list, k: int = RRF_K) -> list:
    """The two rankings by position -- the same fusion the round already uses for the formulations: RRF with the
    project's constant. A unit both passes saw climbs; the tie-break is the unit id, so the order is stable."""
    scores = {}
    for ranking in (first, second):
        for position, unit in enumerate(ranking, 1):
            scores[unit] = scores.get(unit, 0.0) + 1.0 / (k + position)
    return sorted(scores, key=lambda unit: (-scores[unit], str(unit)))


def hits_in(texts: list[str], anchors: list[str], k: int) -> int:
    """How many of the entry's anchors the first k delivered units carry -- the round's own reading."""
    top = texts[:k]
    return sum(1 for anchor in anchors if any(_phrase_pattern(anchor).search(text) for text in top))


class BookRanker:
    """One book's delivery for one probe, in the round's two units. Built once per book and reused: the BM25
    index is local and the deep window is the only thing that changes between probes."""

    def __init__(self, corpus_id: str, channel: str, unit: str, deep_k: int):
        self.corpus_id, self.channel, self.unit, self.deep_k = corpus_id, channel, unit, deep_k
        self.retrieval = REGISTRY[corpus_id]
        self.placement = _child_paragraphs(corpus_id) if unit == "paragraph" else None
        self._manager = None
        if channel == "bm25":
            self.retriever = _deep_bm25(self.retrieval, deep_k)
        elif channel == "dense":
            self._manager = _deep_dense(self.retrieval, deep_k)
            self.retriever = self._manager.__enter__()
        else:
            raise ValueError(f"channel must be bm25 or dense, got {channel!r}")

    def close(self):
        if self._manager is not None:
            self._manager.__exit__(None, None, None)

    def texts(self, probe: str) -> list[str]:
        """The delivered units as text, best first: parents as production returns them, or every paragraph the
        ranked children cover, deduped, in child order (the round's P2, CC-210)."""
        if self.unit == "parent":
            return [match_form(parent.page_content) for parent in self.retriever.invoke(probe)]
        children = (self.retriever.invoke(probe) if self.channel == "bm25"
                    else self.retrieval.vector_store.similarity_search(probe, k=self.deep_k))
        paragraphs, mapping, _, _ = self.placement
        ranked, seen = [], set()
        for child in children:
            for index in mapping.get(match_form(child.page_content)) or ():
                if index in seen:
                    continue
                seen.add(index)
                ranked.append(index)
        return [paragraphs[index] for index in ranked]


def expand_book(entry, ranker: BookRanker, top_passages: int = TOP_PASSAGES,
                top_terms: int = TOP_TERMS) -> dict:
    """One entry, one book: first pass, read its best passages, re-probe, fuse. Returns both rankings, the
    fusion, the probe text and the agreement verdict -- what the run record has to carry."""
    first = ranker.texts(entry.query)
    forbidden = forbidden_terms(entry)
    dropped = [term for term in expansion_terms(first[:top_passages], entry.query, top_terms)
               if term in forbidden]
    probe = expansion_probe(entry.query, first[:top_passages], top_terms, forbidden)
    ok, why = agree(entry, probe)
    second = ranker.texts(probe) if (ok and probe != entry.query) else first
    return {"first": first, "second": second, "fused": fuse(first, second), "probe": probe,
            "agrees": ok, "rejected_because": why, "dropped_terms": dropped}


def measure(channel: str = "bm25", unit: str = "paragraph", deep_k: int = 800,
            k_by_book: dict | None = None, cap: int = CAP, fraction_cap: dict | None = None,
            top_passages: int = TOP_PASSAGES, top_terms: int = TOP_TERMS, entries=None) -> dict:
    """The round: expansion against the same sample, the same cap and the same bar.

    For every entry and book: first pass, expansion, fusion. The pass is read on the fused ranking truncated by
    \`_admit\` -- never on a bigger delivery -- and F1 alone is read on the same truncated delivery, so the gain
    is the difference between two numbers read the same way."""
    entries = entries if entries is not None else attested_entries()
    books = sorted(entries[0].expected)
    k_by_book = k_by_book or {"A": 32, "B": 26}
    fraction_cap = fraction_cap or dict(FRACTION_CAP)
    rankers = {cid: BookRanker(cid, channel, unit, deep_k) for cid in books}
    rows = []
    try:
        for entry in entries:
            per_book = {cid: expand_book(entry, rankers[cid], top_passages, top_terms) for cid in books}
            keep, used = _admit({cid: [len(text) for text in per_book[cid]["fused"][:k_by_book[cid]]]
                                 for cid in books}, k_by_book, cap, fraction_cap)
            passed, passed_first = {}, {}
            for cid in books:
                anchors = entry.expected[cid].anchors
                minimum = entry.expected[cid].min_hits
                passed[cid] = hits_in(per_book[cid]["fused"], anchors, keep[cid]) >= minimum
                passed_first[cid] = hits_in(per_book[cid]["first"], anchors, keep[cid]) >= minimum
            rows.append({"id": entry.id, "passed": passed, "passed_first": passed_first,
                         "k_delivered": keep, "chars_used": used,
                         "probes": {cid: per_book[cid]["probe"] for cid in books},
                         "dropped_terms": {cid: per_book[cid]["dropped_terms"] for cid in books},
                         "agrees": {cid: per_book[cid]["agrees"] for cid in books},
                         "rejected_because": {cid: per_book[cid]["rejected_because"] for cid in books},
                         "first": {cid: per_book[cid]["first"] for cid in books},})
    finally:
        for ranker in rankers.values():
            ranker.close()
    return {"channel": channel, "unit": unit, "deep_k": deep_k, "k": k_by_book, "cap": cap,
            "fraction_cap": fraction_cap, "top_passages": top_passages, "top_terms": top_terms, "n": len(entries),
            "two_sided": sum(all(row["passed"].values()) for row in rows),
            "two_sided_first": sum(all(row["passed_first"].values()) for row in rows),
            "per_book": {cid: sum(row["passed"][cid] for row in rows) for cid in books},
            "per_book_first": {cid: sum(row["passed_first"][cid] for row in rows) for cid in books},
            "rejections": {row["id"]: {cid: row["rejected_because"][cid] for cid in books
                                       if not row["agrees"][cid]}
                           for row in rows if not all(row["agrees"].values())},
            "rows": rows}


def print_measure(data: dict) -> None:
    print(f"\n=== expansion: channel={data['channel']} unit={data['unit']} deep_k={data['deep_k']} k={data['k']} "
          f"cap={data['cap']} passages={data['top_passages']} terms={data['top_terms']} ===")
    print(f"two-sided: F1 alone {data['two_sided_first']}/{data['n']}  ->  F1+expansion {data['two_sided']}/{data['n']}"
          f"   (per book {data['per_book_first']} -> {data['per_book']})")
    for row in data["rows"]:
        before, after = all(row["passed_first"].values()), all(row["passed"].values())
        if before != after:
            print(f"  {row['id']}: F1 {row['passed_first']} -> expansion {row['passed']} "
                  f"(chars {row['chars_used']}, k delivered {row['k_delivered']})")
    for eid, why in data["rejections"].items():
        for cid, reason in why.items():
            print(f"  rejected {eid} {cid}: {reason}")
    pruned = {row["id"]: row["dropped_terms"] for row in data["rows"]
              if any(row["dropped_terms"].values())}
    if pruned:
        print(f"  anchor vocabulary pruned out of the probes: {pruned}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="bm25", choices=("bm25", "dense"))
    parser.add_argument("--unit", default="paragraph", choices=("parent", "paragraph"))
    parser.add_argument("--deep-k", type=int, default=800)
    parser.add_argument("--cap", type=int, default=CAP)
    parser.add_argument("--k-a", type=int, default=32)
    parser.add_argument("--k-b", type=int, default=26)
    parser.add_argument("--passages", type=int, default=TOP_PASSAGES)
    parser.add_argument("--terms", type=int, default=TOP_TERMS)
    parser.add_argument("--spend", action="store_true", help="required for --channel dense: it embeds the probes")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    if args.channel == "dense" and not args.spend:
        raise SystemExit("dense embeds the expansion probe (~280 tokens, US$0.000006). Pass --spend to say so.")
    data = measure(args.channel, args.unit, args.deep_k, {"A": args.k_a, "B": args.k_b}, args.cap,
                   top_passages=args.passages, top_terms=args.terms)
    print_measure(data)
    if args.save:
        path = DATA_DIR / "eval" / f"g2_expand_{args.channel}_{args.unit}_{date.today()}.json"
        path.write_text(json.dumps(data, indent=1))
        print(f"saved {path}")


if __name__ == "__main__":
    main()
