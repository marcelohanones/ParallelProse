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
import os

from ParallelProse.catalog import CATALOG
from ParallelProse.mcp_tools import PORT, http_client, mcp, mcp_tools_as_langchain_tools

warnings.filterwarnings("ignore")
load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.5)

# The per-book verdict is a factual judgment, not prose, so it gets its own client: its temperature and model can be
# set independently of the composer's. The env overrides exist for item 41's C control (temperature 0 / gpt-4o on
# this call only); the defaults reproduce the behaviour before the control.
CRITIQUE_MODEL = os.getenv("PP_CRITIQUE_MODEL", "gpt-4o-mini")
CRITIQUE_TEMPERATURE = float(os.getenv("PP_CRITIQUE_TEMPERATURE", "0.5"))
critique_llm = ChatOpenAI(model=CRITIQUE_MODEL, temperature=CRITIQUE_TEMPERATURE)

# Item 41's A probe: with PP_CRITIQUE_MODE=evidence the per-book call judges the passages alone — the draft is
# removed from its input and its question is re-pointed at the book. The default ("draft") is the behaviour
# before the probe.
CRITIQUE_MODE = os.getenv("PP_CRITIQUE_MODE", "draft")

MAX_ITERATIONS = 5
MAX_TOOL_CALLS = 4
FALLBACK_TOOL = "call_parent_retriever"

system_prompt = " You must call at least one retrieval tool before finishing. You must not answer from your own knowledge, passages from the corpus are the only source. If the query looks impossible or wrong, you must still do the search. Use the query as given, only allow minor changes in the wording if it is to make it clearer. If a retrieval tool returns no results or an error, try a different retrieval tool."

bridged_tools_by_corpus = {}
retrieval_agents_by_corpus = {}


class CorpusState(TypedDict):
    chunks: list[str]
    lineage: list[dict]
    label: Literal["ok", "miss", "silent"] | None
    reason: str | None
    narrowed_query: str | None
    silence_cause: Literal["adjacent_topic", "absence"] | None
    P: str | None
    retry_used: bool


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
        description="'ok' means a chunk's own sentence already asserts the query's specific claim — not a theme you connect to it by your own reasoning. Before choosing 'ok', test it: does the chunk's own wording state this claim, or did you add a step (e.g. 'this passage is about X, and X could explain the query's Y') to bridge from what the chunk says to what the query asks? Any such added step disqualifies 'ok' — it means you are inferring the answer, not finding it. 'miss' is when the book probably addresses it in different words, worth a narrowed retry. 'silent' is when the chunks, read literally with no bridging inference, don't make this claim — whether unrelated, or merely adjacent (same general topic, different specific point, bridged only by your own inference). A narrowed retry that still comes back empty is the best evidence of silence. So, on the first look the default leans toward miss, and silent needs the evidence to stack up.")
    reason: str = Field(
        description="First state plainly whether the chunk's own words already assert the claim, or whether you had to add a connecting inference the chunk doesn't itself state — naming that inference if so (this signals the label should not be 'ok'). Then point to the fact(s) that back up the label: a chunk fully covers the query, or not; if not, whether a narrowed_query has already been tried, successfully or not.")
    narrowed_query: str | None = Field(
        default=None,
        description="Only used when label is 'miss'. It is a narrowed query that would resolve a specific factual doubt, if any. Leave null otherwise.",
    )
    silence_cause: Literal["adjacent_topic", "absence"] | None = Field(
        default=None,
        description="Only used when label is 'silent'. 'adjacent_topic' when the chunks show related material that doesn't make this specific claim (a near miss). 'absence' when nothing related was found at all. Leave null otherwise.",
    )


class ComparisonCritique(BaseModel):
    """The cross-book comparison verdict only — no per-book entries, no passages: judges the agreement/disagreement as a whole."""
    needs_revision: bool = Field(
        description="True if the answer has a real gap or error worth fixing"
    )
    feedback: str = Field(
        description="Judge from the query and from answer's 'agreement' and 'disagreement' text alone. Make no mention of passages, quotes, or per-book findings.")


