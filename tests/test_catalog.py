from ParallelProse.catalog import CATALOG


def test_every_book_carries_its_edition_metadata():
    for book in CATALOG.values():
        assert book.translator and book.year and book.publisher
