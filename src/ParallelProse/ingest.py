from dotenv import load_dotenv

load_dotenv()
import re
import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub
from langchain_core.documents import Document
from pypdf import PdfReader

warnings.filterwarnings("ignore")


# MARK: ENTRY POINT
def load_corpus(path: str) -> list[Document]:
    """Dispatch on the file extension: .pdf -> _load_pdf, .epub -> _load_epub,
    anything else -> ValueError. Every format returns one Document per chapter,
    with metadata={"chapter": title}."""
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return _load_pdf(path)
    if suffix == ".epub":
        return _load_epub(path)
    raise ValueError(f"Unsupported corpus format {suffix!r}: {path}")


# MARK: PDF BRANCH
def _pdf_pages(pdf_path: str) -> list[Document]:
    """One Document per page, in plain extraction order, with the PDF's hidden (soft) hyphens dropped."""
    texts = [re.sub(r"­\s*", "", page.extract_text() or "") for page in PdfReader(pdf_path).pages]
    return [Document(page_content=re.sub(r"[ \t]+", " ", text)) for text in texts]


def _load_pdf(pdf_path: str) -> list[Document]:
    """This function loads the pdf file and concatenates the content of each chapter keeping the metadata. It returns a list of Documents(page_content=str, metadata=chapter)
    """
    pdf_docs = _pdf_pages(pdf_path)

    reader = PdfReader(pdf_path)
    outline = reader.outline  # flat list of Destination objects (39 entries here)

    # pairs (title, page_number)
    pairs = [(entry["/Title"], reader.get_destination_page_number(entry)) for entry in outline]

    # ranges (title, start_page, end_page)
    ranges = []
    document_list = []
    for idx, (title, start) in enumerate(pairs):
        end = pairs[idx + 1][1] if idx + 1 < len(pairs) else len(pdf_docs)
        ranges.append((title, start, end))
        document_list.append(Document(page_content=concat(pdf_docs, start, end), metadata={"chapter": title}))
    return document_list


def concat(docs: list[Document], start: int, end: int) -> str:
    return "\n".join(docs[i].page_content for i in range(start, end))


# MARK: EPUB BRANCH
# Chapters that carry no part of the author's own argument: structural front/back matter (title page, contents,
# index), or prose that belongs to the translator rather than the author (a translator's note) — comparable to
# the editorial-notes problem filtered elsewhere, so it is excluded by name here rather than risk a quote later
# being attributed to the author.
NON_BODY_CHAPTERS = frozenset({"title page", "half title", "contents", "table of contents", "index",
                               "translator's note", "cover"})


def _block_text(block) -> str | None:
    """A block's text, or None if it carries no word of the book: empty, a bare chapter/thesis number heading (an
    edition that puts each thesis number in its own <h3>), or a typographic ornament. The Confessions prints a
    `*` between its Books and a `* * *` at the end -- fourteen blocks with no word character in them, which as
    paragraphs would take an address of their own, shift every address after them, and be counted as passages."""
    text = block.get_text().strip()
    if not text or text.isdigit() or not re.search(r"\w", text):
        return None
    return text


def _is_non_body_chapter(title: str) -> bool:
    return title.strip().lower().replace("’", "'") in NON_BODY_CHAPTERS


PROSE_WORDS = 20  # a block of this many words is prose; apparatus never reaches it (measured: largest apparatus
# block is 14 words, in the Spectacle's index, while every body chapter carries 11 to 70 blocks above it)


def _is_body_item(blocks, nav_title: str | None) -> bool:
    """Is this spine item the author's body text? Two rules, in order, because neither covers the other:

    1. **The name, but only when the book gave one.** `NON_BODY_CHAPTERS` applies to an item that has a nav entry,
       and only then -- a file name is not a name. This is what drops a translator's note, whose 1.6K chars of real
       prose no structural rule can tell from a chapter; the book naming the section is the only signal there is.
       Declared residual risk: a future edition titling it "A Note on the Translation" escapes the list, the prose
       test keeps it, and the translator's prose would be attributed to the author. Adding a book means looking at
       this section.
    2. **Prose, for everything else.** At least one block of PROSE_WORDS words. This is what drops the four items
       the list never caught: three with no nav entry at all (`half.html`, `54_split_001/003.html`) and one whose
       nav title is the book's own title (`54_split_000.html`), which no list of section names can anticipate.
    """
    if nav_title is not None and _is_non_body_chapter(nav_title):
        return False
    return any(len(text.split()) >= PROSE_WORDS for text in (_block_text(b) or "" for b in blocks))


