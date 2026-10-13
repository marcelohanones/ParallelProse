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
import re

from ParallelProse.catalog import CATALOG
from ParallelProse.mcp_tools import PORT, http_client, mcp, mcp_tools_as_langchain_tools

warnings.filterwarnings("ignore")
load_dotenv()

# Item 44.4's seed gate: PP_SEED pins the sampling draws on both seeded clients — llm (the retrieval agent, the
# composer and reflect) and critique_llm (E and the sentence picker). It cleans future draws only — chunks
# already retrieved are unaffected.
SEED = os.getenv("PP_SEED")
SEED_KWARGS = {"seed": int(SEED)} if SEED else {}
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.5, **SEED_KWARGS)

# The per-book verdict is a factual judgment, not prose, so it gets its own client: its temperature and model can be
# set independently of the composer's. The env overrides exist for item 41's C control (temperature 0 / gpt-4o on
# this call only); the defaults reproduce the behaviour before the control.
CRITIQUE_MODEL = os.getenv("PP_CRITIQUE_MODEL", "gpt-4o-mini")
CRITIQUE_TEMPERATURE = float(os.getenv("PP_CRITIQUE_TEMPERATURE", "0.5"))
critique_llm = ChatOpenAI(model=CRITIQUE_MODEL, temperature=CRITIQUE_TEMPERATURE, **SEED_KWARGS)

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


class ComparisonCritique(BaseModel):
    """The cross-book comparison verdict only — no per-book entries, no passages: judges the agreement/disagreement as a whole."""
    needs_revision: bool = Field(
        description="True if the answer has a real gap or error worth fixing"
    )
    feedback: str = Field(
        description="Judge from the query and from answer's 'agreement' and 'disagreement' text alone. Make no mention of passages, quotes, or per-book findings.")


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


class SentenceClaim(BaseModel):
    claim: str = Field(
        description="The proposition the sentence states — what this sentence says, in its own terms. Never a generalization from it, never a cause or a consequence the sentence does not state.")
    sentence: str = Field(
        description="An exact, verbatim sentence from the passage that states this claim. The passage is the evidence; this sentence is the step that carries this claim. Never the query itself: when the query's wording comes from the book, quote the sentence around it instead.")


class CorpusFinding(BaseModel):
    corpus_id: Literal["A", "B"] = Field(
        description="the id of the book this finding is about, exactly as given in the context")
    headline: str = Field(
        description="This book's position on the query, in one or two sentences. Our summary of what the passage shows, not a claim any single sentence proves. If this book's label is 'silent', a direct statement that it doesn't address the query.")
    form: Literal["scene", "thesis", "confession", "diagnosis"] | None = Field(
        default=None,
        description="What kind of passage this is — null when label is 'silent' (no passage to classify).")
    pairs: list[SentenceClaim] = Field(
        default_factory=list,
        description="One to five (claim, sentence) pairs: the grounded steps behind the headline. Empty when label is 'silent'. Each claim must be exactly what its own sentence states — if a sentence states no cause, the pair states no cause.")
    unpaired: list[str] = Field(
        default_factory=list,
        description="Claims left without a sentence of their own by select_sentences — no single sentence states it, or the sentence it matched is already carrying another claim. Kept out of the pairs, never presented as evidence, and kept here so the gap stays visible.")


class DraftFinding(BaseModel):
    """The composer's draft for one book: its position and the atomic claims behind it — no sentences yet. The
    sentences are chosen in a second pass (select_sentences): asking one call to invent the claims and attribute
    them at once is what produced claims paired with sentences that state something else."""
    corpus_id: Literal["A", "B"] = Field(
        description="the id of the book this finding is about, exactly as given in the context")
    headline: str = Field(
        description="This book's position on the query, in one or two sentences. Our summary of what the passage shows, not a claim any single sentence proves. If this book's label is silent, a direct statement that it doesn't address the query.")
    form: Literal["scene", "thesis", "confession", "diagnosis"] | None = Field(
        default=None,
        description="What kind of passage this is — null when label is silent (no passage to classify).")
    claims: list[str] = Field(
        default_factory=list,
        description="One to five atomic claims the passage supports — each one a proposition a single sentence of the passage states, never a generalization, a cause or a consequence the passage leaves out. Empty when label is silent.")


