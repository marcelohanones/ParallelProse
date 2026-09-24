# Roadmap

## Where we are

**Project started 2026-08-07.**

- **v1 (frozen, 2026-09-16)** — single corpus, two separate agents: a fixed reflect-loop graph and a tool-flexible MCP
  demo agent. No comparison capability, no quality loop on the flexible agent.
- **v2 (in progress)** — merges the two agents into one graph and generalizes it to compare two corpora ("Parallel
  Prose": what do two books say about an issue). Items 1 (the merge, 2026-09-19) and 2 (two corpora, 2026-09-24) are
  done; items 4–6 are designed, not yet built (item 3 was dropped, see "Considered and dropped").
- **v3 (planned)** — starts once v2 is complete, with an evaluation harness and demo packaging; the other ideas stay in
  the backlog, deliberately deferred, not forgotten.
- **RAG-Tetris** — a separate future project (comparing code across versions), out of scope here.

Suggested build order below follows dependency, not memory-entry order: state shape and the merge come first because
retrofitting them under already-built features costs more than building on top of them.

## v2 — next up

### 1. Architecture merge — retriever becomes a nested tool-selecting agent

**Status: done, 2026-09-19.** The outer graph (`composer`, `reflect`, routing) needed no changes; only `retriever` did.
Built as designed, plus what the merge turned out to need:

- The inner agent is bounded by `ToolCallLimitMiddleware` (`exit_behavior="end"`) and `ModelCallLimitMiddleware`.
- `chunks` come from the successful `ToolMessage`s, and `lineage` (`iteration`, `tool`, `args`) replaced `chunks_id`.
- Because the model can now skip retrieval, which v1 never allowed: a `system_prompt`, tool docstrings written as
  when-to-use rules, and a fallback that calls `call_parent_retriever` when no chunks come back.
- Open, deliberately left for item 4: an impossible query still uses up `MAX_ITERATIONS` with no resolution, and
  `reflect` grades the draft without seeing the chunks.

**What:** keep the existing outer graph (`ReflectionState` → `composer` → `reflect`, conditional retry) exactly as-is.
The only structural change: `retriever` stops hardcoding one retrieval call and becomes a small inner `create_agent`
that picks among the 4 existing retrieval strategies, bounded by `ToolCallLimitMiddleware`. **Why:** two agents
currently prove two different things (tool-flexible retrieval vs. a quality-refinement loop) with no reason to keep them
apart once seen clearly — one already has the loop, the other already has the flexibility. **Synergy:** this is the
chassis. Every item below assumes this merged graph exists.

### 2. Two-corpus generalization + nested per-corpus state

**Status: done, 2026-09-24.** Built in four steps (tools, retriever, composer, an end-to-end run on both books), plus
what the two-book case turned out to need:

- Tools take a `corpus` the model never sees: the bridge removes it from the schema copy the model gets and adds it back
  from a closure before calling the server. Chosen over letting the model fill the slot, because a wrong book would fail
  silently.
- `retriever` loops over `state["corpora"]`, with tools and inner agent cached per book, and writes each result into that
  book's own slot.
- `composer` builds its context with `format_context`: one block per book, headed by the title and author from the
  catalog, with the chunks under it.
- Each book is defined once, in `catalog.py` (id, title, author, collection name, file), so a book swap is one entry.
- Open, deliberately left for items 4–6: `reflect`, `route_after_reflection` and the `narrowed_query` branch of
  `composer` still read a single `CORPUS_ID`, so a revision round drops the other book; the answer is one blended
  paragraph that does not attribute claims to a book. Both books still get the same literal query (the query-splitting
  idea was dropped, see "Considered and dropped").

**What:** generalize from one corpus to two (`corpora: {A: {...}, B: {...}}` instead of flat `docs_a`/`docs_b`/
`status_a`/`status_b` fields). **Why:** the project's actual point is comparison, not single-corpus Q&A. A flat field
pair means every new per-corpus concern (docs, then status, then narrowed_query) needs its own new pair — schema churn
as an ongoing tax. **Synergy:** every later item here is naturally per-corpus once this lands. Doing it after items 3–6
exist would mean reworking all of them.

### 4. `reflect` becomes a diagnostic router

**What:** `reflect` stops being a binary pass/fail gate and judges each corpus separately, telling *why* a corpus's
coverage is thin: a retrieval miss (a narrowed-query retry can fix it) or genuine silence (the source doesn't address
it — no retry helps). A vocabulary mismatch is treated as a miss: the retry's narrowed query is its remedy. `reflect`
also sees the retrieved chunks, so it checks each corpus's claims against that corpus's own text. **Why:** today's
binary gate can't tell these apart, so it can't route to the right fix — or know when no fix applies — and it grades the
draft without seeing the chunks. **Synergy:** the piece that makes items 1 and 2 cohere instead of firing
independently. Also the direct dependency for items 5 and 6 below.

### 5. Per-corpus retry

**What:** sharpen the existing retry edge so only the corpus `reflect` flags gets a narrowed-query retry — the other
corpus's already-good retrieval isn't redone. **Why:** today's retry is all-or-nothing across both corpora, wasting cost
and risking degrading an already-good answer on one side. **Synergy:** directly consumes item 4's diagnostic label and
item 2's nested state — it's the "act on the diagnosis" step.

### 6. Composer produces structured comparison output

**What:** `composer`'s draft becomes explicit slots (agreement, disagreement, unique to each corpus) instead of one
narrative paragraph. When `reflect` labels a corpus "silent," `composer` states that absence directly as a finding,
instead of a hedged paragraph that reads like a failure. **Why:** structured slots are what make `reflect`'s per-corpus
coverage check (item 4) checkable at all — free prose isn't. **Synergy:** closes the loop back to `reflect`: the
diagnostic router (item 4) is only as good as the output it's inspecting.

## Considered and dropped

### Query-splitting node + terminology-bridging tool (was item 3)

Dropped 2026-09-24 before being built; items 4–6 keep their numbers. A query-splitting node would rewrite the question
per corpus *before* retrieval, so it only has the model's memory of a work, not of the indexed edition. One probe on the
two books (a commodities question) showed no gain: Augustine's on-topic hits went from `[0, 2, 5, 2]` to `[0, 0, 0, 3]`,
and Debord's top chunks did not change. The retry loop already corrects a weak first query with evidence (`reflect` →
`narrowed_query`), and a terminology-bridging tool needs a corpus-derived mapping source that does not exist. Judged not
worth their cost for this project; revisit only if a measured failure shows the retry loop cannot recover a vocabulary gap.