class PerBookCritique(BaseModel):
    """Holds one verdict per book — label, reason, narrowed_query — none skipped. No draft-level signal here."""
    corpora_critique: list[CorpusCritique] = Field(
        description="Is exactly one entry for each book in the context, none skipped")


# MARK: E (item 44) — the evidence-only per-book verdict
# E judges the retrieved passages alone: the composer's draft is never in its input, and its prompt never says
# "support". The field order below is part of the spec — p_adjacent is judged before p_answers so the theme
# question cannot be shaded by the answer question (the bias control).
class EVerdictBase(BaseModel):
    """One book's evidence-only verdict, shared by both looks. EFirst adds the two retry fields; ESecond is
    exactly this minus them, so the retry look cannot re-propose a retry."""
    corpus_id: Literal["A", "B"] = Field(
        description="the id of the book this verdict is about, exactly as given in the context")
    p_adjacent: Literal["yes", "no"] = Field(
        description="some returned chunk treats the query's theme under some proposition, whether or not it "
                    "answers the query. Judge this on its own terms — never as 'adjacent to what I did not find'.")
    p_answers: Literal["yes", "no"] = Field(
        description="some returned chunk's own wording answers the query. The passage alone must state it; do not "
                    "add a connecting step the passage does not itself state.")
    P: str | None = Field(
        default=None,
        description="the proposition: the answering passage's proposition when p_answers is yes; the adjacent "
                    "passage's proposition when p_answers is no and p_adjacent is yes; null when both are no.")


class EFirst(EVerdictBase):
    """E's first look: one book's evidence-only verdict plus its retry proposal. The proposal is normalized afterward (postprocess_e); it never decides anything by itself."""
    retry: Literal["yes", "no"] = Field(
        description="your proposal for whether a narrowed retry is worth one attempt. It is normalized outside "
                    "this call; it never decides anything by itself.")
    narrowed_query: str | None = Field(
        default=None,
        description="only when retry is yes: the narrowed query to try. Leave null otherwise — never an empty "
                    "string or placeholder.")


class ESecond(EVerdictBase):
    """EFirst's schema minus retry and narrowed_query — a schema restriction, not a prompt instruction."""


class EFirstBatch(BaseModel):
    """One call covers both books: E's first look over the whole context, one verdict per book, none skipped."""
    verdicts: list[EFirst] = Field(
        description="Is exactly one entry for each book in the context, none skipped")


class ESecondBatch(BaseModel):
    """One call covers both books: E's retry look, one verdict per book, none skipped."""
    verdicts: list[ESecond] = Field(
        description="Is exactly one entry for each book in the context, none skipped")


class EPostVerdict(BaseModel):
    """A raw E verdict after postprocess_e: retry and narrowed_query are normalized and ok is derived.
    ok is None only on a first look that asked for a retry — E_second then decides."""
    corpus_id: Literal["A", "B"]
    p_adjacent: Literal["yes", "no"]
    p_answers: Literal["yes", "no"]
    P: str | None
    retry: Literal["yes", "no"]
    narrowed_query: str | None
    ok: Literal["yes", "no"] | None


class CorpusFinding(BaseModel):
    corpus_id: Literal["A", "B"] = Field(
        description="the id of the book this finding is about, exactly as given in the context")
    claim_in_passage: str = Field(
        description="What this passage asserts, restricted to the form: when X, Y happens, because Z. If the passage states no cause, write that the cause is unstated — never supply one. Or, if this book's label is 'silent', a direct statement that it doesn't address the query.")
    form: Literal["scene", "thesis", "confession", "diagnosis"] | None = Field(
        default=None,
        description="What kind of passage this is — null when label is 'silent' (no passage to classify).")
    quote: str | None = Field(default=None,
                              description="An exact, verbatim excerpt that backs claim_in_passage. Used only when label is 'miss' or 'ok', leave null if label is 'silent'.")


class ComposerAnswer(BaseModel):
    """Agreement Disagreement"""
    agreement: str = Field(
        description="Agreement means what both books actually claim in common about the query. A substantive point they both assert — not just a subject both happen to touch on. ")
    disagreement: str = Field(
        description="It's a point where the books' claims conflict, both books make a claim about the same specific point, and the claims contradict. It`s not just a point where their subjects diverge, both books touch the same broad subject but make claims about different facets of it — nothing actually contradicts, because there's no shared point to compare.")
    unique_findings: list[CorpusFinding] = Field(description="one entry per book, none skipped")


