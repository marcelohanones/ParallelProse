import asyncio

from dotenv import load_dotenv
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

from ParallelProse.ingest import PDF_PATH
from ParallelProse.retrieve import Retrieval

load_dotenv()

mcp = FastMCP(name="RetrievalServer", instructions="Provide Retrieval Methods")
retrieval_obj = Retrieval(collection_name="demo_C9", pdf_path=PDF_PATH)
retrieval_obj.add_parent_child_docs()


# // TOOLS
@mcp.tool
def call_parent_retriever(query: str) -> list[str]:
    """Semantic search: matches the query against small child chunks by meaning and returns their larger parent chunks, so each result comes with surrounding context.
    Use it by default, for concepts, themes and open questions (e.g. "what does the author say about a subject ?"), where the wording of the query may differ from the wording of the text.
    Avoid it when the query hinges on one exact name or word; use call_bm_25_retriever for that."""
    return [i.page_content for i in retrieval_obj.parent_retriever.invoke(query)]


@mcp.tool
def call_search_self_query(query: str, description: str) -> list[str]:
    """Filtered semantic search: turns the query into a similarity search plus a metadata filter on `chapter`, then returns the parent chunks of the matches.
    Use it only when the query names a specific chapter (e.g. "what does chapter 25 say about fortune?"); otherwise the filter has nothing to filter on.
    `description` is one short sentence saying what the corpus text is (e.g. "A chunk of text from Machiavelli's 'The Prince'"); it is not the query."""
    return [i.page_content for i in retrieval_obj.make_search_self_query(query, description)]


@mcp.tool
def call_bm_25_retriever(query: str) -> list[str]:
    """Exact keyword match (BM25): ranks chunks by how many of the query's words they contain, with no understanding of meaning.
    Use it when the query hinges on a specific name, title, rare word or quoted phrase (e.g. "Cesare Borgia").
    Avoid it for paraphrased or conceptual questions: a synonym or a different wording will not match, and it can return nothing relevant."""
    return [i.page_content for i in retrieval_obj.make_bm_25_retriever().invoke(query)]


@mcp.tool
def call_ensemble_retriever(query: str) -> list[str]:
    """Hybrid search: blends call_bm_25_retriever and call_parent_retriever, weighting each 0.5, so results can match by meaning and by exact words.
    Use it when the query mixes a concept with a specific name or term (e.g. "Borgia's rise and what it teaches about fortune"), or when neither single method fits.
    It is slower than either one alone, so prefer a single retriever when the query clearly fits one."""
    return [i.page_content for i in retrieval_obj.make_ensemble_retriever().invoke(query)]


# //  IN MEMORY
# in_memory_client = Client(mcp)


# async def main_in_memory_client():
#     async with in_memory_client as client:
#         tools = await client.list_tools()
#         print("Available Tools: ", [i.name for i in tools])

#         result_parent = await client.call_tool(
#             "call_parent_retriever",
#             {"query": "em quais capitulos o autor fala sobre fortuna?"},
#         )
#         print(result_parent.data)

#         result_self_query = await client.call_tool(
#             "call_search_self_query",
#             {
#                 "query": "em quais capitulos o autor fala sobre fortuna?",
#                 "description": "A chunk of text from Machiavelli's 'The Prince'",
#             },
#         )
#         print(result_self_query.data)

#         result_bm_25 = await client.call_tool(
#             "call_bm_25_retriever", {"query": "em quais capitulos o autor fala sobre fortuna?"}
#         )
#         print(result_bm_25.data)

#         result_ensemble = await client.call_tool(
#             "call_ensemble_retriever", {"query": "em quais capitulos o autor fala sobre fortuna?"}
#         )
#         print(result_ensemble.data)

# // HTTP
PORT = 8931
http_client = Client(StreamableHttpTransport(url=f"http://127.0.0.1:{PORT}/mcp"))


# // BRIDGE TO LANGCHAIN

async def mcp_tools_as_langchain_tools(client: Client) -> list[StructuredTool]:
    async with client:
        mcp_tools = await client.list_tools()

    def wrap(mcp_tool):
        async def call(**kwargs):
            async with client:
                result = await client.call_tool(mcp_tool.name, kwargs)
            return result.data

        return StructuredTool.from_function(
            coroutine=call,
            name=mcp_tool.name,
            description=mcp_tool.description or "",
            args_schema=mcp_tool.input_schema,
        )

    result = [wrap(i) for i in mcp_tools]
    return result

  

async def main():
    #// HTTP
    server_task = asyncio.create_task(
        mcp.run_http_async(port=PORT, show_banner=False, log_level="critical")
    )
    await asyncio.sleep(1.0)
    print(f"Serving on http://127.0.0.1:{PORT}/mcp")

    async with http_client as client:
        tools = await client.list_tools()
        print("Available Tools over http:", [i.name for i in tools])

        # result_parent = await client.call_tool(
        #     "call_parent_retriever",
        #     {"query": "em quais capitulos o autor fala sobre fortuna?"},
        # )
        # print(result_parent.data)
    #// CALL
    bridged_tools = await mcp_tools_as_langchain_tools(http_client)

    agent = create_agent(model=ChatOpenAI(model="gpt-4o-mini"), tools=bridged_tools)
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="em quais capitulos o autor fala sobre fortuna?")]}
    )
    print(result["messages"][-1].content)

    server_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
