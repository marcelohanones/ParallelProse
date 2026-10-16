"""The text primitives both the quote checker and the judges compare in (roadmap item 48, section 9).

They used to live in `quote_check`, whose import chain reaches the graph: `quote_check` imports `agent` for
`ComposerAnswer`, `agent` imports `mcp_tools`, and `mcp_tools` builds its `REGISTRY` and calls
`add_parent_child_docs()` at module import -- so importing the quote checker opens both Chroma stores. `judges` needs
the primitives and nothing else from that side, so they moved here and `quote_check` re-exports them under their
current names: every existing importer keeps working.

`normalize_text`, `match_form`, `STOPWORDS` and `_content_terms` are byte-identical to the versions that produced
every count recorded in item 47 and in `docs/item48_faithfulness_spec.md` -- they are the pinned helper, and they stay
frozen. `terms_match` is new and used only by the judge's containment guards (spec section 4, C2).
"""

import hashlib
import re
import unicodedata

SOFT_HYPHEN = re.compile(r"­\s*")  # the PDF's hidden hyphen, often followed by a line break
PUNCTUATION_MAP = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-"})
QUOTE_MARKS = re.compile(r"[\"']")  # quote marks, wherever the model or the corpus puts them
TRAILING_PUNCTUATION = re.compile(r"[.,;:!?]+$")  # only the end of the quote is ignored; punctuation inside it still counts

STOPWORDS = frozenset("""a an and are as at be been but by can could did do does for from had has have he her his how i if in
into is it its me my no nor not of on or our she so than that the their them then there these they this those to too us
was we were what when where which who whom why will with would you your""".split())

# C2's lower bound only (item 48, v4): a reading may drop a structural connective, because `read_as` restates one
# segment as a proposition and the joint between segments goes with the joint. Causal and consecutive connectives are
# deliberately NOT here -- `because`, `therefore`, `thus`, `hence`, `by`, `through`, `leading` are families the judge
# exists to catch, and 22 of the 140 claims carry one. Every exemption that fires is logged, so this list stays
# evidence-driven: it was added after `while` cost p43, a `covered` pair, its lenient pass on the first dry-run.
DROPPABLE_CONNECTIVES = frozenset(
    "while whereas though although besides also yet both either neither".split())

STEM_PREFIX = 4  # terms_match only: "reducing" and "reduces" share four characters, "form" and "former" also do


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


def _content_terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", normalize_text(text)) if len(w) > 2 and w not in STOPWORDS}


def terms_match(term: str, others: set[str]) -> bool:
    """Is this content word present among `others`, allowing for inflection? Token equality, or a shared prefix of
    STEM_PREFIX characters -- so a borrowed subject's verb ("reducing" -> "reduces") does not fail a guard. The rule is
    deliberately loose ("form" matches "former"): acceptable for the judge's containment checks, never for a verdict,
    which is why `_content_terms` gains no stemming."""
    if term in others:
        return True
    stem = term[:STEM_PREFIX]
    return any(other[:STEM_PREFIX] == stem for other in others)


def terms_contained(inner: str, outer: str) -> list[str]:
    """The content words of `inner` that `outer` does not carry, under `terms_match` -- empty when inner is contained.
    The judge's two containment guards are this call in both directions (spec section 4, C2)."""
    outer_terms = _content_terms(outer)
    return [term for term in sorted(_content_terms(inner)) if not terms_match(term, outer_terms)]


# MARK: STABLE IDENTITY
def norm_v2(text: str) -> str:
    """The frozen normal form a span's identity is computed in: lowercased, whitespace collapsed, quote marks
    folded. Deliberately narrower than `normalize_text` -- no NFKC, no dash folding, no soft hyphen -- because this
    one is an identity and must never be widened: a looser form would merge two spans that the book prints
    differently, and a tighter one would mint a new id for a span already cited. `normalize_text` stays the
    comparison form and stays pinned (see this module's header); the two are separate on purpose."""
    folded = text.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"}))
    return re.sub(r"\s+", " ", folded).strip().lower()


def stable_id(book: str, span: str) -> str:
    """A span's identity, derived from the span itself -- so it survives a rebuild, which the chunk's `doc_id`
    (a uuid4) does not. Content-addressed by construction: the same text in the same book is the same id, in any
    process, before or after re-embedding."""
    digest = hashlib.sha1(f"{book}|{norm_v2(span)}".encode()).hexdigest()
    return "s" + digest[:12]