_server_task: asyncio.Task | None = None  # guard to void re-calling


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
                "silence_cause": state["corpora"][corpus_id]["silence_cause"],
                "P": state["corpora"][corpus_id]["P"],
                "retry_used": state["corpora"][corpus_id]["retry_used"],
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
            "reason": state["corpora"][corpus_id]["reason"],
            "silence_cause": state["corpora"][corpus_id]["silence_cause"],
            "P": state["corpora"][corpus_id]["P"],
            "retry_used": state["corpora"][corpus_id]["retry_used"],
        }
    return {"corpora": corpora_updates}


def format_context(corpora: dict[str, CorpusState]) -> str:
    """This function returns the retrieved chunks as a string, to feed composer prompt. The formatting is: one labeled block per book: a header naming the book, then that book's chunks."""
    blocks = []
    for corpus_id, slot in corpora.items():
        header = f"Corpus_id: {corpus_id} = Book_title: {CATALOG[corpus_id].book_title} - Author: {CATALOG[corpus_id].author} - Era: {CATALOG[corpus_id].era}\n"
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
        f"""Corpus_id: {corpus_id} = {CATALOG[corpus_id].book_title}, Label: {state["corpora"][corpus_id]["label"]}, Era: {CATALOG[corpus_id].era}"""
        for
        corpus_id in state["corpora"])
    context = format_context(state["corpora"])  # organize chunks per-book

    # an "ok" book was skipped by retriever this round: same chunks, so its finding is settled.
    kept = {}
    if state["answer"]:
        for slot in state["answer"].unique_findings:
            if state["corpora"][slot.corpus_id]["label"] == "ok":
                kept[slot.corpus_id] = slot

    if state["needs_revision"]:
        prompt = f"Given this context {context}, the query {state['query']}, the previous answer{state['answer']}, the book mapping {book_map}, critique to address this feedback {state['feedback']}"
    else:
        prompt = f"Given this context {context}, write a short (3-4 sentence) factual note on: {state['query']}"
    if kept:
        kept_text = "\n".join(
            f'Corpus_id: {corpus_id} = Finding: {slot.claim_in_passage} (quote: "{slot.quote}")'
            for corpus_id, slot in kept.items())
        fresh = [corpus_id for corpus_id in state["corpora"] if corpus_id not in kept]
        prompt += (f"\n\nunique_findings must still hold exactly one entry per book: {', '.join(state['corpora'])}. "
                   f"Write a fresh finding for: {', '.join(fresh)}. "
                   f"These books' findings are already settled — reuse them verbatim, and write "
                   f"agreement/disagreement consistent with them:\n{kept_text}")
    silent = [corpus_id for corpus_id in state["corpora"] if state["corpora"][corpus_id]["label"] == "silent"]

    llm_call = llm.with_structured_output(ComposerAnswer)
    structured_answer = llm_call.invoke(prompt)
    for slot in structured_answer.unique_findings:
        if slot.corpus_id in kept:
            slot.claim_in_passage = kept[slot.corpus_id].claim_in_passage
            slot.quote = kept[slot.corpus_id].quote
            slot.form = kept[slot.corpus_id].form
    for corpus_id in state["corpora"]:
        if state["corpora"][corpus_id]["label"] == "silent":
            for slot in structured_answer.unique_findings:
                if slot.corpus_id == corpus_id:
                    slot.claim_in_passage = "query content is absent"
                    slot.quote = None
                    slot.form = None
    if len(silent) == len(state["corpora"]):
        structured_answer.agreement = "Neither book addresses the query."
        structured_answer.disagreement = "None."
    elif silent:
        names = ", ".join(CATALOG[c].book_title for c in silent)
        structured_answer.agreement = f"{names} does not address the query, so there is no cross-book agreement."
        structured_answer.disagreement = "None: only one book addresses the query."

    return {"answer": structured_answer, "iteration": state["iteration"] + 1}


