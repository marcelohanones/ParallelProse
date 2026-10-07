import json
from collections import Counter

from ParallelProse.vocabulary import load_vocabulary, lookup, save_vocabulary

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
