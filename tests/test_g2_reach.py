"""The pure parts of G2's measuring stick: the probe set and the pass rule. The retrieval itself is not tested
here -- it needs the stores, and the dense channel needs the API."""
import pytest

from ParallelProse.evaluation import QUOTED_RUN, _word_runs
from ParallelProse.g2_reach import FRAME, _passes, formulations
from ParallelProse.textform import STOPWORDS, _content_terms


def test_formulations_are_a_pure_function_of_the_query():
    """Condition 5: same query in, same three out -- no state, no model, no catalogue."""
    query = "Why is the spectator moved by what he watches rather than by his own life?"
    assert formulations(query) == formulations(query)
    assert formulations(query)[0] == query


def test_every_formulation_only_deletes_words():
    """The property that keeps the anchor out of the probe: no formulation adds a token the query lacked."""
    query = "What keeps people sunk in sleep?"
    original = {word.strip(",;:.?").lower() for word in query.split()}
    for form in formulations(query):
        assert {word.strip(",;:.?").lower() for word in form.split()} <= original


def test_f2_drops_stopwords_and_f3_drops_the_interrogative_frame():
    _, content, unframed = formulations("Why is the spectator moved by his own life?")
    assert not ({word.lower() for word in content.split()} & STOPWORDS)
    assert unframed.split()[0].lower() not in FRAME


@pytest.mark.parametrize("ranks,min_hits,k,expected", [
    ([1, 49], 2, 4, False),      # one anchor inside the window is not two
    ([1, 49], 2, 50, True),
    ([None], 1, 1000, False),    # outside the window at any k
    ([17], 1, 17, True),         # the boundary is inclusive
])
def test_passes_counts_only_anchors_inside_k(ranks, min_hits, k, expected):
    class Expectation:
        def __init__(self, hits):
            self.min_hits = hits

    class Entry:
        expected = {"A": Expectation(min_hits)}

    assert _passes(Entry(), "A", ranks, k) is expected


def test_no_derived_formulation_quotes_its_anchor():
    """Condition 6 over the real attested sample: deletion cannot add anchor vocabulary, but it can create an
    adjacency the query lacked, so the run check is run rather than assumed."""
    from ParallelProse.g2_reach import attested_entries
    for entry in attested_entries():
        for form in formulations(entry.query):
            runs = _word_runs(form, QUOTED_RUN)
            for expectation in entry.expected.values():
                for anchor in expectation.anchors:
                    assert not runs & _word_runs(anchor, QUOTED_RUN), (entry.id, form, anchor)
                    if entry.wording == "paraphrase":
                        assert not _content_terms(form) & _content_terms(anchor), (entry.id, form, anchor)
