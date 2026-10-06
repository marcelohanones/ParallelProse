from ParallelProse.agent import ComposerAnswer, CorpusFinding
from ParallelProse.quote_check import normalize_text, verified_flags, verify_quotes

QUERY = "How is time experienced by people?"


def check(quote, chunk, query=QUERY, cid="B"):
    answer = ComposerAnswer(agreement="", disagreement="", unique_findings=[
        CorpusFinding(corpus_id=cid, finding="f", quote=quote)])
    return verify_quotes(answer, {cid: {"chunks": [chunk]}}, query)[cid]


def test_soft_hyphen_at_a_line_break_does_not_break_a_match():
    assert check("the moments joined together", "the moments joined to­\ngether in luxury")["status"] == "verbatim"


def test_dash_variants_match_each_other():
    assert check("councils-a power", "councils—a power")["status"] == "verbatim"


def test_quote_equal_to_the_query_is_rejected_as_an_echo():
    detail = check(QUERY, "some passage about time")

    assert detail["status"] == "echo_of_query"
    assert verified_flags({"B": detail}) == {"B": False}


def test_bare_thesis_number_in_the_corpus_is_reported_as_its_own_status():
    detail = check("the spectacle. the spectacle is everywhere", "the spectacle. 24 the spectacle is everywhere")

    assert detail["status"] == "differs_only_by_corpus_numbers"
    assert detail["nearest"] == "the spectacle. 24 the spectacle is everywhere"


def test_changed_punctuation_is_not_found_and_shows_the_difference():
    detail = check("passions, for the auditor", "passions? for the auditor is not called on to relieve")

    assert detail["status"] == "not_found"
    assert detail["nearest"] == "passions? for the auditor is not called on to relieve"
    assert ["replace", ",", "?"] in detail["differences"]
    assert 0 < detail["similarity"] < 1


def test_no_quote_has_no_flag():
    answer = ComposerAnswer(agreement="", disagreement="", unique_findings=[
        CorpusFinding(corpus_id="A", finding="query content is absent", quote=None)])

    details = verify_quotes(answer, {"A": {"chunks": ["anything"]}}, QUERY)

    assert details == {"A": {"status": "no_quote"}}
    assert verified_flags(details) == {"A": None}


def test_normalize_text_folds_case_and_whitespace():
    assert normalize_text("  Time\n\tPASSES  ") == "time passes"