class ComposerDraft(BaseModel):
    """Agreement Disagreement, plus each book's headline and its claims — the sentences are still to come."""
    agreement: str = Field(
        description="Agreement means what both books actually claim in common about the query. A substantive point they both assert — not just a subject both happen to touch on. ")
    disagreement: str = Field(
        description="A point where the books' claims conflict: both make a claim about the same specific point, and the claims contradict. Not a point where their subjects merely diverge.")
    unique_findings: list[DraftFinding] = Field(
        description="one entry per book that addresses the query (label ok); a book the graph marked silent gets no finding here.")


class SentenceChoice(BaseModel):
    sentence_index: int | None = Field(
        description="1-based number of the single sentence that states this claim, from the numbered list given, or null when no single sentence states it")


class ComposerAnswer(BaseModel):
    """Agreement Disagreement"""
    agreement: str = Field(
        description="Agreement means what both books actually claim in common about the query. A substantive point they both assert — not just a subject both happen to touch on. ")
    disagreement: str = Field(
        description="It's a point where the books' claims conflict, both books make a claim about the same specific point, and the claims contradict. It`s not just a point where their subjects diverge, both books touch the same broad subject but make claims about different facets of it — nothing actually contradicts, because there's no shared point to compare.")
    unique_findings: list[CorpusFinding] = Field(
        description="one entry per book that addresses the query (label 'ok'); a book the graph marked 'silent' gets no finding here.")


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
            {"messages": [HumanMessage(content=argument)]},
            config={"tags": ["role:retrieval_agent"]},
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
def _sentences(chunks: list[str]) -> list[str]:
    """The book's retrieved sentences, in order — the candidate list the picker chooses from."""
    return [s for chunk in (chunks or [])
            for s in re.split(r"(?<=[.!?;:])\s+", re.sub(r"\s+", " ", chunk).strip()) if s.strip()]


def select_sentences(draft: ComposerDraft, corpora: dict) -> ComposerAnswer:
    """The second pass: for every claim, one call asks which single sentence of that book states it, and the pair
    carries that sentence verbatim. The task is selection, not generation — the shape that pairs 96% of claims
    correctly, against the ~36% a one-shot composer managed. A claim no single sentence states is left out of the
    pairs and kept in the finding's unpaired list."""
    findings = []
    for slot in draft.unique_findings:
        sentences = _sentences(corpora[slot.corpus_id]["chunks"])
        listing = "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences, 1))
        pairs, unpaired, used = [], [], set()
        for claim in slot.claims:
            choice = critique_llm.with_structured_output(SentenceChoice).invoke(
                f"Claim: {claim}\n\nSentences from the book's retrieved passages:\n{listing}\n\n"
                "Which single sentence states this claim? Judge by what the sentence means, not by shared words. "
                "Answer with its number, or null if no single sentence states it.",
                config={"tags": ["role:sentence_picker"]})
            index = choice.sentence_index
            if index is not None and 1 <= index <= len(sentences) and index not in used:
                used.add(index)  # one sentence carries one claim: a reused sentence is not a second grounded step
                pairs.append(SentenceClaim(claim=claim, sentence=sentences[index - 1]))
            else:
                unpaired.append(claim)
        findings.append(CorpusFinding(corpus_id=slot.corpus_id, headline=slot.headline, form=slot.form,
                                      pairs=pairs, unpaired=unpaired))
    return ComposerAnswer(agreement=draft.agreement, disagreement=draft.disagreement, unique_findings=findings)