def format_attempts(corpora: dict[str, CorpusState]) -> str:
    """Returns lineage as a string for reflect's prompt formatted as one block per book: the queries already tried, one line per attempt.
    """
    blocks = []
    for corpus_id, slot in corpora.items():
        header = f"Corpus_id: {corpus_id} = Book_title: {CATALOG[corpus_id].book_title} - Author: {CATALOG[corpus_id].author}\n"
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


def format_answer(answer: ComposerAnswer) -> str:
    """This function formats ComposerAnswer as a string to feed reflect's prompt."""
    header = f"""Agreement: {answer.agreement}\nDisagreement: {answer.disagreement} """
    body = "\n".join(
        f"""Corpus_id: {slot.corpus_id} = Finding: {slot.claim_in_passage} (already backed by this verbatim quote: "{slot.quote}")"""
        for slot in answer.unique_findings)
    return "\n\n".join([header, body])


# MARK: E JUDGE
def e_judge_first(query: str, corpora: dict[str, CorpusState]) -> EFirstBatch:
    """E's first look: one evidence-only call covering both books. It sees the query, each book's retrieved
    chunks and its lineage — never the composer's draft — and returns the model's raw verdicts. Normalizing
    retry/ok/narrowed_query is postprocess_e's job (44.1.2), not this one's."""
    book_map = "\n".join(
        f"Corpus_id: {corpus_id} = {CATALOG[corpus_id].book_title} - Era: {CATALOG[corpus_id].era}"
        for corpus_id in corpora)
    evidence = format_context(corpora)
    lineage = format_attempts(corpora)
    prompt = (
        f"Books:\n{book_map}\n\n"
        f"Query: {query}\n\n"
        f"Retrieved passages per book:\n{evidence}\n\n"
        f"Queries already tried per book:\n{lineage}\n\n"
        "For each book listed above, judge that book's own retrieved passages alone. Work only from the "
        "passages, and write no draft answer. First decide p_adjacent on its own terms: does some returned "
        "chunk treat the query's theme under some proposition, whether or not it answers the query? Then decide "
        "p_answers: does some chunk's own wording answer the query? Do not add a step the passage does not "
        "itself state. Then give the proposition P, and, if the passages do not answer, propose retry and the "
        "narrowed_query to try. "
        "Add exactly one entry per book, corpus_id exactly A or B as given above."
    )
    judge = critique_llm.with_structured_output(EFirstBatch)
    return judge.invoke(prompt)


def postprocess_e(verdict: EVerdictBase) -> EPostVerdict:
    """Deterministic, outside the LLM, applied to both looks. It rewrites — never rejects — the model's
    proposal so the derivation table holds: retry is forced no when p_answers is yes; narrowed_query is null
    whenever retry is no; ok is yes when p_answers is yes, no when the book does not answer and no retry fired,
    and None when a retry must decide. E_second has no retry/narrowed_query fields, so it reads as 'no'/None."""
    raw_retry = getattr(verdict, "retry", "no")
    raw_narrowed = getattr(verdict, "narrowed_query", None)
    retry = "no" if verdict.p_answers == "yes" else ("yes" if raw_retry == "yes" else "no")
    narrowed_query = raw_narrowed if retry == "yes" else None
    if verdict.p_answers == "yes":
        ok = "yes"
    elif retry == "yes":
        ok = None
    else:
        ok = "no"
    if (raw_retry, raw_narrowed) != (retry, narrowed_query):
        print(f"E post-process (book {verdict.corpus_id}): rewrote retry={raw_retry!r} "
              f"narrowed_query={raw_narrowed!r} -> retry={retry!r} narrowed_query={narrowed_query!r}")
    return EPostVerdict(corpus_id=verdict.corpus_id, p_adjacent=verdict.p_adjacent,
                        p_answers=verdict.p_answers, P=verdict.P, retry=retry,
                        narrowed_query=narrowed_query, ok=ok)


def e_record(verdict: EPostVerdict, retry_used: bool) -> dict:
    """The canonical per-book record E owns: label plus P, and — for a silent book — silence_cause (derived
    from p_adjacent) and retry_used. A first look that asked for a retry maps to 'miss' so the existing router
    runs it; 44.3 replaces that with the E_second look, after which every record ends ok or silent."""
    if verdict.ok == "yes":
        label = "ok"
    elif verdict.ok is None:
        label = "miss"
    else:
        label = "silent"
    silence_cause = None
    if label == "silent":
        silence_cause = "adjacent_topic" if verdict.p_adjacent == "yes" else "absence"
    return {"label": label, "silence_cause": silence_cause, "P": verdict.P, "retry_used": retry_used}


