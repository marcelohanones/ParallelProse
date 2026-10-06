from dotenv import load_dotenv

load_dotenv()
import re
import warnings
from collections import Counter
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
WORD = re.compile(r"[A-Za-z]+")
TOKEN = re.compile(r"[A-Za-z]+|\s+|[^A-Za-z\s]+")


def _is_word_pair(tokens: list[str], i: int) -> bool:
    return bool(WORD.fullmatch(tokens[i]) and tokens[i + 1].isspace() and WORD.fullmatch(tokens[i + 2]))


def _join_split_words(pages: list[str]) -> list[str]:
    """Rejoins words the PDF split with a space (e.g. 'commod ity'). A pair (a, b) is joined when a+b occurs as a word elsewhere in the text
    and at least 90% of a's occurrences are such pairs, so a is only ever a fragment. Ordinary two-word phrases ('to day') stay apart,
    because 'to' also stands alone."""
    words = Counter(w.lower() for text in pages for w in WORD.findall(text))
    pairs = Counter()
    for text in pages:
        tokens = TOKEN.findall(text)
        for i in range(len(tokens) - 2):
            if _is_word_pair(tokens, i):
                pairs[(tokens[i].lower(), tokens[i + 2].lower())] += 1
    fragment_pairs = Counter()
    for (a, b), n in pairs.items():
        if words[a + b] >= 1:
            fragment_pairs[a] += n
    joins = {(a, b) for (a, b) in pairs if words[a + b] >= 1 and fragment_pairs[a] >= 0.9 * words[a]}

    joined_pages = []
    for text in pages:
        tokens = TOKEN.findall(text)
        out, i = [], 0
        while i < len(tokens):
            if i + 2 < len(tokens) and _is_word_pair(tokens, i) and (tokens[i].lower(), tokens[i + 2].lower()) in joins:
                out.append(tokens[i] + tokens[i + 2])
                i += 3
            else:
                out.append(tokens[i])
                i += 1
        joined_pages.append("".join(out))
    return joined_pages


# Splits the automatic rule cannot tell from ordinary two-word phrases: the whole word never occurs intact in this PDF.
KNOWN_PDF_SPLITS = [
    (re.compile(r"\bmonolog\s+ue\b"), "monologue"),
    (re.compile(r"\brepresen\s+tation\b"), "representation"),
    (re.compile(r"\bRepresen\s+tation\b"), "Representation"),
    (re.compile(r"\brepresen\s+tative\b"), "representative"),
    (re.compile(r"\bRepresen\s+tative\b"), "Representative"),
]


def _pdf_pages(pdf_path: str) -> list[Document]:
    """One Document per page, in plain extraction order. Layout order merges the margin notes into the body text (a thesis number lands
    mid-sentence), so plain order is used, with the PDF's hidden hyphens dropped, split words rejoined, and the KNOWN_PDF_SPLITS fixed."""
    texts = [re.sub(r"­\s*", "", page.extract_text() or "") for page in PdfReader(pdf_path).pages]
    texts = _join_split_words(texts)
    for pattern, whole in KNOWN_PDF_SPLITS:
        texts = [pattern.sub(whole, text) for text in texts]
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
def _load_epub(path: str) -> list[Document]:
    """Walk the spine in reading order; each HTML chapter file becomes one Document."""
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