def composer(state: ReflectionState):
    """Composes the answer from the books E left 'ok'. A silent book contributes no finding — the readers
    take their per-book record from E, not from here — and when fewer than two books answer, the
    agreement/disagreement is written deterministically instead of by the model."""
    ok = [corpus_id for corpus_id in state["corpora"] if state["corpora"][corpus_id]["label"] == "ok"]
    context = format_context(state["corpora"])  # organize chunks per-book

    if not ok:
        answer = ComposerAnswer(agreement="Neither book addresses the query.",
                                disagreement="None.", unique_findings=[])
    else:
        book_map = "\n".join(
            f"""Corpus_id: {corpus_id} = {CATALOG[corpus_id].book_title}, Label: {state["corpora"][corpus_id]["label"]}, Era: {CATALOG[corpus_id].era}"""
            for corpus_id in state["corpora"])
        prompt = (f"Given this context {context}, the query {state['query']} and the book mapping {book_map}, "
                  f"write a short (3-4 sentence) factual note on: {state['query']}. For each book give its own "
                  f"position as a headline and the atomic claims the passage supports; the sentences themselves "
                  f"are chosen afterwards.")
        draft = llm.with_structured_output(ComposerDraft).invoke(prompt, config={"tags": ["role:composer"]})
        # a finding only exists for a book that answers: drop any the model wrote for a silent book
        draft.unique_findings = [slot for slot in draft.unique_findings if slot.corpus_id in ok]
        answer = select_sentences(draft, state["corpora"])
        if len(ok) == 1:
            silent_names = ", ".join(CATALOG[c].book_title for c in state["corpora"] if c not in ok)
            answer.agreement = f"{silent_names} does not address the query, so there is no cross-book agreement."
            answer.disagreement = "None: only one book addresses the query."

    return {"answer": answer, "iteration": state["iteration"] + 1}


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
    return judge.invoke(prompt, config={"tags": ["role:critique_e"]})


