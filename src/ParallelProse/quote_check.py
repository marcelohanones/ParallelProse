import difflib
import math
import re
from bisect import bisect_right
from collections import Counter
from functools import lru_cache

from ParallelProse.agent import ComposerAnswer
from ParallelProse.catalog import CATALOG
from ParallelProse.ingest import load_corpus
# Re-exported, not redefined: the text primitives moved to textform.py so `judges` can compare in the same form
# without importing this module's graph chain (item 48, section 9). Every existing importer of these names from
# quote_check keeps working.
from ParallelProse.textform import (PUNCTUATION_MAP, QUOTE_MARKS, SOFT_HYPHEN, STOPWORDS,  # noqa: F401
                                    TRAILING_PUNCTUATION, _content_terms, match_form, normalize_text)

BARE_NUMBER = re.compile(r"(?<!\S)\d{1,3}(?!\S)")  # the corpus numbers its theses inline, as a bare token
VERIFIED_STATUSES = {"verbatim", "prefix", "fragment"}  # the quote is text the book contains, whole or cut


def _without_bare_numbers(text: str) -> str:
    return re.sub(r"\s+", " ", BARE_NUMBER.sub(" ", text)).strip()


def _windows(text: str):
    """Each sentence, and each pair of consecutive sentences, as a candidate passage, in the text's own wording."""
    text = re.sub(r"\s+", " ", text).strip()
    sentences = [s for s in re.split(r"(?<=[.!?;:])\s+", text) if s.strip()]
    for i, sentence in enumerate(sentences):
        yield sentence
        if i + 1 < len(sentences):
            yield f"{sentence} {sentences[i + 1]}"


def _nearest(quote: str, windows: list[tuple[str, str]]) -> tuple[float, str, str]:
    """The window whose matching form is closest to the quote's: (similarity, window as written, its matching form)."""
    best = (0.0, "", "")
    for raw, form in windows:
        ratio = difflib.SequenceMatcher(None, quote, form, autojunk=False).ratio()
        if ratio > best[0]:
            best = (ratio, raw, form)
    return best


def _differences(quote: str, window: str, limit: int = 4) -> list[list[str]]:
    """The first few spans where the quote and the nearest corpus passage disagree: [operation, quote text, corpus text]."""
    opcodes = difflib.SequenceMatcher(None, quote, window, autojunk=False).get_opcodes()
    return [[tag, quote[i1:i2], window[j1:j2]] for tag, i1, i2, j1, j2 in opcodes if tag != "equal"][:limit]


@lru_cache
def _chapters(book):
    """The book's chapters, parsed once per book and shared by every cache below."""
    return load_corpus(str(book.path))


@lru_cache
def book_paragraphs(book) -> tuple[list[str], list[int]]:
    """The book's paragraphs in match_form, and where each one starts in the paragraphs joined with a space.
    _load_epub joins a chapter's paragraphs with a blank line, so splitting on it gives them back. Cached per
    book: a session runs many queries against the same two books, and this parses the epub from scratch."""
    paragraphs = [match_form(p) for chapter in _chapters(book)
                  for p in chapter.page_content.split("\n\n") if p.strip()]
    starts, position = [], 0
    for paragraph in paragraphs:
        starts.append(position)
        position += len(paragraph) + 1
    return paragraphs, starts


@lru_cache
def _book_raw_paragraphs(book) -> list[str]:
    """The book's paragraphs as written — same split as book_paragraphs, no match_form — for human-readable display."""
    return [p for chapter in _chapters(book) for p in chapter.page_content.split("\n\n") if p.strip()]


@lru_cache
def _book_sentences(book) -> list[str]:
    """Every raw sentence in the book, flattened across paragraphs into one book-wide reading order."""
    return [s for p in _book_raw_paragraphs(book)
            for s in re.split(r"(?<=[.!?;:])\s+", re.sub(r"\s+", " ", p).strip()) if s.strip()]