# MARK: E FIRST (item 44.3)
def e_first(state: ReflectionState) -> dict:
    """E's first look as its own graph node: one evidence-only call over both books — query, chunks
    and lineage, never the composer's draft — then postprocess_e and e_record turn each raw verdict
    into the canonical per-book record. The comparison critique stays out of this node."""
    first = e_judge_first(state["query"], state["corpora"])
    verdicts = {verdict.corpus_id: postprocess_e(verdict) for verdict in first.verdicts}
    corpora = {}
    for corpus_id in state["corpora"]:
        verdict = verdicts[corpus_id]
        retry_used = state["corpora"][corpus_id]["label"] == "miss"
        record = e_record(verdict, retry_used)
        corpora[corpus_id] = {
            "chunks": state["corpora"][corpus_id]["chunks"],
            "lineage": state["corpora"][corpus_id]["lineage"],
            "label": record["label"],
            "reason": f"p_answers={verdict.p_answers}, p_adjacent={verdict.p_adjacent}",
            "narrowed_query": verdict.narrowed_query,
            "silence_cause": record["silence_cause"],
            "P": record["P"],
            "retry_used": record["retry_used"],
        }
    return {"corpora": corpora}


# MARK: REFLECT
def reflect(state: ReflectionState):
    """The graph's per-book judge and cross-book critic. The per-book half is now E's evidence-only look
    (item 44.1.3): e_judge_first sees the query, each book's chunks and its lineage — never the composer's
    draft — and postprocess_e + e_record turn that verdict into the canonical record. The comparison half
    still critiques agreement/disagreement as a whole."""

    # 1 - E's evidence-only look (item 44.1.3) replaces the draft-support per-book critique. One call
    # covers both books; the post-process below makes its verdicts deterministic before they become the record.
    first = e_judge_first(state["query"], state["corpora"])
    # 2 - comparison call: restricted inputs, new schema
    comparison_prompt = f"Query: {state['query']}\n" \
                        f"Agreement: {state['answer'].agreement}\n" \
                        f"Disagreement: {state['answer'].disagreement}\n" \
                        "<instruction: judge the comparison as a whole; you have no access to per-book chunks or findings, so you cannot and must not reference one book's depth specifically>"
    comparison_llm = llm.with_structured_output(ComparisonCritique)
    comparison = comparison_llm.invoke(comparison_prompt)

    # 3 - Deterministic post-process + the canonical per-book record. Dual format: the composer-derived
    # fields the existing consumers read stay alongside E's, until 44.2 switches the read sites.
    verdicts = {verdict.corpus_id: postprocess_e(verdict) for verdict in first.verdicts}
    corpora = {}
    for corpus_id in state["corpora"]:
        verdict = verdicts[corpus_id]
        retry_used = state["corpora"][corpus_id]["label"] == "miss"
        record = e_record(verdict, retry_used)
        corpora[corpus_id] = {
            "chunks": state["corpora"][corpus_id]["chunks"],
            "lineage": state["corpora"][corpus_id]["lineage"],
            "label": record["label"],
            "reason": f"p_answers={verdict.p_answers}, p_adjacent={verdict.p_adjacent}",
            "narrowed_query": verdict.narrowed_query,
            "silence_cause": record["silence_cause"],
            "P": record["P"],
            "retry_used": record["retry_used"],
        }

    return {
        "feedback": comparison.feedback,
        "needs_revision": comparison.needs_revision,
        "corpora": corpora,
    }


def route_after_reflection(state: ReflectionState):
    """This function routes the flow"""
    has_miss = False
    has_silent = False
    for corpus_id in state["corpora"]:
        if state["corpora"][corpus_id]["label"] == "miss":
            has_miss = True
        if state["corpora"][corpus_id]["label"] == "silent":
            has_silent = True

    if has_miss and state["iteration"] < MAX_ITERATIONS:
        return "retriever"
    elif has_silent:
        return "finalize"
    elif has_miss:
        print("END - MAX_ITERATIONS reached")
    return END