# MARK: E SECOND JUDGE
def e_judge_second(query: str, corpora: dict[str, CorpusState]) -> ESecondBatch:
    """E's retry look: the same evidence-only judgment as e_judge_first, restricted to ESecond's schema —
    no retry, no narrowed_query. After a retry round every record must end ok or silent, so this look
    cannot propose another one. The same rule holds: the composer's draft is never in the prompt, and
    the prompt never says "support"."""
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
        "itself state. Then give the proposition P. "
        "Add exactly one entry per book, corpus_id exactly A or B as given above."
    )
    judge = critique_llm.with_structured_output(ESecondBatch)
    return judge.invoke(prompt, config={"tags": ["role:critique_e"]})


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
    runs it, and the E_second look later overwrites it — so every record the graph ends on is ok or silent."""
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


# MARK: E FIRST / SECOND NODES (item 44.3)
def _verdicts_for_every_book(state: ReflectionState, judge) -> list:
    """E's batch, retried once for any book it left out. A structured-output batch occasionally comes back one
    book short, and a missing verdict would delete that book's slot downstream (the state invariant: returning
    corpora replaces the whole dict) — so the missing books are asked for again, once, and a book still absent
    after the retry raises a message that names it instead of a bare KeyError."""
    verdicts = list(judge(state["query"], state["corpora"]).verdicts)
    missing = [cid for cid in state["corpora"] if cid not in {v.corpus_id for v in verdicts}]
    if missing:
        retry = judge(state["query"], state["corpora"])
        seen = {v.corpus_id for v in verdicts}
        verdicts += [v for v in retry.verdicts if v.corpus_id not in seen]
        still = [cid for cid in state["corpora"] if cid not in {v.corpus_id for v in verdicts}]
        if still:
            raise ValueError(f"E returned no verdict for {', '.join(sorted(still))} after a retry")
    return verdicts


def _e_records(state: ReflectionState, raw_verdicts) -> dict:
    """The deterministic tail both E looks share: postprocess_e every raw verdict, then e_record turns
    each one into the canonical per-book slot. Every book in state["corpora"] gets a slot — the state
    invariant: returning corpora replaces the whole dict, so an omitted book is a deleted book."""
    verdicts = {verdict.corpus_id: postprocess_e(verdict) for verdict in raw_verdicts}
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
    return corpora


def e_first(state: ReflectionState) -> dict:
    """E's first look as its own graph node: one evidence-only call over both books — query, chunks
    and lineage, never the composer's draft — then the deterministic tail turns each raw verdict into
    the canonical per-book record. The comparison critique stays out of this node."""
    return {"corpora": _e_records(state, _verdicts_for_every_book(state, e_judge_first))}


def e_second(state: ReflectionState) -> dict:
    """E's retry look: the same evidence-only judgment as e_first, but ESecond's schema carries no retry
    or narrowed_query, so this look only decides ok or silent. Every record is final after this node, and
    retry_used is true on a book whose prior look was 'miss'."""
    return {"corpora": _e_records(state, _verdicts_for_every_book(state, e_judge_second))}


# MARK: REFLECT
def reflect(state: ReflectionState):
    """The cross-book comparison critique. The per-book verdict now lives in e_first/e_second, so this
    node judges agreement/disagreement as a whole and short-circuits when fewer than two books are 'ok'
    — there is no comparison to judge then."""
    ok = [corpus_id for corpus_id in state["corpora"] if state["corpora"][corpus_id]["label"] == "ok"]
    if len(ok) < 2:
        return {"feedback": "Comparison skipped: fewer than two books answer the query.",
                "needs_revision": False}

    comparison_prompt = (f"Query: {state['query']}\n"
                         f"Agreement: {state['answer'].agreement}\n"
                         f"Disagreement: {state['answer'].disagreement}\n"
                         "<instruction: judge the comparison as a whole; you have no access to per-book chunks or findings, so you cannot and must not reference one book's depth specifically>")
    comparison = llm.with_structured_output(ComparisonCritique).invoke(comparison_prompt,
                                                                       config={"tags": ["role:reflect"]})
    return {"feedback": comparison.feedback, "needs_revision": comparison.needs_revision}


def route_after_e_first(state: ReflectionState):
    """The retry decision, placed after e_first: any book e_first left 'miss' owes the retry round;
    otherwise the flow moves on to composer. Retry fires at most once because the retry node's only
    outgoing edge lands on e_second, never back on e_first."""
    for corpus_id in state["corpora"]:
        if state["corpora"][corpus_id]["label"] == "miss":
            return "retry"
    return "done"


reflection_graph = StateGraph(ReflectionState)
reflection_graph.add_node("retriever", retriever)
reflection_graph.add_node("retry_retriever", retriever)  # the same callable: the retry entry
reflection_graph.add_node("e_first", e_first)
reflection_graph.add_node("e_second", e_second)
reflection_graph.add_node("composer", composer)
reflection_graph.add_node("reflect", reflect)
reflection_graph.add_edge(START, "retriever")
reflection_graph.add_edge("retriever", "e_first")
reflection_graph.add_conditional_edges("e_first", route_after_e_first,
                                       {"retry": "retry_retriever", "done": "composer"})
reflection_graph.add_edge("retry_retriever", "e_second")
reflection_graph.add_edge("e_second", "composer")
reflection_graph.add_edge("composer", "reflect")
reflection_graph.add_edge("reflect", END)

reflection_app = reflection_graph.compile()


async def run_query(query: str, callbacks=None) -> ReflectionState:
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
    config = {"callbacks": callbacks} if callbacks else None
    return await reflection_app.ainvoke(initial_state, config=config)


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
                    print(f"""_Findings: {slot.corpus_id} - {slot.headline[:width]} ({len(slot.pairs)} pairs)""")
            if node == "reflect":
                print(f"""_Feedback:  {update["feedback"][:width]}""")
                print(f"""_Needs_revision: {update["needs_revision"]}\n""")


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
