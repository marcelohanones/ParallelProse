import html
import warnings
from pathlib import Path

import ebooklib
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from pypdf import PdfReader
from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub


warnings.filterwarnings("ignore")
load_dotenv()


REPO_ROOT = Path(__file__).resolve().parents[2]
PDF_PATH = REPO_ROOT / "data" / "data/The_Society_of_the_Spectacle_(Annotated Edition)-Guy_Debord.pdf"
EPUB_PATH = REPO_ROOT / "data"/ "The_Confessions_Of_Saint_Augustine-Saint_Augustine_Pusey_Edward_Bouverie-2017-Duke Classics.epub"

def _load_epub(path: str) -> list[Document]:
    """One Document per chapter: page_content = chapter text without HTML tags,
    metadata={"chapter": title from the table of contents}."""
    # TODO 1: open the epub with ebooklib.
    # TODO 2: walk the spine (reading order), keeping only the HTML document items
    #         (skip images, css, cover).
    # TODO 3: strip each item's HTML down to plain text with BeautifulSoup.
    # TODO 4: find that item's title in the table of contents.
    # TODO 5: skip items whose text comes out empty (title pages and the like).


def load_corpus(path: str) -> list[Document]:
    """Dispatch on the file extension: .pdf -> _load_pdf, .epub -> _load_epub,
    anything else -> raise ValueError."""
    # TODO: get the suffix (pathlib), lowercase it, branch.

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


def _load_epub(path: str) -> list[Document]:
    book = epub.read_epub(path)
    titles = _flatten_toc(book.toc)
    documents = []
    for idref, _ in book.spine:
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ITEM_DOCUMENT or isinstance(item, epub.EpubNav):
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        blocks = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"])
        paragraphs = (b.get_text().strip() for b in blocks)
        text = "\n".join(p for p in paragraphs if p)
        if not text:
            continue
        chapter = titles.get(item.get_name(), item.get_name())
        documents.append(Document(page_content=text, metadata={"chapter": chapter}))
    return documents



def concat(docs: list[Document], start: int, end: int) -> str:
    return "\n".join(docs[i].page_content for i in range(start, end))


def _load_pdf(pdf_path: str) -> list[Document]:
    """This function loads the pdf file and concatenates the content of each charpter keeping the metadata. It returns a list of Documents(page_content=str, metadata=charpter)
    """
    pdf_docs = PyPDFLoader(str(pdf_path)).load()

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
        document_list.append(Document(page_content=concat(pdf_docs,start, end), metadata={"chapter": title}))
    return document_list

if __name__ == "__main__":
    print(len(load_corpus(str(PDF_PATH))[0].page_content))

