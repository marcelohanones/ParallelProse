import difflib
import re
import unicodedata

from ParallelProse.agent import ComposerAnswer

SOFT_HYPHEN = re.compile(r"­\s*")  # the PDF's hidden hyphen, often followed by a line break
PUNCTUATION_MAP = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-"})
BARE_NUMBER = re.compile(r"(?<!\S)\d{1,3}(?!\S)")  # the corpus numbers its theses inline, as a bare token


def normalize_text(text: str) -> str:
    """Lowercases, folds compatibility characters and dash/quote variants, drops soft hyphens, collapses whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = SOFT_HYPHEN.sub("", text).translate(PUNCTUATION_MAP)
    return re.sub(r"\s+", " ", text).strip().lower()


def _without_bare_numbers(text: str) -> str:
    return re.sub(r"\s+", " ", BARE_NUMBER.sub(" ", text)).strip()


def _windows(text: str):
    """Each sentence, and each pair of consecutive sentences, as a candidate passage."""
    sentences = [s for s in re.split(r"(?<=[.!?;:])\s+", text) if s.strip()]
    for i, sentence in enumerate(sentences):
        yield sentence
        if i + 1 < len(sentences):
            yield f"{sentence} {sentences[i + 1]}"


def _nearest(quote: str, chunks: list[str]) -> tuple[float, str]:
    best = (0.0, "")
    for chunk in chunks:
        for window in _windows(chunk):
            ratio = difflib.SequenceMatcher(None, quote, window, autojunk=False).ratio()
            if ratio > best[0]:
                best = (ratio, window)
    return best


def _differences(quote: str, window: str, limit: int = 4) -> list[list[str]]:
    """The first few spans where the quote and the nearest corpus passage disagree: [operation, quote text, corpus text]."""
    opcodes = difflib.SequenceMatcher(None, quote, window, autojunk=False).get_opcodes()
    return [[tag, quote[i1:i2], window[j1:j2]] for tag, i1, i2, j1, j2 in opcodes if tag != "equal"][:limit]


def verify_quotes(answer: ComposerAnswer, corpora: dict, query: str) -> dict[str, dict]:
    """Per book, how its quote relates to that book's retrieved chunks. `status` is one of:
    no_quote; echo_of_query (the quote is the query itself); verbatim (found in the chunks after normalization);
    differs_only_by_corpus_numbers (found once the corpus's bare thesis numbers are ignored); not_found.
    Failed quotes also carry similarity, nearest (the closest corpus passage) and differences."""
    query_n = normalize_text(query)
    details = {}
    for finding in answer.unique_findings:
        cid = finding.corpus_id
        if finding.quote is None:
            details[cid] = {"status": "no_quote"}
            continue
        quote_n = normalize_text(finding.quote)
        chunks_n = [normalize_text(c) for c in corpora[cid]["chunks"]]
        joined = " ".join(chunks_n)
        if quote_n == query_n:
            status = "echo_of_query"
        elif quote_n in joined:
            status = "verbatim"
        elif _without_bare_numbers(quote_n) in _without_bare_numbers(joined):
            status = "differs_only_by_corpus_numbers"
        else:
            status = "not_found"
        entry = {"status": status}
        if status in ("not_found", "differs_only_by_corpus_numbers"):
            similarity, window = _nearest(quote_n, chunks_n)
            entry.update(similarity=round(similarity, 3), nearest=window, differences=_differences(quote_n, window))
        details[cid] = entry
    return details


def verified_flags(details: dict[str, dict]) -> dict[str, bool | None]:
    """The boolean kept for each bite: True only for a verbatim quote, None when there is no quote."""
    return {cid: None if d["status"] == "no_quote" else d["status"] == "verbatim" for cid, d in details.items()}
