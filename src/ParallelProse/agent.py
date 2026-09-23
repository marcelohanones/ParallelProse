import asyncio
import warnings
from operator import contains
from typing import TypedDict

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, ChatMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
import json

from ParallelProse.mcp_tools import PORT, http_client, mcp, mcp_tools_as_langchain_tools

warnings.filterwarnings("ignore")
load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.5)

MAX_ITERATIONS = 5
MAX_TOOL_CALLS = 4
FALLBACK_TOOL = "call_parent_retriever"
CORPUS_ID = "B"

system_prompt = " You must call at least one retrieval tool before finishing. You must not answer from your own knowledge, passages from the corpus are the only source. If the query looks impossible or wrong, you must still do the search. Use the query as given, only allow minor changes in the wording if it is to make it clearer. If a retrieval tool returns no results or an error, try a different retrieval tool."
# bridged_tools = None
# retrieval_agent = None

bridged_tools_by_corpus = {}
retrieval_agents_by_corpus = {}


class CorpusState(TypedDict):
    chunks: list[str]
    lineage: list[dict]
    narrowed_query: str | None


class ReflectionState(TypedDict):
    query: str
    answer: str
    needs_revision: bool
    feedback: str
    iteration: int
    corpora: dict[str, CorpusState]  # {"A": {...}} for now


class Critique(BaseModel):
    needs_revision: bool = Field(
        description="True if the answer has a real gap or error worth fixing"
    )
    feedback: str = Field(description="What's wrong and what to fix, or why it's fine")
    narrowed_query: str | None = Field(
        default=None,
        description="A narrowed query that would resolve a specific factual doubt, if any. Leave null otherwise.",
    )


# MARK: RETRIEVER
async def retriever(state: ReflectionState):
    """This function retrieves chunks over a query, once per book in state["corpora"]."""
    global bridged_tools_by_corpus, retrieval_agents_by_corpus

    corpora_updates = {}
    for corpus_id in state["corpora"]:
        if corpus_id not in bridged_tools_by_corpus:
            bridged_tools_by_corpus[corpus_id] = await mcp_tools_as_langchain_tools(http_client, corpus_id)
        bridged_tools = bridged_tools_by_corpus[corpus_id]
        if corpus_id not in retrieval_agents_by_corpus:
            retrieval_agents_by_corpus[corpus_id] = create_agent(
                model=llm,
                tools=bridged_tools,
                middleware=[
                    ModelCallLimitMiddleware(run_limit=MAX_ITERATIONS),
                    ToolCallLimitMiddleware(run_limit=MAX_TOOL_CALLS, exit_behavior="end"),
                ],
                system_prompt=system_prompt,
            )
        retrieval_agent = retrieval_agents_by_corpus[corpus_id]
        if state["corpora"][corpus_id]["narrowed_query"]:
            argument = state["corpora"][corpus_id]["narrowed_query"]
        else:
            argument = state["query"]
        result = await retrieval_agent.ainvoke(
            {"messages": [HumanMessage(content=argument)]}
        )
        chunks_list = []
        tool_call_ids = set([])
        lineage_dict = []

        for msg in result["messages"]:
            if isinstance(msg, ToolMessage) and msg.status == "success":
                chunks_list.extend(json.loads(msg.content))
                tool_call_ids.add(msg.tool_call_id)
        for msg in result["messages"]:
            if isinstance(msg, AIMessage):
                for tc in msg.tool_calls:
                    if tc["id"] in tool_call_ids:
                        lineage_dict.append({"iteration": state["iteration"],
                                             "tool": tc["name"],
                                             "args": tc["args"],
                                             "forced_retriever": False
                                             })
        # forcing retriever
        if not chunks_list:
            async with http_client as client:
                r = await client.call_tool(FALLBACK_TOOL,
                                           {"query": argument,
                                            "corpus": corpus_id})
                chunks_list.extend(r.data)
                lineage_dict.append(
                    {
                        "iteration": state["iteration"],
                        "tool": "call_parent_retriever",
                        "args": {"query": argument},
                        "forced_retriever": True
                    }
                )
        corpora_updates[corpus_id] = {
            "chunks": chunks_list,
            "lineage": state["corpora"][corpus_id]["lineage"] + lineage_dict,
            "narrowed_query": state["corpora"][corpus_id]["narrowed_query"],

        }
    return {"corpora": corpora_updates}


# MARK: COMPOSER
def composer(state: ReflectionState):
    """
    This function composes an answer for: retrieved chunks from a query|narrowed_query, a Critique
    """
    # context = ""
    docs = state["corpora"][CORPUS_ID]["chunks"]
    context = docs
    # narrowed_retriever → composer
    # critique narrowed_query + chunks
    if state["corpora"][CORPUS_ID]["narrowed_query"] and state["needs_revision"]:  # new chunks
        prompt = f"Given this context {context}, the query {state['corpora'][CORPUS_ID]['narrowed_query']},  and the previous answer{state['answer']} , critique to address this feedback {state['feedback']}"

        # context , query, feedback , previous answer

    # switch → composer (direct revise branch)
    elif state["needs_revision"]:  # old chunks
        prompt = f"Given this context {context}, the query {state['query']} and the previous answer{state['answer']} critique to adress this feedback {state['feedback']}"
    # retriever → composer
    # no critique,
    else:
        prompt = f"Given this context {context}, write a short (3-4 sentence) factual note on: {state['query']}"

    answer = llm.invoke(prompt).content
    return {"answer": answer, "iteration": state["iteration"] + 1}


