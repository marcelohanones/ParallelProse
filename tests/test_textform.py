"""The pinned text primitives (item 48, section 9): the move must not change a comparison, and the new
inflection-tolerant guard must stay confined to its own function."""

from ParallelProse import textform
from ParallelProse.textform import _content_terms, match_form, normalize_text, terms_contained, terms_match


def test_normalize_folds_quotes_dashes_and_whitespace():
    assert normalize_text("The  “spectacle”—is\nabstract") == 'the "spectacle"-is abstract'
    assert normalize_text("soft­\nhyphen") == "softhyphen"


def test_match_form_drops_quote_marks_and_only_a_quote_s_trailing_punctuation():
    assert match_form('say "this",') == "say this,"
    assert match_form('say "this",', is_quote=True) == "say this"


def test_content_terms_keeps_no_stemming_and_no_short_or_stop_words():
    assert _content_terms("The spectacle is reducing it") == {"spectacle", "reducing"}
    assert "reduces" not in _content_terms("The spectacle is reducing it")


def test_terms_match_accepts_inflection_and_is_deliberately_loose():
    assert terms_match("reduces", {"reducing", "life"})      # the case the containment guard exists for
    assert terms_match("former", {"form"})                   # loose on purpose: a guard, never a verdict
    assert not terms_match("spectacle", {"reducing", "life"})


def test_terms_contained_reports_what_the_outer_text_lacks():
    assert terms_contained("reducing life", "the spectacle reduces life to mere images") == []
    assert terms_contained("the spectacle reduces life", "everything lived has receded") == [
        "life", "reduces", "spectacle"]


def test_quote_check_re_exports_the_same_objects():
    from ParallelProse import quote_check

    for name in ("normalize_text", "match_form", "STOPWORDS", "_content_terms",
                 "SOFT_HYPHEN", "PUNCTUATION_MAP", "QUOTE_MARKS", "TRAILING_PUNCTUATION"):
        assert getattr(quote_check, name) is getattr(textform, name)
