import difflib
import math
import re
import unicodedata
from collections import Counter

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


MIN_SHARED_TERMS = 2  # a replacement must share at least this many content terms with the query
STOPWORDS = frozenset("""a an and are as at be been but by can could did do does for from had has have he her his how i if in
into is it its me my no nor not of on or our she so than that the their them then there these they this those to too us
was we were what when where which who whom why will with would you your""".split())


def _content_terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", normalize_text(text)) if len(w) > 2 and w not in STOPWORDS}


def select_quotes(answer: ComposerAnswer, corpora: dict, query: str,
                  books: set[str] | None = None) -> tuple[ComposerAnswer, dict[str, dict]]:
    """Per book, the composer's quote is replaced by the sentence of that book's retrieved chunks that shares the most query terms,
    when that sentence scores strictly higher. A term counts for more the rarer it is among the book's sentences. A quote that echoes
    the query always loses its place, and the echo is never replaced by the query itself. Returns the adjusted answer and, per book,
    whether a quote was replaced, with the composer's original quote as `llm_quote` and both scores. Only the books in `books`
    are considered (None means all): a twin query's non-target book keeps the composer's quote."""
    query_terms = _content_terms(query)
    query_form = match_form(query, is_quote=True)
    selection, findings = {}, []
    for finding in answer.unique_findings:
        cid = finding.corpus_id
        if finding.quote is None or (books is not None and cid not in books):
            selection[cid] = {"replaced": False}
            findings.append(finding)
            continue
        sentences = [(s, _content_terms(s)) for chunk in corpora[cid]["chunks"]
                     for s in re.split(r"(?<=[.!?;:])\s+", re.sub(r"\s+", " ", chunk).strip()) if s.strip()]
        document_frequency = Counter(term for _, terms in sentences for term in terms)
        count = len(sentences)

        def score(terms: set[str]) -> float:
            return sum(math.log((count + 1) / (document_frequency[t] + 1)) + 1 for t in query_terms if t in terms)

        if match_form(finding.quote, is_quote=True) == query_form:
            quote_score = -1.0  # an echo of the query loses to any real sentence
        else:
            quote_score = score(_content_terms(finding.quote))
        best_sentence, best_score = "", 0.0
        for sentence, terms in sentences:
            if match_form(sentence, is_quote=True) == query_form or len(query_terms & terms) < MIN_SHARED_TERMS:
                continue  # one shared word, even a rare one, is not enough to stand in for an answer
            if score(terms) > best_score:
                best_sentence, best_score = sentence, score(terms)
        if best_sentence and best_score > quote_score:
            selection[cid] = {"replaced": True, "llm_quote": finding.quote,
                              "score": round(best_score, 3), "llm_score": round(quote_score, 3)}
            findings.append(finding.model_copy(update={"quote": best_sentence}))
        else:
            selection[cid] = {"replaced": False, "score": round(quote_score, 3)}
            findings.append(finding)
    return answer.model_copy(update={"unique_findings": findings}), selection


def verified_flags(details: dict[str, dict]) -> dict[str, bool | None]:
    """The boolean kept for each bite: True when the quote is text the book contains (whole, prefix or fragment), None when there is no quote."""
    return {cid: None if d["status"] == "no_quote" else d["status"] in VERIFIED_STATUSES for cid, d in details.items()}
