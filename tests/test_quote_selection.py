from ParallelProse.agent import ComposerAnswer, CorpusFinding
from ParallelProse.quote_check import select_quotes

CHUNK = ("What sort of compassion is this for feigned and scenical passions? For the auditor is not called on to relieve, "
         "but only to grieve. And he applauds the actor of these fictions.")
QUERY = "Why is the auditor not called on to relieve, but only to grieve?"
BEST = "For the auditor is not called on to relieve, but only to grieve."


def run(quote, query=QUERY, chunk=CHUNK, finding="the finding"):
    answer = ComposerAnswer(agreement="", disagreement="", unique_findings=[
        CorpusFinding(corpus_id="A", finding=finding, quote=quote)])
    return select_quotes(answer, {"A": {"chunks": [chunk]}}, query)


def test_neighbouring_sentence_is_replaced_by_the_one_that_shares_the_query_terms():
    answer, selection = run("What sort of compassion is this for feigned and scenical passions?")

    assert answer.unique_findings[0].quote == BEST
    assert selection["A"]["replaced"] is True
    assert selection["A"]["llm_quote"] == "What sort of compassion is this for feigned and scenical passions?"


def test_echo_of_the_query_is_replaced_by_a_real_sentence_and_never_by_the_query():
    answer, selection = run(QUERY)

    assert answer.unique_findings[0].quote == BEST
    assert selection["A"]["llm_quote"] == QUERY


def test_a_quote_that_already_scores_highest_is_kept():
    answer, selection = run(BEST)

    assert answer.unique_findings[0].quote == BEST
    assert selection["A"]["replaced"] is False


def test_the_finding_is_not_changed_by_a_replacement():
    answer, _ = run("What sort of compassion is this for feigned and scenical passions?", finding="pity on stage")

    assert answer.unique_findings[0].finding == "pity on stage"


def test_a_sentence_sharing_only_one_query_term_does_not_replace_the_quote():
    chunk = "The moon is pale. Her auditor sleeps soundly."
    answer, selection = run("The moon is pale.", query="Why does the auditor sleep?", chunk=chunk)

    assert answer.unique_findings[0].quote == "The moon is pale."
    assert selection["A"]["replaced"] is False


def test_a_book_without_a_quote_is_left_alone():
    answer = ComposerAnswer(agreement="", disagreement="", unique_findings=[
        CorpusFinding(corpus_id="A", finding="query content is absent", quote=None)])

    adjusted, selection = select_quotes(answer, {"A": {"chunks": [CHUNK]}}, QUERY)

    assert adjusted.unique_findings[0].quote is None
    assert selection == {"A": {"replaced": False}}


def test_a_non_target_book_keeps_the_composer_quote():
    answer = ComposerAnswer(agreement="", disagreement="", unique_findings=[
        CorpusFinding(corpus_id="A", finding="f", quote="What sort of compassion is this for feigned and scenical passions?"),
        CorpusFinding(corpus_id="B", finding="g", quote="The moon is pale.")])
    adjusted, selection = select_quotes(answer, {"A": {"chunks": [CHUNK]}, "B": {"chunks": [CHUNK]}}, QUERY, books={"A"})

    assert adjusted.unique_findings[0].quote == BEST
    assert adjusted.unique_findings[1].quote == "The moon is pale."
    assert selection["B"] == {"replaced": False}