# MARK: REFLECT
def reflect(state: ReflectionState):
    """This function returns a Critique judgment over composer's answer. It works as an optimizer returning feedbacks and narrowed_query for another round of revision."""
    structured_llm = llm.with_structured_output(Critique)
    critique = structured_llm.invoke(
        f"Critique this draft for factual accuracy and completeness.\n\n"
        f"Query: {state['query']}\n\nAnswer:\n{state['answer']}"
    )
    return {
        "feedback": critique.feedback,
        "needs_revision": critique.needs_revision,
        "corpora": {CORPUS_ID: {
            "chunks": state["corpora"][CORPUS_ID]["chunks"],
            "lineage": state["corpora"][CORPUS_ID]["lineage"],
            "narrowed_query": critique.narrowed_query}}
    }


def route_after_reflection(state: ReflectionState):
    """This function routes the flow"""
    if not state["needs_revision"] or state["iteration"] >= MAX_ITERATIONS:
        return END
    if state["corpora"][CORPUS_ID]["narrowed_query"]:
        return "retriever"
    return "composer"


reflection_graph = StateGraph(ReflectionState)
reflection_graph.add_node("retriever", retriever)
reflection_graph.add_node("composer", composer)
reflection_graph.add_node("reflect", reflect)
reflection_graph.add_conditional_edges("reflect", route_after_reflection)
reflection_graph.add_edge(START, "retriever")
reflection_graph.add_edge("retriever", "composer")
reflection_graph.add_edge("composer", "reflect")

reflection_app = reflection_graph.compile()

if __name__ == "__main__":
    # print(reflection_app.get_graph().draw_mermaid())

    def show(step: dict, width: int = 100):
        for node, update in step.items():
            print(f"\n________{node.upper()} >>>")
            if node == "retriever":
                print(f"""_Chunks: {len(update["corpora"][CORPUS_ID]["chunks"])} items""")
            if node == "composer":
                print(f"""  _Answer: {update["answer"][:width]}""")
            if node == "reflect":
                print(f"""_Chunks: {len(update["corpora"][CORPUS_ID]["chunks"])} items""")
                print(f"""      _Feedback:  {update["feedback"][:width]}""")
                print(f"""\n        _Needs_revision: {update["needs_revision"]}""")
                print(f"""\n            _Narrowed_query: {update["corpora"][CORPUS_ID]["narrowed_query"]}""")
                for item in update["corpora"][CORPUS_ID]["lineage"]:
                    print(
                        f"""\n_It: {item["iteration"]}, Tool: {item["tool"]}, Query: {item["args"]["query"]}, Forced: {item["forced_retriever"]} """)

                print(
                    "\n          _____________________________________________________________________________________________\n")


    async def run():
        server_task = asyncio.create_task(
            mcp.run_http_async(port=PORT, show_banner=False, log_level="critical")
        )
        await asyncio.sleep(1.0)

        # astream instead of ainvoke — see each node's output as it happens
        async for step in reflection_app.astream(
                {
                    "query": "when and why Niccolò Machiavelli wrote The Lion",
                    "answer": "",
                    "needs_revision": False,
                    "feedback": "",
                    "iteration": 0,
                    "corpora": {CORPUS_ID: {
                        "chunks": None,
                        "lineage": [],
                        "narrowed_query": None
                    }}
                },
                stream_mode="updates",
        ):
            show(step)

        server_task.cancel()


    # MARK: TESTS
    async def test_retriever():
        server_task = asyncio.create_task(
            mcp.run_http_async(port=PORT, show_banner=False, log_level="critical")
        )
        await asyncio.sleep(1.0)
        try:
            state = {
                "query": "What the book says about 'life being represented instead of living'?",
                "answer": "",
                "needs_revision": False,
                "feedback": "",
                "iteration": 0,
                "corpora": {
                    "A": {"chunks": None, "lineage": [], "narrowed_query": None},
                    "B": {"chunks": None, "lineage": [], "narrowed_query": None},
                }

            }

            result = await retriever2(state)
            print(result)
            return result
        finally:
            server_task.cancel()


    async def test_accumulation():
        server_task = asyncio.create_task(mcp.run_http_async(port=PORT, show_banner=False, log_level="critical"))
        await asyncio.sleep(1.0)
        try:
            state = {
                "query": "em quais capitulos o autor fala sobre fortuna?",
                "narrowed_query": None,
                "answer": "",
                "feedback": "",
                "needs_revision": False,
                "chunks": None,
                "lineage": [],
                "iteration": 0,
            }

            r1 = await retriever(state)
            state = {**state, **r1}  # what LangGraph does with the node's return
            print("round 1:", state["lineage"])

            state["iteration"] = 1  # composer would have bumped this
            state["narrowed_query"] = "fortuna no capítulo XXV"
            r2 = await retriever(state)
            state = {**state, **r2}
            print("round 2:", state["lineage"])
        finally:
            server_task.cancel()


    async def test_retriever_2():
        server_task = asyncio.create_task(mcp.run_http_async(port=PORT, show_banner=False, log_level="critical"))

        await asyncio.sleep(1.0)

        async with http_client as client:
            r = await client.call_tool("call_parent_retriever",
                                       {"query": "when and why Niccolò Machiavelli wrote The Lion"})
        print(len(r.data));
        print(r.data[0][:200])


    # MARK: CALLERS
    # asyncio.run(run())
    asyncio.run(test_retriever())
    # asyncio.run(test_accumulation())
    # asyncio.run(test_retriever_2())