reflection_graph = StateGraph(ReflectionState)
reflection_graph.add_node("retriever", retriever)
reflection_graph.add_node("composer", composer)
reflection_graph.add_node("reflect", reflect)
reflection_graph.add_node("finalize", composer)
reflection_graph.add_conditional_edges("reflect", route_after_reflection)
reflection_graph.add_edge(START, "retriever")
reflection_graph.add_edge("retriever", "composer")
reflection_graph.add_edge("composer", "reflect")
reflection_graph.add_edge("finalize", END)

reflection_app = reflection_graph.compile()


async def run_query(query: str) -> ReflectionState:
    global _server_task
    if _server_task is None:
        _server_task = asyncio.create_task(
            mcp.run_http_async(port=PORT, show_banner=False, log_level="critical")
        )
        await asyncio.sleep(1.0)

    initial_state = {
        "query": query,
        "answer": "",
        "needs_revision": False,
        "feedback": "",
        "iteration": 0,
        "corpora": {
            "A": {"chunks": None, "lineage": [], "narrowed_query": None, "label": None, "reason": None,
                  "silence_cause": None, "P": None, "retry_used": False},
            "B": {"chunks": None, "lineage": [], "narrowed_query": None, "label": None, "reason": None,
                  "silence_cause": None, "P": None, "retry_used": False},
        }
    }
    return await reflection_app.ainvoke(initial_state)


if __name__ == "__main__":
    # print(reflection_app.get_graph().draw_mermaid())

    def show(step: dict, width: int = 100):
        for node, update in step.items():
            print(f"\n________{node.upper()} >>>")
            if node == "retriever":
                for corpus_id in update["corpora"]:
                    print(f"""_Chunks: {corpus_id} -  {len(update["corpora"][corpus_id]["chunks"])} items""")
            if node in ("composer", "finalize"):
                print(f"""_Agreement: {update["answer"].agreement[:width]}""")
                print(f"""_Disagreement: {update["answer"].disagreement[:width]}\n""")
                for slot in update["answer"].unique_findings:
                    print(f"""_Findings: {slot.corpus_id} - {slot.claim_in_passage[:width]}""")
            if node == "reflect":
                print(f"""_Feedback:  {update["feedback"][:width]}""")
                print(f"""_Needs_revision: {update["needs_revision"]}\n""")
                for corpus_id in update["corpora"]:
                    print(f"""_Chunks: {corpus_id} - {len(update["corpora"][corpus_id]["chunks"])} items""")
                    print(f"""  _Label: {update["corpora"][corpus_id]["label"]} """)
                    print(f"""    _Reason: {update["corpora"][corpus_id]["reason"]} """)
                    print(f"""      _Narrowed_query: {update["corpora"][corpus_id]["narrowed_query"]}""")
                    print(f"""      _Silence_cause: {update["corpora"][corpus_id]["silence_cause"]}""")
                    for item in update["corpora"][corpus_id]["lineage"]:
                        print(
                            f"""       _It: {item["iteration"]}, Tool: {item["tool"]}, Forced: {item["forced_retriever"]}""")
                    print("\n")
                print(
                    "\n          _____________________________________________________________________________________________\n")


    async def demo():
        result = await run_query(query="How is time experienced by people, and what shapes that experience?")
        print(f"""________Query: {result["query"]} >>>""")
        print(f"""_Answer: {result["answer"]}""")
        print(f"""_Feedback: {result["feedback"]}""")


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
                "A": {"chunks": None, "lineage": [], "narrowed_query": None, "label": None, "reason": None,
                      "silence_cause": None, "P": None, "retry_used": False},
                "B": {"chunks": None, "lineage": [], "narrowed_query": None, "label": None, "reason": None,
                      "silence_cause": None, "P": None, "retry_used": False},
            }
        }
        print(f"""________Query: {initial_state["query"]} >>>""")
        async for step in reflection_app.astream(initial_state, stream_mode="updates"):
            show(step)

        server_task.cancel()


    # MARK: CALLERS
    # asyncio.run(run())
    asyncio.run(demo())
