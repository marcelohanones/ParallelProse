import asyncio
import warnings
from typing import TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from ParallelProse.mcp_tools import PORT, http_client, mcp

warnings.filterwarnings("ignore")
load_dotenv()

llm=ChatOpenAI(model="gpt-4o-mini", temperature=0.5)

MAX_ITERATIONS = 5

class ReflectionState(TypedDict):
    query: str
    narrowed_query: str | None
    answer: str
    needs_revision: bool
    feedback: str
    chunks: list[str]
    chunks_id: int
    iteration: int


class Critique(BaseModel):
    needs_revision: bool = Field(
        description="True if the answer has a real gap or error worth fixing"
    )
    feedback: str = Field(description="What's wrong and what to fix, or why it's fine")
    narrowed_query: str | None = Field(
        default=None,
        description="A narrowed query that would resolve a specific factual doubt, if any. Leave null otherwise.",
    )


async def retriever(state: ReflectionState) -> dict:
    """This function retrieves chunks over a query via the MCP retrieval server."""
    if state.get("narrowed_query"):
        argument = state["narrowed_query"]
    else:
        argument = state["query"]
    async with http_client as client:
        result = await client.call_tool("call_parent_retriever", {"query": argument})
    return {
        "chunks": result.data,
        "chunks_id": state.get("chunks_id", 0) + 1,
    }


def composer(state: ReflectionState):
    """
    This function composes an answer for: retrieved chunks from a query|narrowed_query, a Critique
    """
    # context = ""
    docs = state["chunks"]
    context = docs
    # narrowed_retriever → composer
    # critique narrowed_query + chunks
    if state["narrowed_query"] and state["needs_revision"]:# new chunks
        prompt = f"Given this context {context}, the query {state['narrowed_query']},  and the previous answer{state['answer']} , critique to adress this feedback {state['feedback']}"

        # context , query, feedback , previous answer

    # switch → composer (direct revise branch)
    elif state["needs_revision"]:#  old chunks
        prompt = f"Given this context {context}, the query {state['query']} and the previous answer{state['answer']} critique to adress this feedback {state['feedback']}"
    # retriever → composer
    # no critique, 
    else:
        prompt = f"Given this context {context}, write a short (3-4 sentence) factual note on: {state['query']}"

    answer = llm.invoke(prompt).content
    return {"answer": answer, "iteration": state.get("iteration",0) + 1}


def reflect(state: ReflectionState):
    """This function returns a Critique judment over composer's answer. It works as an optimizer returning feedbacks and narrowed_query for another round of revision."""
    structured_llm = llm.with_structured_output(Critique)
    critique = structured_llm.invoke(
        f"Critique this draft for factual accuracy and completeness.\n\n"
        f"Query: {state['query']}\n\nAnswer:\n{state['answer']}"
    )
    return {
        "feedback": critique.feedback,
        "needs_revision": critique.needs_revision,
        "narrowed_query": critique.narrowed_query,
    }


def route_after_reflection(state: ReflectionState):
    """This function routes the flow"""
    if not state["needs_revision"] or state["iteration"] >= MAX_ITERATIONS:
        return END
    if state["narrowed_query"]:
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
    print(reflection_app.get_graph().draw_mermaid())

    async def run():
        server_task = asyncio.create_task(
            mcp.run_http_async(port=PORT, show_banner=False, log_level="critical")
        )
        await asyncio.sleep(1.0)

        # astream instead of ainvoke — see each node's output as it happens
        async for step in reflection_app.astream(
            {
                "query": "when and why Niccolò Machiavelli wrote The Prince",
                "narrowed_query": None,
                "answer": "",
                "feedback": "",
                "needs_revision": False,
                "chunks": None,
                "chunks_id": 0,
                "iteration": 0,
            },
            stream_mode="updates",
        ):
            print(step)

        server_task.cancel()

    asyncio.run(run())
