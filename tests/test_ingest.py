from ParallelProse.ingest import _join_split_words


def test_split_word_is_rejoined_when_the_whole_word_occurs_elsewhere():
    pages = ["the commod ity form, and commodity itself.", "commod ity again, a commodity here."]

    joined = _join_split_words(pages)

    assert joined[0] == "the commodity form, and commodity itself."
    assert joined[1] == "commodity again, a commodity here."


def test_ordinary_two_word_phrase_stays_apart_when_its_first_word_also_stands_alone():
    pages = ["to day is the day.", "today, and a to b.", "to be or not to be."]

    assert _join_split_words(pages)[0] == "to day is the day."
