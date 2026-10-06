import difflib
import re
import unicodedata

from ParallelProse.agent import ComposerAnswer

SOFT_HYPHEN = re.compile(r"­\s*")  # the PDF's hidden hyphen, often followed by a line break
PUNCTUATION_MAP = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-"})
QUOTE_MARKS = re.compile(r"[\"']")  # quote marks, wherever the model or the corpus puts them
TRAILING_PUNCTUATION = re.compile(r"[.,;:!?]+$")  # only the end of the quote is ignored; punctuation inside it still counts
BARE_NUMBER = re.compile(r"(?<!\S)\d{1,3}(?!\S)")  # the corpus numbers its theses inline, as a bare token
VERIFIED_STATUSES = {"verbatim", "prefix", "fragment"}  # the quote is text the book contains, whole or cut


def normalize_text(text: str) -> str:
    """Lowercases, folds compatibility characters and dash/quote variants, drops soft hyphens, collapses whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = SOFT_HYPHEN.sub("", text).translate(PUNCTUATION_MAP)
    return re.sub(r"\s+", " ", text).strip().lower()


def match_form(text: str, is_quote: bool = False) -> str:
    """The form two texts are compared in: normalized, with quote marks removed everywhere and, for a quote, its trailing punctuation removed."""
    form = QUOTE_MARKS.sub("", normalize_text(text)).strip()
    if is_quote:
        form = TRAILING_PUNCTUATION.sub("", form).strip()
    return form


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


def verify_quotes(answer: ComposerAnswer, corpora: dict, query: str) -> dict[str, dict]:
    """Per book, how its quote relates to that book's retrieved chunks. `status` is one of:
    no_quote; echo_of_query (the quote is the query itself); verbatim (the quote is a whole sentence the chunks contain);
    prefix (the quote opens a longer sentence; quote_full is that sentence as written); fragment (the quote sits inside
    a longer sentence; quote_full is that sentence); differs_only_by_corpus_numbers (found once the corpus's bare thesis
    numbers are ignored); not_found. Failed quotes also carry similarity, nearest and differences."""
    query_form = match_form(query, is_quote=True)
    details = {}
    for finding in answer.unique_findings:
        cid = finding.corpus_id
        if finding.quote is None:
            details[cid] = {"status": "no_quote"}
            continue
        quote_form = match_form(finding.quote, is_quote=True)
        windows = [(raw, match_form(raw, is_quote=True)) for chunk in corpora[cid]["chunks"] for raw in _windows(chunk)]
        joined = " ".join(match_form(chunk) for chunk in corpora[cid]["chunks"])
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
            entry["status"] = "not_found"
        if entry["status"] in ("differs_only_by_corpus_numbers", "not_found"):
            similarity, raw, form = _nearest(quote_form, windows)
            entry.update(similarity=round(similarity, 3), nearest=raw, differences=_differences(quote_form, form))
        details[cid] = entry
    return details


def verified_flags(details: dict[str, dict]) -> dict[str, bool | None]:
    """The boolean kept for each bite: True when the quote is text the book contains (whole, prefix or fragment), None when there is no quote."""
    return {cid: None if d["status"] == "no_quote" else d["status"] in VERIFIED_STATUSES for cid, d in details.items()}
