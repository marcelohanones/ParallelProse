import json

from langchain_core.documents import Document

from ParallelProse.survey import (level0, level1, level2, run_survey, sentences_from_documents, term_pattern)

SENTENCES = [
    ("Ch1", "The crowd drew him into the arena."),
    ("Ch1", "A crowd cheered at the games."),
    ("Ch2", "He wept alone in the garden."),
    ("Ch2", "The arena was full of blood and noise."),
    ("Ch3", "Money changed hands in the market."),
    ("Ch3", "Coins and money filled the purse."),
]


class KeywordEmbedder:
    """Deterministic stand-in for OpenAIEmbeddings: one dimension per keyword, so similarity follows shared words."""
    KEYWORDS = ["crowd", "arena", "garden", "money", "coins", "games", "blood"]

    def _vector(self, text):
        lowered = text.lower()
        return [float(lowered.count(k)) for k in self.KEYWORDS]

    def embed_documents(self, texts):
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        return self._vector(text)


def test_term_pattern_matches_whole_words_only_and_any_whitespace():
    assert term_pattern("crowd").search("the crowd cheered")
    assert not term_pattern("crowd").search("crowds")
    assert term_pattern("money changed").search("money\nchanged hands")


def test_level0_counts_sentences_chapters_and_dense_sentences():
    result = level0(SENTENCES, ["crowd", "arena", "money"])

    assert result["sentences"] == 5
    assert result["chapters"] == 3
    assert result["dense_sentences"] == 1  # "The crowd drew him into the arena." has two terms
    assert result["per_term"] == {"crowd": 2, "arena": 2, "money": 2}


def test_level0_dense_counts_sentences_with_two_distinct_terms():
    result = level0([("C", "The crowd filled the arena.")], ["crowd", "arena"])

    assert result["dense_sentences"] == 1


def test_level1_proposes_cooccurring_words_and_excludes_the_term_itself():
    sentences = [("C", "crowd gathers at dawn"), ("C", "crowd gathers again"), ("C", "crowd and rain")]

    candidates = level1(sentences, ["crowd"])["candidates"]["crowd"]
    words = [c["word"] for c in candidates]

    assert "crowd" not in words
    assert "gathers" in words
    assert candidates[words.index("gathers")]["cooccurrences"] == 2


def test_level1_counts_only_approved_words():
    result = level1(SENTENCES, ["crowd"], approved={"crowd": ["arena"]})

    assert result["sentences"] == 2
    assert result["per_term"] == {"crowd": 2}
    assert result["approved"] == {"crowd": ["arena"]}


def test_level2_counts_sentences_above_a_calibrated_threshold(tmp_path):
    # Neutral filler sentences have no similarity to any theme, so the calibrated threshold stays low enough
    # for the crowd sentences (score > 0) to count, and nothing else does.
    filler = [("F", "The day passed slowly and quietly.")] * 200
    themes = [{"slug": "crowd", "title": "t", "terms": [], "description": "crowd arena games"},
              {"slug": "money", "title": "t", "terms": [], "description": "money coins"}]

    result = level2(SENTENCES + filler, themes, "crowd", KeywordEmbedder(), tmp_path / "cache.json")

    assert result["sentences"] == 3  # the two crowd sentences and the arena sentence
    assert result["threshold"] == 0.0
    assert (tmp_path / "cache.json").exists()


def test_level2_cache_avoids_embedding_the_same_sentences_twice(tmp_path):
    calls = []

    class Counting(KeywordEmbedder):
        def embed_documents(self, texts):
            calls.append(len(texts))
            return super().embed_documents(texts)

    themes = [{"slug": "a", "title": "t", "terms": [], "description": "crowd"},
              {"slug": "b", "title": "t", "terms": [], "description": "money"}]
    cache = tmp_path / "cache.json"
    level2(SENTENCES, themes, "a", Counting(), cache)
    level2(SENTENCES, themes, "a", Counting(), cache)

    assert calls == [len(SENTENCES)]


def test_notes_are_dropped_from_the_survey_text():
    documents = [Document(page_content="The crowd cheered. 164. the world dreams, cf. Marx's letter. Money changed.",
                          metadata={"chapter": "C"})]

    kept = [s for _, s in sentences_from_documents(documents, drop_notes=True)]

    assert not any("cf." in s for s in kept)
    assert any("crowd" in s for s in kept)


def test_run_survey_writes_one_file_per_theme_and_a_summary_that_flags_disagreement(tmp_path):
    themes = [{"slug": "crowd", "title": "Crowd", "terms": ["crowd"], "description": "crowd arena games"},
              {"slug": "money", "title": "Money", "terms": ["money"], "description": "money coins"}]

    paths = run_survey("A", SENTENCES, themes, levels=(0, 1, 2), approved={"money": {"money": ["coins"]}},
                       embedder=KeywordEmbedder(), output_dir=tmp_path)

    assert [p.name for p in paths] == ["crowd.json", "money.json"]
    record = json.loads((tmp_path / "A" / "money.json").read_text())
    assert set(record) >= {"level0", "level1", "level2", "provisional_notes_filter"}
    assert record["level1"]["sentences"] == 1  # only "Coins and money filled the purse." has "coins"
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert {row["theme"] for row in summary} == {"crowd", "money"}
    assert all("disagree" in row for row in summary)
