import os
import warnings
from dataclasses import asdict, dataclass

import chromadb
from chromadb.errors import NotFoundError
from dotenv import load_dotenv
from langchain_classic.chains.query_constructor.base import AttributeInfo
from langchain_classic.retrievers import (
    EnsembleRetriever,
    ParentDocumentRetriever,
    SelfQueryRetriever,
)
from langchain_classic.storage import LocalFileStore, create_kv_docstore
from langchain_community.query_constructors.chroma import ChromaTranslator
from langchain_community.retrievers import BM25Retriever
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import CharacterTextSplitter

from ParallelProse.ingest import PDF_PATH, REPO_ROOT, load_corpus

warnings.filterwarnings("ignore")
load_dotenv()

CHROMA_PERSIST_DIR = REPO_ROOT / "data" / "chroma_demo_c1_project"


# // MARK: Retrieval
@dataclass
class SplitterConfig:
    chunk_size: int
    chunk_overlap: int
    separator: str = "\n"


class Retrieval:
    def __init__(
        self,
        collection_name,
        pdf_path,
        llm=ChatOpenAI(model="gpt-4o-mini", temperature=0.5),
        child_config=SplitterConfig(chunk_size=400, chunk_overlap=50),
        parent_config=SplitterConfig(chunk_size=4000, chunk_overlap=100),
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_model=OpenAIEmbeddings(
            model="text-embedding-3-small", api_key=os.environ.get("OPENAI_API_KEY")
        ),
    ):
        self.collection_name = collection_name
        self.pdf_path = pdf_path
        self.llm = llm
        self.child_config = child_config
        self.parent_config = parent_config
        self.persist_directory = str(persist_directory)
        self.embedding_model = embedding_model
        self.vector_store = self.make_vector_store()
        self.doc_store = self.make_docstore()
        self.child_splitter = self.make_child_splitter()
        self.parent_splitter = self.make_parent_splitter()
        self.parent_retriever = self.make_parent_retriever()

    def make_child_splitter(self):
        return CharacterTextSplitter(**asdict(self.child_config))

    def make_parent_splitter(self):
        return CharacterTextSplitter(**asdict(self.parent_config))

    def make_vector_store(self):
        return Chroma(
            collection_name=self.collection_name,
            persist_directory=self.persist_directory,
            embedding_function=self.embedding_model,
        )

    def make_docstore(self):
        name = self.collection_name + "_project"
        return create_kv_docstore(LocalFileStore(REPO_ROOT / "data" / name))

    def make_parent_retriever(self):
        return ParentDocumentRetriever(
            vectorstore=self.vector_store,
            docstore=self.doc_store,
            child_splitter=self.child_splitter,
            parent_splitter=self.parent_splitter,
        )

    def add_parent_child_docs(self, rebuild: bool = False):
        """this function controls wether to build the database. It re-split the corpus to get the expected number of chunks. Then compare it against vector_store and doc_store to avoid unecessary re-embedding.
        The decision tree is:
        if not rebuild and ==N -> return as is
        everything else -> drop and rebuild"""

        # LOADING DATA
        corpus = load_corpus(str(self.pdf_path))
        retriever_int = self.parent_retriever
        # RE-SPLITING
        parent = retriever_int.parent_splitter.split_documents(corpus)
        child = []
        for p in parent:
            child.extend(retriever_int.child_splitter.split_documents([p]))
        parent_match = len(parent) == len(list(retriever_int.docstore.yield_keys()))
        # COUNTING
        try:
            count = retriever_int.vectorstore._collection.count()
        except NotFoundError:
            count = 0
        child_match = len(child) == count
        # DECIION TREE
        if not rebuild and (parent_match and child_match):
            print("parent and child matches vector_store and docstore")
            print("nothing loaded")
        else:
            # DROP REBUILD
            keys = list(retriever_int.docstore.yield_keys())
            retriever_int.docstore.mdelete(keys)
            client = chromadb.PersistentClient(path=self.persist_directory)
            client.delete_collection(name=self.collection_name)
            retriever_int.vectorstore = (
                self.make_vector_store()
            )  # create new vectorstore within ParentDocumentRetriever
            self.vector_store = (
                self.parent_retriever.vectorstore
            )  # update vectorstore on Chroma to unify and avoid stale reference.
            retriever_int.add_documents(corpus)
            print("corpus is loaded")

    def make_metadata_field_info(self):
        """This function set the attributes that explain the corpus."""
        return [AttributeInfo(name="chapter", description="the chapter it belongs", type="string")]

    def make_search_self_query(self, query: str, description: str) -> list[Document]:
        """This function retrieves child chunks through SelfQueryRetriever, fetch it's id's and returns the correspondent parents in a list."""
        retriever = SelfQueryRetriever.from_llm(
            self.llm,
            self.vector_store,
            document_contents=description,
            metadata_field_info=self.make_metadata_field_info(),
            structured_query_translator=ChromaTranslator(),
        )
        query_answer = retriever.invoke(query)
        ids = list({i.metadata["doc_id"] for i in query_answer})  # dedup
        docs = [i for i in self.doc_store.mget(ids) if i is not None]  # remove None
        return docs

    def make_bm_25_retriever(self):
        """This function creates a BM25 instance retriever."""
        return BM25Retriever.from_documents(
            documents=load_corpus(str(self.pdf_path)), bm25_params={"k1": 1.5, "b": 0.75}
        )

    def make_ensemble_retriever(self):
        """
        This function creates an Ensemble retriever instance.
        """
        return EnsembleRetriever(
            retrievers=[self.make_bm_25_retriever(), self.parent_retriever], weights=[0.5, 0.5]
        )


# // MARK: callers

# flow 1 similarity_search
# retrieval_obj.add_parent_child_docs()
# response = retrieval_obj.parent_retriever.invoke("em quais capitulos o autor fala sobre fortuna ?")

# flow 2 - filtering
# retrieval_obj.parent_retriever.search_kwargs = {"filter": {"chapter": "Capítulo 25"}}
# response = retrieval_obj.parent_retriever.invoke("fortuna")
# print(response)


if __name__ == "__main__":
    retrieval_obj = Retrieval(collection_name="class_testing", pdf_path=PDF_PATH)
    retrieval_obj.add_parent_child_docs()
    # description = "A chunk of text from Machiavelli's 'The Prince'"
    # print(retrieval_obj.make_search_self_query("em quais capitulos o autor fala sobre fortuna ?", description))
    # flow 3
    retrieval_obj.make_bm_25_retriever()
    print(
        retrieval_obj.make_ensemble_retriever().invoke(
            "em quais capitulos o autor fala sobre fortuna ?"
        )
    )
