import asyncio
import warnings
from typing import TypedDict, Literal

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, ChatMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
import json

from ParallelProse.catalog import CATALOG
from ParallelProse.mcp_tools import PORT, http_client, mcp, mcp_tools_as_langchain_tools

warnings.filterwarnings("ignore")
load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.5)

MAX_ITERATIONS = 5
MAX_TOOL_CALLS = 4
FALLBACK_TOOL = "call_parent_retriever"
CORPUS_ID = "A"

system_prompt = " You must call at least one retrieval tool before finishing. You must not answer from your own knowledge, passages from the corpus are the only source. If the query looks impossible or wrong, you must still do the search. Use the query as given, only allow minor changes in the wording if it is to make it clearer. If a retrieval tool returns no results or an error, try a different retrieval tool."

bridged_tools_by_corpus = {}
retrieval_agents_by_corpus = {}


class CorpusState(TypedDict):
    chunks: list[str]
    lineage: list[dict]
    label: Literal["ok", "miss", "silent"] | None
    reason: str | None
    narrowed_query: str | None


class ReflectionState(TypedDict):
    query: str
    answer: str
    needs_revision: bool
    feedback: str
    iteration: int
    corpora: dict[str, CorpusState]  # {"A": {...}} for now


class CorpusCritique(BaseModel):
    """One book's verdict: is the evidence there, and if not, why."""
    corpus_id: Literal["A", "B"] = Field(
        description="the id of the book this verdict is about, exactly as given in the context")
    label: Literal["ok", "miss", "silent"] = Field(
        description="'ok' is when chunks support a real answer for this book. 'miss' is when the book probably addresses it, but retrieval didn't surface it (wrong words count as a miss). 'silent' is when the chunks show the book doesn't address it. Related material in other words points to a miss. Unrelated material points to silence. A narrowed retry that still comes back empty is the best evidence of silence. So, on the first look the default leans toward miss, and silent needs the evidence to stack up.")
    reason: str = Field(
        description="This points the fact(s) that backs-up the choosing of a label. This is the factual proof of what triggers, justifies one label or another. It points that a chunk fully covers a query, or not , if not, that a narrowed_query has or hasn't already been tried, successfully or not.")
    narrowed_query: str | None = Field(
        default=None,
        description="Only used when label is 'miss'. It is a narrowed query that would resolve a specific factual doubt, if any. Leave null otherwise.",
    )


class Critique(BaseModel):
    """The whole verdict: one entry per book, plus the draft-level signal."""
    needs_revision: bool = Field(
        description="True if the answer has a real gap or error worth fixing"
    )
    feedback: str = Field(description="What's wrong and what to fix, or why it's fine")
    corpora_critique: list[CorpusCritique] = Field(
        description="Is exactly one entry for each book in the context, none skipped")


class CorpusFinding(BaseModel):
    corpus_id: Literal["A", "B"] = Field(
        description="the id of the book this finding is about, exactly as given in the context")
    finding: str = Field(
        description="What this one book alone asserts about the query, restricted to whatever wasn't already pulled into the top-level agreement/disagreement. Or, if this book's label is 'silent', a direct statement that it doesn't address the query")


class ComposerAnswer(BaseModel):
    """Agreement Disagreement"""
    agreement: str = Field(
        description="Agreement means what both books actually claim in common about the query. A substantive point they both assert — not just a subject both happen to touch on. ")
    disagreement: str = Field(
        description="It's a point where the books' claims conflict, both books make a claim about the same specific point, and the claims contradict. It`s not just a point where their subjects diverge, both books touch the same broad subject but make claims about different facets of it — nothing actually contradicts, because there's no shared point to compare.")
    unique_findings: list[CorpusFinding] = Field(description="one entry per book, none skipped")


