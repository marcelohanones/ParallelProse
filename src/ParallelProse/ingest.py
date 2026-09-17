
import warnings
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from pypdf import PdfReader

warnings.filterwarnings("ignore")
load_dotenv()


REPO_ROOT = Path(__file__).resolve().parents[2]
PDF_PATH = REPO_ROOT / "data" / "O-príncipe-Nicolau-Maquiavel.pdf"


def concat(docs: list[Document], start: int, end: int) -> str:
    return "\n".join(docs[i].page_content for i in range(start, end))


def load_corpus(pdf_path: str) -> list[Document]:
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

