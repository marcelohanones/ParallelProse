from bs4 import BeautifulSoup

from ParallelProse.ingest import _block_text, _is_body_item, _is_non_body_chapter


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


def _blocks(html):
    return BeautifulSoup(html, "html.parser").find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"])


PROSE = "<p>" + " ".join(["word"] * 25) + "</p>"


def test_an_item_named_in_the_nav_and_listed_as_non_body_is_dropped_even_when_it_is_real_prose():
    # the translator's note: 1.6K chars of prose no structural rule can tell from a chapter
    assert not _is_body_item(_blocks(PROSE), "Translator’s Note")


def test_an_item_with_no_nav_entry_falls_to_the_prose_test_not_to_its_file_name():
    assert not _is_body_item(_blocks("<p>*</p>"), None)  # 54_split_001.html, one character
    assert _is_body_item(_blocks(PROSE), None)


def test_a_nav_title_outside_the_list_still_falls_to_the_prose_test():
    # 54_split_000.html is the title page, and the nav names it with the book's own title: no list anticipates that
    assert not _is_body_item(_blocks("<h1>THE CONFESSIONS OF ST. AUGUSTINE</h1>"), "THE CONFESSIONS OF ST. AUGUSTINE")


def test_short_blocks_never_add_up_to_prose():
    # the Spectacle's index: 85 blocks, the largest 11 words
    assert not _is_body_item(_blocks("<p>short line</p>" * 85), "Not In The List")


def test_block_text_drops_a_typographic_ornament():
    # the Confessions prints a `*` between Books and a `* * *` at the end: fourteen blocks with no word in them
    assert _block_text(_block('<h2 class="decoration">*</h2>')) is None
    assert _block_text(_block("<p>* * *</p>")) is None