## v3 — after v2 is complete

### Evaluation and demo packaging

**What:** a small evaluation harness — about 10 questions and two proposed metrics, faithfulness (is each claim
supported by the retrieved text) and attribution (is each claim credited to the right book) — run before and after the
v2 changes so the report has numbers. Plus the demo package: a README with a real run and the final v2 architecture
notebook. **Why:** evidence that the comparison works is more convincing than a description of it, and it is something a
reviewer can check. **Synergy:** items 4–6 are the changes it measures, which is why it comes after them.

### Backlog (deferred, not dropped)

- **Summarizing tool** — condense each corpus's retrieved chunks into a compact position before `composer` synthesizes.
  Costs an extra LLM call and some risk of losing nuance.
- **Era/context-annotation tool** — surfaces "this passage is from 350 BCE / this one is from 2020" as metadata, so the
  comparison doesn't flatten two authors from different eras into contemporaneous peers.
- **Quote-extraction tool** — pulls verbatim supporting text per side to ground the comparison in exact words instead of
  paraphrase. Costs tokens.

These were deferred deliberately to keep v2 scoped to the changes with the clearest, most concrete payoff — not
because they're low-value.

## Out of scope here

**RAG-Tetris** (comparing a language feature's evolution across versions, e.g. Python's GC or type system across
releases) is a separate future project, built elsewhere, not in this directory. If a design choice here ever has to pick
between what's best for this project and what would ease future sharing with RAG-Tetris, this project wins — Tetris gets
addressed when it actually starts.
