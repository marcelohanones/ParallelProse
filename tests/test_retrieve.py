import pytest

from ParallelProse.mcp_tools import REGISTRY

PARENT_CHARS = 4000


def test_bm25_returns_parent_chunks_for_a_keyword():
    docs = REGISTRY["A"].make_bm_25_retriever().invoke("Alypius")
    assert docs
    assert all(len(d.page_content) <= PARENT_CHARS for d in docs)
    assert all("Alypius" in d.page_content for d in docs)


@pytest.mark.parametrize("corpus", ["A", "B"])
def test_bm25_results_are_capped_at_parent_size(corpus):
    docs = REGISTRY[corpus].make_bm_25_retriever().invoke("crowd")
    assert docs
    assert all(len(d.page_content) <= PARENT_CHARS for d in docs)


def test_the_child_splitter_has_no_separator_to_depend_on():
    from dataclasses import fields

    from ParallelProse.retrieve import ChildSplitterConfig, SplitterConfig

    assert "separator" not in {f.name for f in fields(ChildSplitterConfig)}
    assert SplitterConfig(chunk_size=4000, chunk_overlap=100).separator == "\n\n"
