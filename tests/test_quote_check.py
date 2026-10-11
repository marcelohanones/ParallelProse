from ParallelProse import quote_check as qc
from ParallelProse.agent import ComposerAnswer, CorpusFinding
from ParallelProse.quote_check import normalize_text, verified_flags, verify_quotes

QUERY = "How is time experienced by people?"


def check(quote, chunk, query=QUERY, cid="B"):
    answer = ComposerAnswer(agreement="", disagreement="", unique_findings=[
        CorpusFinding(corpus_id=cid, finding="f", quote=quote)])
    return verify_quotes(answer, {cid: {"chunks": [chunk]}}, query)[cid]


def test_soft_hyphen_at_a_line_break_does_not_break_a_match():
    assert check("the moments joined together.", "the moments joined to­\ngether.")["status"] == "verbatim"


def test_dash_variants_match_each_other():
    assert check("councils-a power.", "councils—a power.")["status"] == "verbatim"


def test_trailing_punctuation_of_the_quote_is_ignored():
    assert check("held down as in sleep.", "held down as in sleep:")["status"] == "verbatim"
    assert check("held down as in sleep.", "I was held down as in sleep: and more")["status"] == "fragment"


def test_quote_marks_around_or_inside_the_quote_are_ignored():
    assert check('"Anon, anon,"', "Anon, anon, presently.")["status"] == "prefix"
    assert check("'Give me' chastity", "Give me chastity and continency")["status"] == "prefix"


def test_quote_that_opens_a_longer_sentence_is_a_prefix_and_returns_the_full_sentence():
    detail = check("I begged chastity", "I begged chastity and continency, only not yet. Then I wept.")

    assert detail["status"] == "prefix"
    assert detail["quote_full"] == "I begged chastity and continency, only not yet."
    assert verified_flags({"B": detail}) == {"B": True}


def test_quote_inside_a_longer_sentence_is_a_fragment_with_the_full_sentence():
    detail = check("in whom is no variableness", "Thou, in whom is no variableness, nor shadow of turning.")

    assert detail["status"] == "fragment"
    assert detail["quote_full"] == "Thou, in whom is no variableness, nor shadow of turning."


def test_quote_equal_to_the_query_is_rejected_as_an_echo():
    detail = check(QUERY, "some passage about time")

    assert detail["status"] == "echo_of_query"
    assert verified_flags({"B": detail}) == {"B": False}


def test_bare_thesis_number_in_the_corpus_is_reported_as_its_own_status():
    detail = check("the spectacle. the spectacle is everywhere", "the spectacle. 24 the spectacle is everywhere")

    assert detail["status"] == "differs_only_by_corpus_numbers"
    assert detail["nearest"] == "the spectacle. 24 the spectacle is everywhere"


def test_changed_punctuation_inside_the_quote_is_still_not_found():
    detail = check("passions, for the auditor", "passions? for the auditor is not called on to relieve")

    assert detail["status"] == "not_found"
    assert detail["nearest"] == "passions? for the auditor is not called on to relieve"
    assert ["replace", ",", "?"] in detail["differences"]
    assert 0 < detail["similarity"] < 1


def test_book_paragraphs_splits_on_the_blank_line_load_corpus_uses_between_paragraphs(monkeypatch):
    class Chapter:
        def __init__(self, page_content):
            self.page_content = page_content

    class Book:
        path = "irrelevant.epub"

    monkeypatch.setattr(qc, "load_corpus", lambda path: [Chapter("First paragraph.\n\nSecond paragraph.")])
    qc.book_paragraphs.cache_clear()

    paragraphs, starts = qc.book_paragraphs(Book())

    assert paragraphs == ["first paragraph.", "second paragraph."]
    assert starts == [0, len("first paragraph.") + 1]


def test_a_colon_mid_sentence_in_the_corpus_is_still_matched_verbatim():
    # the real failure mode item 37 targets: _windows() splits a "sentence" wherever [.!?;:] appears, even
    # when the colon doesn't actually end the sentence grammatically (epub text runs straight into "and ...").
    detail = check("held down pleasantly, as in sleep.",
                    "held down pleasantly, as in sleep: and the thoughts wherein I meditated were like dreams.")

    assert detail["status"] == "verbatim"


def test_quote_missing_from_chunks_but_present_in_the_book_is_found_in_book(monkeypatch):
    monkeypatch.setattr(qc, "book_paragraphs", lambda book: (["give me chastity and continency, only not yet"], [0]))

    detail = check("Give me chastity and continency, only not yet.", "some unrelated retrieved passage")

    assert detail["status"] == "found_in_book"
    assert "similarity" not in detail


def test_quote_missing_from_chunks_and_from_the_book_is_not_found(monkeypatch):
    monkeypatch.setattr(qc, "book_paragraphs", lambda book: (["nothing like the quote at all"], [0]))

    detail = check("a quote that exists nowhere", "some unrelated retrieved passage")

    assert detail["status"] == "not_found"
    assert "similarity" in detail


def test_no_quote_has_no_flag():
    answer = ComposerAnswer(agreement="", disagreement="", unique_findings=[
        CorpusFinding(corpus_id="A", finding="query content is absent", quote=None)])

    details = verify_quotes(answer, {"A": {"chunks": ["anything"]}}, QUERY)

    assert details == {"A": {"status": "no_quote"}}
    assert verified_flags(details) == {"A": None}


def test_normalize_text_folds_case_and_whitespace():
    assert normalize_text("  Time\n\tPASSES  ") == "time passes"
