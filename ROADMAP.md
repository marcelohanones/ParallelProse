# Roadmap

## Where we are

**Project started 2026-08-07.**

- **v1 (frozen, 2026-09-16)** — single corpus, two separate agents: a fixed reflect-loop graph and a tool-flexible MCP demo agent. No comparison capability, no quality loop on the flexible agent.
- **v2 (in progress)** — merges the two agents into one graph and generalizes it to compare two corpora ("Parallel Prose": what do two books say about an issue). Item 1 (the merge) is done as of 2026-09-19; items 2–6 are designed, not yet built.
- **v3 (backlog)** — discussed and deliberately deferred, not forgotten.
- **RAG-Tetris** — a separate future project (comparing code across versions), out of scope here.

Suggested build order below follows dependency, not memory-entry order: state shape and the merge come first because retrofitting them under already-built features costs more than building on top of them.

## v2 — next up

### 1. Architecture merge — retriever becomes a nested tool-selecting agent
**Status: done, 2026-09-19.** The outer graph (`composer`, `reflect`, routing) needed no changes; only `retriever` did. Built as designed, plus what the merge turned out to need:
- The inner agent is bounded by `ToolCallLimitMiddleware` (`exit_behavior="end"`) and `ModelCallLimitMiddleware`.
- `chunks` come from the successful `ToolMessage`s, and `lineage` (`iteration`, `tool`, `args`) replaced `chunks_id`.
- Because the model can now skip retrieval, which v1 never allowed: a `system_prompt`, tool docstrings written as when-to-use rules, and a fallback that calls `call_parent_retriever` when no chunks come back.
- Open, deliberately left for item 4: an impossible query still uses up `MAX_ITERATIONS` with no resolution, and `reflect` grades the draft without seeing the chunks.

**What:** keep the existing outer graph (`ReflectionState` → `composer` → `reflect`, conditional retry) exactly as-is. The only structural change: `retriever` stops hardcoding one retrieval call and becomes a small inner `create_agent` that picks among the 4 existing retrieval strategies, bounded by `ToolCallLimitMiddleware`.
**Why:** two agents currently prove two different things (tool-flexible retrieval vs. a quality-refinement loop) with no reason to keep them apart once seen clearly — one already has the loop, the other already has the flexibility.
**Synergy:** this is the chassis. Every item below assumes this merged graph exists.

### 2. Two-corpus generalization + nested per-corpus state
**What:** generalize from one corpus to two (`corpora: {A: {...}, B: {...}}` instead of flat `docs_a`/`docs_b`/`status_a`/`status_b` fields).
**Why:** the project's actual point is comparison, not single-corpus Q&A. A flat field pair means every new per-corpus concern (docs, then status, then narrowed_query) needs its own new pair — schema churn as an ongoing tax.
**Synergy:** every later item here is naturally per-corpus once this lands. Doing it after items 3–6 exist would mean reworking all of them.

### 3. Query-splitting node + terminology-bridging tool
**What:** two complementary fixes for the same failure case — a query-splitting node rephrases the question per corpus before retrieval; a terminology-bridging tool maps a modern concept to its period-appropriate equivalent (e.g. "virtue" → "arete").
**Why:** motivating case is Aristotle vs. a contemporary author — the same literal query retrieves well from the modern text and returns nothing from the ancient one, because vocabulary and framing drifted across time. Terminology-bridging targets *why* the phrasing diverges; query-splitting handles it more generally. Neither alone is judged sufficient.
**Synergy:** gives `reflect` (next item) concrete, distinguishable failure modes to detect, instead of one generic "coverage thin" signal.

### 4. `reflect` becomes a diagnostic router
**What:** `reflect` stops being a binary pass/fail gate and classifies *why* a corpus's coverage is thin: a retrieval miss, a vocabulary/framing mismatch, or genuine silence (the source doesn't address it — no retry helps).
**Why:** today's binary gate can't tell these apart, so it can't route to the right fix — or know when no fix applies.
**Synergy:** the piece that makes items 1 and 3 cohere instead of firing independently. Also the direct dependency for items 5 and 6 below.

### 5. Per-corpus retry
**What:** sharpen the existing retry edge so only the corpus `reflect` flags gets a narrowed-query retry — the other corpus's already-good retrieval isn't redone.
**Why:** today's retry is all-or-nothing across both corpora, wasting cost and risking degrading an already-good answer on one side.
**Synergy:** directly consumes item 4's diagnostic label and item 2's nested state — it's the "act on the diagnosis" step.

### 6. Composer produces structured comparison output
**What:** `composer`'s draft becomes explicit slots (agreement, disagreement, unique to each corpus) instead of one narrative paragraph. When `reflect` labels a corpus "silent," `composer` states that absence directly as a finding, instead of a hedged paragraph that reads like a failure.
**Why:** structured slots are what make `reflect`'s per-corpus coverage check (item 4) checkable at all — free prose isn't.
**Synergy:** closes the loop back to `reflect`: the diagnostic router (item 4) is only as good as the output it's inspecting.

## v3 — backlog (deferred, not dropped)

- **Summarizing tool** — condense each corpus's retrieved chunks into a compact position before `composer` synthesizes. Costs an extra LLM call and some risk of losing nuance.
- **Era/context-annotation tool** — surfaces "this passage is from 350 BCE / this one is from 2020" as metadata, so the comparison doesn't flatten two authors from different eras into contemporaneous peers.
- **Quote-extraction tool** — pulls verbatim supporting text per side to ground the comparison in exact words instead of paraphrase. Costs tokens.

These were deferred deliberately to keep v2 scoped to the changes with the clearest, most concrete motivating failure case (the cross-era vocabulary mismatch) — not because they're low-value.

## Out of scope here

**RAG-Tetris** (comparing a language feature's evolution across versions, e.g. Python's GC or type system across releases) is a separate future project, built elsewhere, not in this directory. If a design choice here ever has to pick between what's best for this project and what would ease future sharing with RAG-Tetris, this project wins — Tetris gets addressed when it actually starts.
