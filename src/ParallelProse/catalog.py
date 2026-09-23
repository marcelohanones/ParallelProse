from pathlib import Path
from dataclasses import dataclass

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"


@dataclass(frozen=True)
class Book:
    book_title: str
    author: str
    collection_name: str
    file_name: str

    @property
    def path(self) -> Path:
        return REPO_ROOT / "data" / self.file_name


# _________PER - PROJECT SETTINGS
CHROMA_PERSIST_DIR = DATA_DIR / "confessions_spectacle"

CATALOG: dict[str, Book] = {
    "A": Book(
        book_title="The Confessions of Saint Augustine",
        author="Saint Augustine",
        collection_name="augustine_confessions",
        file_name="The_Confessions_Of_Saint_Augustine-Saint_Augustine.epub"),
    "B":
        Book(
            book_title="The Society of the Spectacle",
            author="Guy Debord",
            collection_name="debord_spectacle",
            file_name="The_Society_of_the_Spectacle_(Annotated Edition)-Guy_Debord.pdf")
}