# MARK: RETRIEVER
async def retriever(state: ReflectionState):
    """This function retrieves chunks over a query, once per book in state["corpora"]."""

    # 1 - This section gets server tools and agent creation, per-book.
    global bridged_tools_by_corpus, retrieval_agents_by_corpus  # caches mcp and create_agent calls.
    corpora_updates = {}

    for corpus_id in state["corpora"]:
        if corpus_id not in bridged_tools_by_corpus:  # have I already built the tools for this book ?
            bridged_tools_by_corpus[corpus_id] = await mcp_tools_as_langchain_tools(http_client,
                                                                                    corpus_id)  # if no, create it.
        bridged_tools = bridged_tools_by_corpus[corpus_id]  # if yes, use the cached one.
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

        # 2 - This section decides whether to Retrieve w/ what query.
        if state["corpora"][corpus_id]["label"] is None:  # first-run, label not yet set.
            argument = state["query"]
        elif state["corpora"][corpus_id]["label"] == "miss":
            argument = state["corpora"][corpus_id]["narrowed_query"]
        else:
            corpora_updates[corpus_id] = {
                "chunks": state["corpora"][corpus_id]["chunks"],
                "lineage": state["corpora"][corpus_id]["lineage"],
                "label": state["corpora"][corpus_id]["label"],
                "reason": state["corpora"][corpus_id]["reason"],
                "narrowed_query": None,
            }
            continue
        result = await retrieval_agent.ainvoke(
            {"messages": [HumanMessage(content=argument)]}
        )
        # 3 - setting the accumulators
        chunks_list = []
        tool_call_ids = set([])
        lineage_dict = []

        # 4 - filtering succeeded messages before chunks and tool calls append.
        for msg in result["messages"]:
            if isinstance(msg, ToolMessage) and msg.status == "success":
                chunks_list.extend(json.loads(msg.content))
                tool_call_ids.add(msg.tool_call_id)
        # 5 - getting lineage from succeeded tool calls.
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
            "label": state["corpora"][corpus_id]["label"],
            "reason": state["corpora"][corpus_id]["reason"]
        }
    return {"corpora": corpora_updates}


def format_context(corpora: dict[str, CorpusState]) -> str:
    """One labeled block per book: a header naming the book, then that book's chunks.
    Returns a single string for the composer prompt."""
    blocks = []
    for corpus_id, slot in corpora.items():
        header = f"corpus_id: {corpus_id} = Book_title: {CATALOG[corpus_id].book_title} - Author: {CATALOG[corpus_id].author}\n"
        if not slot["chunks"]:
            chunks_to_str = "no passages retrieved"
        else:
            chunks_to_str = "\n\n".join(slot["chunks"])
        blocks.append(header + chunks_to_str)
    divider = "\n\n\n====================================================\n\n\n"
    result = divider.join(blocks)
    return result


# MARK: COMPOSER
def composer(state: ReflectionState):
    """
    This function composes an answer on how chunks answers the query.
    """
    book_map = "\n".join(
        f"""{corpus_id} = {CATALOG[corpus_id].book_title}, label: {state["corpora"][corpus_id]["label"]}""" for
        corpus_id in state["corpora"])
    context = format_context(state["corpora"])  # organize chunks per-book

    if state["needs_revision"]:
        prompt = f"Given this context {context}, the query {state['query']}, the previous answer{state['answer']}, the book mapping {book_map}, critique to address this feedback {state['feedback']}"
    else:
        prompt = f"Given this context {context}, write a short (3-4 sentence) factual note on: {state['query']}"

    llm_call = llm.with_structured_output(ComposerAnswer)
    structured_answer = llm_call.invoke(prompt)
    for corpus_id in state["corpora"]:
        if state["corpora"][corpus_id]["label"] == "silent":
            for slot in structured_answer.unique_findings:
                if slot.corpus_id == corpus_id:
                    slot.finding = "query content is absent"

    return {"answer": structured_answer, "iteration": state["iteration"] + 1}


def format_attempts(corpora: dict[str, CorpusState]) -> str:
    """Returns a string for reflect's prompt formatted as one block per book: the queries already tried, one line per attempt.
    """
    blocks = []
    for corpus_id, slot in corpora.items():
        header = f"corpus_id: {corpus_id} = Book_title: {CATALOG[corpus_id].book_title} - Author: {CATALOG[corpus_id].author}\n"
        if not slot["lineage"]:
            body = "no attempts so far"
        else:
            body = "\n".join(
                f"Iteration: {a['iteration']}, Tool: {a['tool']}, "
                f"Query: {a['args']['query']}, Forced: {a['forced_retriever']}"
                for a in slot["lineage"]
            )
        blocks.append(header + body)
    return "\n\n".join(blocks)


