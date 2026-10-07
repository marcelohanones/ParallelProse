from bs4 import BeautifulSoup

from ParallelProse.ingest import _block_text, _is_non_body_chapter, _join_split_words


def test_split_word_is_rejoined_when_the_whole_word_occurs_elsewhere():
    pages = ["the commod ity form, and commodity itself.", "commod ity again, a commodity here."]

    joined = _join_split_words(pages)

    assert joined[0] == "the commodity form, and commodity itself."
    assert joined[1] == "commodity again, a commodity here."


def test_ordinary_two_word_phrase_stays_apart_when_its_first_word_also_stands_alone():
    pages = ["to day is the day.", "today, and a to b.", "to be or not to be."]

    assert _join_split_words(pages)[0] == "to day is the day."


def _block(html):
    return BeautifulSoup(html, "html.parser").find()


def test_block_text_drops_a_bare_thesis_number_heading():
    assert _block_text(_block('<h3 class="num">35</h3>')) is None


def test_block_text_keeps_a_real_heading_or_paragraph():
    assert _block_text(_block("<h2>Chapter 2: The Commodity as Spectacle</h2>")) == "Chapter 2: The Commodity as Spectacle"
    assert _block_text(_block("<p>In the spectacle's basic practice...</p>")) == "In the spectacle's basic practice..."


def test_block_text_drops_an_empty_block():
    assert _block_text(_block("<p>   </p>")) is None


def test_non_body_chapters_are_recognized_case_and_quote_insensitively():
    assert _is_non_body_chapter("Index")
    assert _is_non_body_chapter("  CONTENTS  ")
    assert _is_non_body_chapter("Translator’s Note")  # curly apostrophe, as this epub's TOC spells it
    assert _is_non_body_chapter("Translator's Note")  # straight apostrophe


def test_real_chapters_are_not_flagged_as_non_body():
    assert not _is_non_body_chapter("1: The Culmination of Separation")
    assert not _is_non_body_chapter("Book I")