def context_window(book, quote: str, around: int = 1) -> str | None:
    """`around` raw sentences before and after the sentence(s) the quote's match_form overlaps, joined with the
    matched span itself. None if no sentence in the book overlaps the quote (an echo, an invention, or a number
    mismatch that makes the match fuzzy). Locates the quote by character position in the joined sentence forms,
    not by per-sentence substring containment: a short quote is a trivial substring of almost any short sentence
    fragment (this text's heavy semicolon/colon use over-splits plenty of them), so containment alone matches
    everywhere; a character span can only match where the quote actually sits."""
    quote_form = match_form(quote, is_quote=True)
    sentences = _book_sentences(book)
    forms = [match_form(s) for s in sentences]
    starts, position = [], 0
    for form in forms:
        starts.append(position)
        position += len(form) + 1
    idx = " ".join(forms).find(quote_form)
    if idx == -1:
        return None
    first = bisect_right(starts, idx) - 1
    last = bisect_right(starts, idx + len(quote_form) - 1) - 1
    lo, hi = max(0, first - around), min(len(sentences), last + 1 + around)
    return " ".join(sentences[lo:hi])


def book_passage(book, quote: str) -> str | None:
    """The paragraph of the book that contains the quote, as written — the evidence unit the quote anchors into.
    None when no paragraph contains it (an echo, an invention, or a fuzzy number match). Locates the quote by
    character span in the joined paragraph forms, for the reason context_window does: containment alone matches a
    short quote everywhere in this text's over-split sentences."""
    quote_form = match_form(quote, is_quote=True)
    forms, starts = book_paragraphs(book)
    idx = " ".join(forms).find(quote_form)
    if idx == -1:
        return None
    return _book_raw_paragraphs(book)[bisect_right(starts, idx) - 1]


def _sentence_status(sentence: str, cid: str, chunks: list[str], query_form: str) -> dict:
    """How one pair's sentence relates to that book's retrieved chunks and, failing that, to the book itself."""
    quote_form = match_form(sentence, is_quote=True)
    windows = [(raw, match_form(raw, is_quote=True)) for chunk in chunks for raw in _windows(chunk)]
    joined = " ".join(match_form(chunk) for chunk in chunks)
    entry = {}
    if quote_form == query_form:
        entry["status"] = "echo_of_query"
    elif quote_form in joined:
        containing = [(raw, form) for raw, form in windows if quote_form in form]
        if not containing:
            entry["status"] = "verbatim"  # spans two chunks or more than two sentences: present, not one sentence
        else:
            raw, form = min(containing, key=lambda w: len(w[1]))
            if form == quote_form:
                entry["status"] = "verbatim"
            else:
                entry["status"] = "prefix" if form.startswith(quote_form) else "fragment"
                entry["quote_full"] = raw
    elif _without_bare_numbers(quote_form) in _without_bare_numbers(joined):
        entry["status"] = "differs_only_by_corpus_numbers"
    else:
        paragraphs, _ = book_paragraphs(CATALOG[cid])
        entry["status"] = "found_in_book" if quote_form in " ".join(paragraphs) else "not_found"
    if entry["status"] in ("differs_only_by_corpus_numbers", "not_found"):
        similarity, raw, form = _nearest(quote_form, windows)
        entry.update(similarity=round(similarity, 3), nearest=raw, differences=_differences(quote_form, form))
    return entry


def verify_quotes(answer: ComposerAnswer, corpora: dict, query: str) -> dict[str, list[dict]]:
    """Per book, one entry per (claim, sentence) pair, in order: how that pair's sentence relates to that book's
    retrieved chunks and, failing that, to the book itself. An empty list means the book contributed no pair — a
    silent book. Each entry's `status` is one of: echo_of_query (the sentence is the query itself); verbatim (the
    sentence is a whole sentence the chunks contain); prefix (it opens a longer sentence; quote_full is that
    sentence as written); fragment (it sits inside a longer sentence; quote_full is that sentence);
    differs_only_by_corpus_numbers (found once the corpus's bare thesis numbers are ignored); found_in_book (not
    in the retrieved chunks, but the book itself has it — a retrieval gap, not an invented quote); not_found (the
    book does not contain it either). Failed sentences also carry similarity, nearest and differences."""
    query_form = match_form(query, is_quote=True)
    findings_by_cid = {f.corpus_id: f for f in answer.unique_findings}
    details = {}
    for cid in corpora:
        finding = findings_by_cid.get(cid)
        details[cid] = [_sentence_status(pair.sentence, cid, corpora[cid]["chunks"], query_form)
                        for pair in (finding.pairs if finding else [])]
    return details


def verified_flags(details: dict[str, list[dict]]) -> dict[str, bool | None]:
    """The boolean kept for each bite: True when every pair's sentence is text the book contains (whole, prefix or
    fragment), False when at least one is not, None when the book contributed no pair."""
    return {cid: (None if not entries else all(e["status"] in VERIFIED_STATUSES for e in entries))
            for cid, entries in details.items()}