# MARK: REFLECT
def reflect(state: ReflectionState):
    """This is an "optimizer" function that returns an evaluation to ground upstream refinement, if needed. It works by applying a Critique judgment over composer's answer."""

    # 1 - This section sets the structural information to feed the llm.
    book_map = "\n".join(
        f"{corpus_id} = {CATALOG[corpus_id].book_title}" for corpus_id in state["corpora"])
    attempts = format_attempts(state["corpora"])
    chunks = format_context(state["corpora"])

    # 2 - This section gets a Critique by calling the llm.
    structured_llm = llm.with_structured_output(Critique)
    critique = structured_llm.invoke(
        f"Books:\n{book_map}\n\n"
        f"Query: {state['query']}\n\n"
        f"Answer:\n{state['answer']}\n\n"
        f"Retrieved passages per book:\n{chunks}\n\n"
        f"Queries already tried per book:\n{attempts}\n\n"
        "Critique the answer for factual accuracy and completeness against the retrieved passages.\n"
        "Return needs_revision and feedback for the answer as a whole.\n"
        "Then, for each book listed above, add one entry to corpora_critique: corpus_id must be "
        "exactly A or B as given above, plus label, reason, and narrowed_query."
    )
    # 3 - This section saves the Critique in a per-book structure.
    verdicts = {}
    for slot in critique.corpora_critique:
        if slot.corpus_id == "A":
            if slot.label != "miss":
                slot.narrowed_query = None
            verdicts["A"] = {"corpus_id": slot.corpus_id,
                             "label": slot.label,
                             "reason": slot.reason,
                             "narrowed_query": slot.narrowed_query
                             }
        else:
            if slot.label != "miss":
                slot.narrowed_query = None
            verdicts["B"] = {"corpus_id": slot.corpus_id,
                             "label": slot.label,
                             "reason": slot.reason,
                             "narrowed_query": slot.narrowed_query
                             }

    return {
        "feedback": critique.feedback,
        "needs_revision": critique.needs_revision,
        "corpora":
            {"A": {
                "chunks": state["corpora"]["A"]["chunks"],
                "lineage": state["corpora"]["A"]["lineage"],
                "label": verdicts["A"]["label"],
                "reason": verdicts["A"]["reason"],
                "narrowed_query": verdicts["A"]["narrowed_query"]
            },
                "B": {
                    "chunks": state["corpora"]["B"]["chunks"],
                    "lineage": state["corpora"]["B"]["lineage"],
                    "label": verdicts["B"]["label"],
                    "reason": verdicts["B"]["reason"],
                    "narrowed_query": verdicts["B"]["narrowed_query"]
                }
            }
    }


def route_after_reflection(state: ReflectionState):
    """This function routes the flow"""
    has_miss = False
    for corpus_id in state["corpora"]:
        if state["corpora"][corpus_id]["label"] == "miss":
            has_miss = True

    if state["iteration"] >= MAX_ITERATIONS:
        print("END - MAX_ITERATIONS reached")
        return END
    elif has_miss:
        return "retriever"
    elif state["needs_revision"]:
        return "composer"
    else:
        return END


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
                for corpus_id in update["corpora"]:
                    print(f"""_Chunks: {corpus_id} -  {len(update["corpora"][corpus_id]["chunks"])} items""")
            if node == "composer":
                print(f"""_Agreement: {update["answer"].agreement[:width]}""")
                print(f"""_Disagreement: {update["answer"].disagreement[:width]}\n""")
                for slot in update["answer"].unique_findings:
                    print(f"""_Findings: {slot.corpus_id} - {slot.finding[:width]}""")
            if node == "reflect":
                print(f"""_Feedback:  {update["feedback"][:width]}""")
                print(f"""_Needs_revision: {update["needs_revision"]}\n""")
                for corpus_id in update["corpora"]:
                    print(f"""_Chunks: {corpus_id} - {len(update["corpora"][corpus_id]["chunks"])} items""")
                    print(f"""  _Label: {update["corpora"][corpus_id]["label"]} """)
                    print(f"""    _Reason: {update["corpora"][corpus_id]["reason"]} """)
                    print(f"""      _Narrowed_query: {update["corpora"][corpus_id]["narrowed_query"]}\n""")
                    for item in update["corpora"][corpus_id]["lineage"]:
                        print(
                            f"""_It: {item["iteration"]}, Tool: {item["tool"]}, Forced: {item["forced_retriever"]} """)
                print(
                    "\n\n          _____________________________________________________________________________________________\n")


    async def run():
        server_task = asyncio.create_task(
            mcp.run_http_async(port=PORT, show_banner=False, log_level="critical")
        )
        await asyncio.sleep(1.0)

        # astream instead of ainvoke — see each node's output as it happens
        initial_state = {
            "query": "How is time experienced by people, and what shapes that experience?",
            "answer": "",
            "needs_revision": False,
            "feedback": "",
            "iteration": 0,
            "corpora": {
                "A": {"chunks": None, "lineage": [], "narrowed_query": None, "label": None, "reason": None},
                "B": {"chunks": None, "lineage": [], "narrowed_query": None, "label": None, "reason": None},
            }
        }
        print(f"""________Query: {initial_state["query"]} >>>""")
        async for step in reflection_app.astream(initial_state, stream_mode="updates"):
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
                    "A": {"chunks": None, "lineage": [], "narrowed_query": None, "label": None, "reason": None},
                    "B": {"chunks": None, "lineage": [], "narrowed_query": None, "label": None, "reason": None},
                }

            }
            result = await retriever(state)
            # print(result)
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
    asyncio.run(run())
    # asyncio.run(test_retriever())
    # asyncio.run(test_accumulation())
    # asyncio.run(test_retriever_2())
