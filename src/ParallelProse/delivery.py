"""The delivery contract, as a production function (item 53, G3).

What the composer, the picker and the judges receive for one query: per book, the paragraphs the dense channel
ranks for the query verbatim, admitted by the contract's fixed k, per-book fraction and joint cap (the rule of
g2_reach._admit, read on the delivered unit). Nothing here calls a model.

The measuring stick (g2_reach) owns the constants and the helpers; this module calls the same ones, so the
pre-registered round (g3_round_preregistration) and production share one code path. Until the retriever is
wired to `deliver`, production does not run this path.
"""
from __future__ import annotations

from ParallelProse.g2_reach import (CLOSING_ROUND_CONFIG, _admit, _channel_runner, _child_paragraphs, _ranking,
                                    book_chars, formulations)

_placement: dict[str, tuple] = {}  # per book, built once per process: scanning every child is the slow part


def _placement_of(corpus_id: str):
    if corpus_id not in _placement:
        _placement[corpus_id] = _child_paragraphs(corpus_id)
    return _placement[corpus_id]


def deliver(queries: dict[str, str]) -> dict[str, list[tuple[int, str]]]:
    """The delivered paragraphs per book as (address, text) pairs, each book probed with its own query, truncated
    by the contract's rule (fraction first, then the joint cap, dropping the deepest unit of the book with more
    admitted; ties go to the later book). The address is the paragraph's position in the book's paragraph list --
    the identity that travels with the text, so no caller has to recover it by matching the text."""
    cfg = CLOSING_ROUND_CONFIG
    books = list(queries)
    fraction_cap = {cid: int(cfg["fraction"] * book_chars(cid)) for cid in books}

    windows: dict[str, list[tuple[int, str]]] = {}
    for cid in books:
        probe = formulations(queries[cid])[0]  # F1: the query exactly as written
        run, manager = _channel_runner(cid, cfg["channel"], cfg["deep_k"], cfg["unit"])
        try:
            pairs = _ranking(run, cid, probe, cfg["unit"], _placement_of(cid))
        finally:
            if manager is not None:
                manager.__exit__(None, None, None)
        windows[cid] = [(int(index), text) for index, text in pairs]

    counts, _ = _admit({cid: [len(text) for _, text in windows[cid]] for cid in books},
                       cfg["asked_k"], cfg["cap"], fraction_cap)
    return {cid: windows[cid][:counts[cid]] for cid in books}