@dataclass(frozen=True)
class Paragraph:
    """One paragraph of a book, and its address. The address is born here, in the ingest, and nowhere else: the
    chunking layer must not mint a second one (a rebuild would then hold two ids for the same paragraph).

    `quoted` marks a paragraph the author quotes rather than asserts, with `source` carrying the attribution the
    edition prints -- the Spectacle opens each of its nine chapters with one (Feuerbach, Lukacs, Shakespeare,
    Machiavelli, Hegel and four more). Flattened into the chapter text, as they were, a claim citing one came back
    verbatim from the book and was credited to its author.
    """
    index: int  # position in the book, counting body paragraphs only
    chapter: str
    chapter_seq: int  # position within the chapter
    text: str  # as written
    quoted: bool = False
    source: str | None = None


def _attribution(blockquote) -> str | None:
    """The source line an edition prints under a quoted block, if it marks one."""
    attrib = blockquote.find("p", class_="attrib")
    return " ".join(attrib.get_text().split()) if attrib else None


@lru_cache
def epub_paragraphs(path: str) -> tuple[Paragraph, ...]:
    """Every body paragraph of an epub, in reading order, with its address and its quotation marks.

    The single source for both the chapter Documents (`_load_epub` groups these) and the passage layer
    (`quote_check.book_paragraphs` reads these) -- one function, so the two cannot drift apart and the paragraph
    index means the same thing on both sides.
    """
    book = epub.read_epub(path)
    titles = _flatten_toc(book.toc)
    paragraphs, index = [], 0
    for idref, _ in book.spine:
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ITEM_DOCUMENT or isinstance(item, epub.EpubNav):
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        blocks = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"])
        nav_title = titles.get(item.get_name())
        if not _is_body_item(blocks, nav_title):
            continue
        chapter = nav_title if nav_title is not None else item.get_name()
        seq = 0
        for block in blocks:
            text = _block_text(block)
            if not text:
                continue
            blockquote = block.find_parent("blockquote")
            if blockquote is not None and block.get("class") and "attrib" in block.get("class"):
                continue  # the attribution travels as `source`, never as a paragraph of the book
            paragraphs.append(Paragraph(
                index=index, chapter=chapter, chapter_seq=seq, text=text,
                quoted=blockquote is not None,
                source=_attribution(blockquote) if blockquote is not None else None))
            index += 1
            seq += 1
    return tuple(paragraphs)


def _load_epub(path: str) -> list[Document]:
    """One Document per chapter, built from `epub_paragraphs` so the Document text and the paragraph addresses
    come from the same split. Paragraphs are joined with "\n\n": that blank line is the parent splitter's break
    point (retrieve.py), which is what keeps a chunk boundary off the middle of a paragraph."""
    chapters: dict[str, list[str]] = {}
    for paragraph in epub_paragraphs(path):
        chapters.setdefault(paragraph.chapter, []).append(paragraph.text)
    return [Document(page_content="\n\n".join(texts), metadata={"chapter": chapter})
            for chapter, texts in chapters.items() if texts]


def _flatten_toc(entries) -> dict[str, str]:
    """Flatten ebooklib's nested table of contents into {file name: title}."""
    titles = {}
    for entry in entries:
        if isinstance(entry, tuple):
            section, children = entry
            titles.setdefault(section.href.split("#")[0], section.title)
            for href, title in _flatten_toc(children).items():
                titles.setdefault(href, title)
        else:
            titles.setdefault(entry.href.split("#")[0], entry.title)
    return titles


if __name__ == "__main__":
    from ParallelProse.catalog import CATALOG

    print(len(load_corpus(str(CATALOG["B"].path))[0].page_content))
