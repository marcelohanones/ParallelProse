"""The pure parts of G2's expansion round: the feedback vocabulary, the probe, the fusion and the condition-6
guard. The retrieval itself is not tested here (it needs the stores, and the dense channel needs the API)."""
import pytest

from ParallelProse.evaluation import load_golden_set, golden_set_path
from ParallelProse.g2_expand import agree, expansion_probe, expansion_terms, fuse, hits_in


def test_expansion_terms_prefers_the_word_spread_over_the_passages():
    """Document frequency decides: a word in both passages beats one repeated five times inside a single one."""
    passages = ["memory memory memory forgetfulness", "memory buried"]
    terms = expansion_terms(passages, "how is the past forgotten?")
    assert terms[0] == "memory"
    assert "forgetfulness" in terms


def test_expansion_terms_are_a_pure_function_and_never_carry_the_query():
    passages = ["the spectator contemplates the spectacle", "the spectacle is a social relation"]
    query = "Why is the spectator moved by what he watches?"
    assert expansion_terms(passages, query) == expansion_terms(passages, query)
    assert not (set(expansion_terms(passages, query)) & {"spectator", "watches", "moved"})


def test_expansion_terms_drop_stopwords_and_short_words():
    terms = expansion_terms(["the of and to a in is it that was for on are as with his they"], "what is it?")
    assert terms == []


def test_expansion_probe_falls_back_to_the_query_when_the_material_adds_nothing():
    """No new vocabulary is an answer, not an error: the second probe is then the first, and the fusion is a
    no-op."""
    query = "What keeps people sunk in sleep?"
    assert expansion_probe(query, ["the of and to a in is it"]) == query
    assert expansion_probe(query, []) == query


def test_fuse_is_reciprocal_rank_fusion_with_the_projects_constant():
    """The sum of 1/(60 + position) over the passes: a top position in one pass outweighs a middling position in
    both, and a unit both passes saw at all beats one only a single pass returned."""
    first = ["a", "b", "c", "d"]
    second = ["c", "b", "d", "e"]
    fused = fuse(first, second)
    scores = {}
    for ranking in (first, second):
        for position, unit in enumerate(ranking, 1):
            scores[unit] = scores.get(unit, 0.0) + 1.0 / (60 + position)
    assert fused == sorted(scores, key=lambda unit: (-scores[unit], str(unit)))
    assert fused.index("c") < fused.index("a")   # 1st + 3rd beats 1st alone
    assert fused.index("e") == len(fused) - 1    # seen by one pass only, at its last position
    assert fused == fuse(first, second)


@pytest.mark.parametrize("k,expected", [(1, 0), (2, 1), (3, 2)])
def test_hits_in_reads_the_anchor_inside_the_delivered_prefix(k, expected):
    texts = ["nothing here at all", "the auditor is not called on to relieve", "weeping not his own death"]
    anchors = ["the auditor is not called on to relieve", "weeping not his own death"]
    assert hits_in(texts, anchors, k) == expected


def test_agree_rejects_a_probe_that_quotes_an_anchor_four_words_running():
    """Condition 6 is mechanical: the golden set's own run check, applied to the expanded probe."""
    entry = next(e for e in load_golden_set(golden_set_path) if e.wording == "book")
    anchor = entry.expected["A"].anchors[0]
    ok, reason = agree(entry, f"{entry.query} {anchor}")
    assert not ok
    assert "4 words in a row" in reason


def test_agree_rejects_a_paraphrase_probe_sharing_one_content_term_with_an_anchor():
    entry = next(e for e in load_golden_set(golden_set_path)
                 if e.wording == "paraphrase" and "A" in e.expected and e.expected["A"].label == "ok")
    anchor_term = sorted(__import__("ParallelProse.textform", fromlist=["x"])._content_terms(
        entry.expected["A"].anchors[0]))[0]
    ok, reason = agree(entry, f"{entry.query} {anchor_term}")
    assert not ok
    assert "paraphrase" in reason


def test_agree_accepts_the_query_itself():
    """The guard must not reject the probe the round already runs: every attested entry passes on its own query."""
    for entry in load_golden_set(golden_set_path):
        if all(expectation.label == "ok" for expectation in entry.expected.values()):
            ok, reason = agree(entry, entry.query)
            assert ok, f"{entry.id}: {reason}"
