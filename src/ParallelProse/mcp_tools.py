from dotenv import load_dotenv

load_dotenv()
import asyncio

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
import copy

from ParallelProse.ingest import PDF_PATH, EPUB_PATH
from ParallelProse.retrieve import Retrieval

mcp = FastMCP(name="RetrievalServer", instructions="Provide Retrieval Methods")
collection_nameA = "augustine_confessions"
collection_nameB = "debord_spectacle"
REGISTRY = {
    "A": Retrieval(collection_name=collection_nameA, source_path=EPUB_PATH),
    "B": Retrieval(collection_name=collection_nameB, source_path=PDF_PATH)
}

for v in REGISTRY.values():
    v.add_parent_child_docs()


# MARK: TOOLS
@mcp.tool
def call_parent_retriever(query: str, corpus: str) -> list[str]:
    """Semantic search: matches the query against small child chunks by meaning and returns their larger parent chunks, so each result comes with surrounding context.
    Use it by default, for concepts, themes and open questions (e.g. "what does the author say about '<a subject>'  ?"), where the wording of the query may differ from the wording of the text.
    Avoid it when the query hinges on one exact name or word; use call_bm_25_retriever for that."""
    return [i.page_content for i in REGISTRY[corpus].parent_retriever.invoke(query)]


@mcp.tool
def call_search_self_query(query: str, description: str, corpus: str) -> list[str]:
    """Filtered semantic search: turns the query into a similarity search plus a metadata filter on `chapter`, then returns the parent chunks of the matches.
    Use it only when the query names a specific chapter (e.g. "what does chapter 25 say about '<a subject>' ? "); otherwise the filter has nothing to filter on.
    `description` is one short sentence saying what the corpus text is (e.g. "A chunk of text from '<book title>'"); it is not the query."""
    return [i.page_content for i in REGISTRY[corpus].make_search_self_query(query, description)]


@mcp.tool
def call_bm_25_retriever(query: str, corpus: str) -> list[str]:
    """Exact keyword match (BM25): ranks chunks by how many of the query's words they contain, with no understanding of meaning.
    Use it when the query hinges on a specific name, title, rare word or quoted phrase.
    Avoid it for paraphrased or conceptual questions: a synonym or a different wording will not match, and it can return nothing relevant."""
    return [i.page_content for i in REGISTRY[corpus].make_bm_25_retriever().invoke(query)]


@mcp.tool
def call_ensemble_retriever(query: str, corpus: str) -> list[str]:
    """Hybrid search: blends call_bm_25_retriever and call_parent_retriever, weighting each 0.5, so results can match by meaning and by exact words.
    Use it when the query mixes a concept with a specific name or term (e.g. "<a person's name> and what it shows about a broader theme"), or when neither single method fits.
    It is slower than either one alone, so prefer a single retriever when the query clearly fits one."""
    return [i.page_content for i in REGISTRY[corpus].make_ensemble_retriever().invoke(query)]


PORT = 8931
http_client = Client(StreamableHttpTransport(url=f"http://127.0.0.1:{PORT}/mcp"))


# MARK: BRIDGE TO LANGCHAIN
async def mcp_tools_as_langchain_tools(client: Client, corpus: str) -> list[StructuredTool]:
    async with client:
        mcp_tools = await client.list_tools()  # ask the server for tool's params. (has corpus).

    def wrap(mcp_tool):
        dict_no_corpus = copy.deepcopy(mcp_tool.input_schema)
        dict_no_corpus["properties"].pop("corpus")
        dict_no_corpus["required"].remove("corpus")

        async def call(**kwargs):
            async with client:
                kwargs["corpus"] = corpus
                result = await client.call_tool(mcp_tool.name, kwargs)
            return result.data

        return StructuredTool.from_function(
            coroutine=call,
            name=mcp_tool.name,
            description=mcp_tool.description or "",
            args_schema=dict_no_corpus,
            # the "copy" of input_schema the model sees, without corpus. See the hiding bellow.
        )

    result = [wrap(i) for i in mcp_tools]
    return result


# The hiding: the motivation is that model's decision on what corpus to use is non-deterministic. So, we hide corpus from model and insert it by code.
# 1 -  The 1st step is to pop out corpus key from the mcp_tool.input_schema dict (dict_no_corpus) and hand it out to args_schema. So, the model will not see corpus.
# 2 - the 2nd is, on call function, to add corpus key to kwargs and let closure fills it's value. So the tool sees the corpus.
# Bottom Line: we hide corpus from the model and put it back for the tool.

async def main():
    server_task = asyncio.create_task(
        mcp.run_http_async(port=PORT, show_banner=False, log_level="critical")
    )
    await asyncio.sleep(1.0)
    print(f"Serving on http://127.0.0.1:{PORT}/mcp")

    async with http_client as client:
        tools = await client.list_tools()
        print("Available Tools over http:", [i.name for i in tools])
    bridged_tools = await mcp_tools_as_langchain_tools(http_client, "B")

    agent = create_agent(model=ChatOpenAI(model="gpt-4o-mini"), tools=bridged_tools)
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="In what year was Society of the Spectacle written ?")]}
    )
    print(result["messages"][-1].content)

    server_task.cancel()


# MARK: Main
if __name__ == "__main__":
    asyncio.run(main())


    async def test_retriever():
        server_task = asyncio.create_task(mcp.run_http_async(port=PORT, show_banner=False, log_level="critical"))
        await asyncio.sleep(1.0)
        async with http_client as client:
            pr = await client.call_tool("call_parent_retriever", {
                "query": "in what year this book was written?",
                "corpus": "B"
            })
            print(f""">>> Parent_retriever: {pr.data[0][:200]}""")

            pr = await client.call_tool("call_search_self_query", {
                "query": "in what year this book was written?",
                "corpus": "B",
                "description": "A chunk of text from the book Confessions writen by Saint Augustine"
            })
            print(f""">>> Search_self: {pr.data[0][:200]}""")

            bm = await client.call_tool("call_bm_25_retriever", {
                "query": "in what year this book was written?",
                "corpus": "B"
            })
            print(f""">>> BM_25: {bm.data[0][:200]}""")

            en = await client.call_tool("call_ensemble_retriever", {
                "query": "in what year this book was written?",
                "corpus": "B"
            })
            print(f""">>> Ensemble_retriever: {en.data[0][:200]}""")

    # asyncio.run(test_retriever())
