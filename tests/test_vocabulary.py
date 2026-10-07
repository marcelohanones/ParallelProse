import json
from collections import Counter

from ParallelProse.vocabulary import distinctive_words, load_vocabulary, lookup, save_vocabulary, write_reference_document

VOCAB = Counter({"spectacle": 12, "commodity": 5, "separation": 3})


def test_lookup_finds_an_existing_word_case_insensitively():
    result = lookup("Spectacle", VOCAB)

    assert result == {"term": "Spectacle", "exists": True, "count": 12, "nearest": []}


def test_lookup_suggests_the_books_own_nearest_words_when_absent():
    result = lookup("comodity", VOCAB)

    assert result["exists"] is False
    assert result["count"] == 0
    assert result["nearest"][0] == {"word": "commodity", "count": 5}


def test_lookup_returns_no_suggestions_when_nothing_is_close():
    result = lookup("xyzxyz", VOCAB)

    assert result == {"term": "xyzxyz", "exists": False, "count": 0, "nearest": []}


def test_save_and_load_vocabulary_round_trip(tmp_path):
    path = save_vocabulary("A", VOCAB, output_dir=tmp_path)

    assert path == tmp_path / "A.json"
    assert json.loads(path.read_text()) == dict(VOCAB)
    assert load_vocabulary("A", input_dir=tmp_path) == VOCAB


def test_distinctive_words_drops_stopwords_and_short_words_and_ranks_by_frequency():
    vocab = Counter({"spectacle": 12, "the": 500, "of": 400, "is": 20, "commodity": 5})

    assert distinctive_words(vocab) == [("spectacle", 12), ("commodity", 5)]


def test_distinctive_words_respects_the_limit():
    vocab = Counter({"spectacle": 12, "commodity": 5, "separation": 3})

    assert distinctive_words(vocab, limit=2) == [("spectacle", 12), ("commodity", 5)]


def test_write_reference_document_lists_words_with_counts(tmp_path):
    path = write_reference_document("A", VOCAB, output_dir=tmp_path, limit=10)

    assert path == tmp_path / "A_reference.md"
    text = path.read_text()
    assert "spectacle (12)" in text
    assert "The Confessions of Saint Augustine" in text
