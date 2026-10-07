# Roadmap

## Where we are

**Project started 2026-08-07.**

- **v1 (frozen, 2026-09-16)** — single corpus, two separate agents: a fixed reflect-loop graph and a tool-flexible MCP
  demo agent. No comparison capability, no quality loop on the flexible agent.
- **v2 (done, 2026-10-02)** — merges the two agents into one graph and generalizes it to compare two corpora ("Parallel
  Prose": what do two books say about an issue). Items 1 (the merge, 2026-09-19), 2 (two corpora,
  2026-09-24), 4 (reflect as diagnostic router, 2026-09-27), 5 (per-corpus retry, 2026-09-28), and 6 (structured
  composer output, 2026-10-02) are all done (item 3 was dropped, see "Considered and dropped").
- **v3 (done, 2026-10-03)** — five ordered phases: era-annotation and quote-extraction (items 7-8, the two cheap
  wins), then app packaging (item 9), then making `Critique` 2-book native in two steps — a cheap instruction-only
  try (item 10) measured before deciding on a structural fix (item 11). Items 7 (era-annotation), 8
  (quote-extraction), 9 (app packaging), 10 (instruction-only try, measured, didn't work), and 11 (structural fix,
  validated against item 10's own test) are all done (2026-10-02 through 2026-10-03) — see "v3 — after v2 is
  complete" below.
- **v4 (in progress, started 2026-10-03)** — a synthesis layer connecting several targeted queries to a stated
  thesis (item 12, committed), then a proper test suite (item 16), then a theme parser (item 17), then the evaluation harness (item 30). Items
  13-15 are the retrieval and silent-verdict fixes built after item 12 was committed. The synthesis layer was always
  its own version — a distinct capability layered on top of a finished, tested two-book comparison
  system; the test suite and eval harness moved here from v3 since v3's own completion no longer waits on them, and
  now land after the synthesis layer so they cover it too. See "v4 — after v3 is
  complete" below.
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
- `retriever` loops over `state["corpora"]`, with tools and inner agent cached per book, and writes each result into
  that
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

**Status: done, 2026-09-27.** Built as designed (see `project_item4_reflect_router_decisions.md`), plus what building
and two real runs turned out to need:

- `Critique` now nests a `CorpusCritique` per book (`corpus_id: Literal["A", "B"]`, `label: ok|miss|silent`, `reason`,
  `narrowed_query`) instead of one flat verdict — one LLM call judges both books.
- `reflect`'s prompt gives the model an explicit id→title mapping (built from `CATALOG`, since `format_context`'s
  headers show titles, never "A"/"B"), the retrieved chunks (`format_context`), and the query log so far
  (`format_attempts`) — so a label is checked against that book's own text, not asserted from the draft alone.
- `corpus_id` is `Literal["A", "B"]`, not a plain `str`: a malformed value now fails at the schema boundary instead of
  silently misfiling into the wrong book's slot.
- `narrowed_query` is code-enforced to `None` whenever `label != "miss"`, not left to the field description alone.
- The return carries every book's updated slot — fixes the earlier bug where book B's slot was dropped on every
  `reflect` call.
- `show()` prints each book's `label`/`reason`/`narrowed_query` per round, not just one hardcoded book.
- Two real runs on both books (gpt-4o-mini) validated the labels track the actual chunks — reasons cited concrete
  content, not filler. Also surfaced two things for the backlog below: `reflect`'s label on *identical* chunks isn't
  stable call-to-call (one run flipped a book between `ok` and `miss` across rounds with no new evidence), and once
  every book is `ok`, nothing stops `needs_revision` from staying `True` and re-running `composer` on unchanged text
  until `MAX_ITERATIONS`.
- Open, deliberately left for item 5: whether a retry fires *at all* is still gated on book A's `narrowed_query` alone
  (`route_after_reflection`/`composer` still hardcode `CORPUS_ID`) — a book B miss only gets acted on if A also needed
  a retry that round, since `retriever` retries every book whenever it runs at all.

**What:** `reflect` stops being a binary pass/fail gate and judges each corpus separately, telling *why* a corpus's
coverage is thin: a retrieval miss (a narrowed-query retry can fix it) or genuine silence (the source doesn't address
it — no retry helps). A vocabulary mismatch is treated as a miss: the retry's narrowed query is its remedy. `reflect`
also sees the retrieved chunks, so it checks each corpus's claims against that corpus's own text. **Why:** today's
binary gate can't tell these apart, so it can't route to the right fix — or know when no fix applies — and it grades the
draft without seeing the chunks. **Synergy:** the piece that makes items 1 and 2 cohere instead of firing
independently. Also the direct dependency for items 5 and 6 below.

### 5. Per-corpus retry

**Status: done, 2026-09-28.** Built as designed (see `project_item5_per_corpus_retry_decisions.md`), validated with
one real run on both books:

- `retriever`'s per-book loop now reads each book's `label` before running: `None` (round 1) or `"miss"` falls through
  to the existing query/narrowed_query logic; `"ok"` or `"silent"` skips retrieval and forwards that book's slot
  (`chunks`, `lineage`, `label`, `reason`, `narrowed_query`) unchanged into `corpora_updates`, then `continue`s to the
  next book (see `CLAUDE.md`, "State invariants").
- `composer` lost its per-book loop: one prompt per call, chosen once from `needs_revision` alone (`context` still
  carries every book's current chunks either way); `narrowed_query` no longer enters the prompt text, since it already
  did its job steering `retriever`.
- `route_after_reflection` now scans every book for `label == "miss"` before deciding (no `return` inside that scan),
  so a book's position in `state["corpora"]` no longer decides the route; the case where nothing needs revision and no
  book is a miss now falls to `END` instead of returning `None`.
- The real run confirmed the skip directly: across two later retry rounds, book A (`ok`) stayed frozen at 2 lineage
  entries while book B (`miss`) picked up new ones each retry, and B's label flipped `miss -> ok` once its narrowed
  retries changed its chunks.
- Open, deliberately left for item 6 (finding 3 from item 4): once every book is `ok`, `needs_revision` can still stay
  `True` — the validation run ended via `MAX_ITERATIONS`, not a stop rule.

**What:** sharpen the existing retry edge so only the corpus `reflect` flags gets a narrowed-query retry — the other
corpus's already-good retrieval isn't redone. **Why:** today's retry is all-or-nothing across both corpora, wasting cost
and risking degrading an already-good answer on one side. **Synergy:** directly consumes item 4's diagnostic label and
item 2's nested state — it's the "act on the diagnosis" step.

### 6. Composer produces structured comparison output

**Status: done, 2026-10-02.** Atomized into three functions, each walked and built separately, as designed:

- `composer` (6.1) returns `ComposerAnswer` — a top-level `agreement`/`disagreement` pair plus `unique_findings`
  (`list[CorpusComposer]`, one `corpus_id`/`finding` entry per book), mirroring `Critique`/`CorpusCritique`'s own
  nesting. A `"silent"` corpus's `finding` is overwritten in code after the LLM call, the same alibi mechanic as
  `reflect`'s own `narrowed_query` guard — never left to the model's prose alone.
- `reflect` (6.2) gets a new `format_answer` formatter (mirroring `format_context`/`format_attempts`'s contract) that
  renders `agreement`/`disagreement` plus each corpus's `finding` by name; `reflect`'s one-line edit swaps the old raw
  `state['answer']` interpolation for `format_answer(state['answer'])`. The `Critique` schema and the per-book
  ok/miss/silent logic are untouched.
- `route_after_reflection` (6.3) had its `elif needs_revision: return "composer"` branch deleted outright: since
  `has_miss` is checked first, that branch was only ever reachable once no book was `miss` — it never gated a
  distinct case, it was item 5 finding 3's bug itself. No book `miss` now falls straight to `END`.
- Two real bugs caught and fixed during the build: `format_answer`'s signature was typed `answer: ComposerAnswer` but
  the body subscripted it as a dict (`answer["answer"]`), only working because the call site accidentally passed the
  whole `state` dict; fixed so the parameter and the call site (`format_answer(state['answer'])`) agree. A leftover
  `print(1)` debug statement was also removed.

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
worth their cost for this project; revisit only if a measured failure shows the retry loop cannot recover a vocabulary
gap.

### Survey-style queries, thematic tagging, finer position metadata

Dropped 2026-10-02. ParallelProse is scoped to targeted queries only (a specific question against the corpora), not
survey queries (an open question about a book's overall scope, e.g. "what subjects does this book cover"). That
scoping directly drops thematic tagging — labeling each chunk by subject only pays off if a survey-style query
consumes the tags, and without that consumer they'd sit unused. Finer position metadata (page/sub-heading instead of
whole-chapter) was considered in the same pass and dropped too, but for an unrelated reason: it's a targeted-query
feature, not a survey one, and it was already the weakest of the three ingestion ideas reviewed — sharper citations,
but no new question type unlocked. Era/date metadata is the one survivor of the three; it stays in the Backlog below.

### Summarizing tool

Dropped 2026-10-02. Not a new capability, just a refinement of something `composer` already does: it already
synthesizes directly from the retrieved chunks today, and a summarizing step would only insert condensation in front
of that, with a stated risk of losing nuance for an extra LLM call. Era-annotation and quote-extraction both add
something the system can't currently show (chronology, verbatim grounding); this one doesn't change what the output
looks like or what question gets answered.

## v3 — after v2 is complete

### 7. Era-annotation

**Status: done, 2026-10-02.** Built as designed (see `notebooks/ParallelProse/v3-01-graphs.ipynb`), plus one
correction found while reading the code before building:

- `format_answer` (agent.py) carries no book-identity header at all — the roadmap's original wording was off. The
  three real surfacing points are `format_context`'s header, and the inline `book_map` strings built separately
  inside `composer` and `reflect`; `format_answer` stays untouched, since there's nothing book-shaped there to attach
  an era to.
- `Book` (catalog.py) gained a single free-text `era: str` field, matching its three existing plain-string fields —
  nothing downstream compares, sorts, or parses it, so no numeric or BCE/CE-aware type was needed. Augustine is
  `"397"`, Debord is `"1967"`; a bare number reads as CE, an explicit `"BCE"` suffix marks a BCE date (e.g.
  Aristotle would be `"340 BCE"`).
- All three surfacing points now interpolate `CATALOG[corpus_id].era` into their existing header/`book_map` strings.
- Validated directly: `format_context`'s header renders `"... - Era: 397"` / `"... - Era: 1967"`, and a full graph
  run on both books completed with no regression (both books still labeled `ok`).

**What:** a new `era`/period field on `Book` in `catalog.py`, surfaced wherever a book's identity is already named to
the LLM (`format_context`'s header, `composer`'s and `reflect`'s `book_map` strings); no ingestion change needed,
since era belongs to the book, not the chunk. **Why:** fixes a real correctness risk — comparing Augustine (~400 CE)
and Debord (1967) with no era marker risks `composer` treating them as contemporaries. **Synergy:** cheapest item in
v3, done first.

### 8. Quote-extraction

**Status: done, 2026-10-02.** Built as designed (see `notebooks/ParallelProse/v3-01-graphs.ipynb`), plus one
correction found while reading the code before building:

- The roadmap's original wording named `CorpusComposer`; the actual schema is `CorpusFinding` (agent.py:73-79,
  nested inside `ComposerAnswer`).
- `CorpusFinding` gained `quote: str | None = Field(default=None, ...)`, mirroring `narrowed_query`'s own
  shape (`CorpusCritique`, agent.py:57-60) — meaningful only when `label` isn't `"silent"`, singular rather than a
  list, matching the roadmap's "an exact excerpt" wording.
- `composer`'s existing silent-override loop (agent.py:212-217) now also sets `slot.quote = None`, right alongside
  where it already overwrites `slot.finding` for a silent book.
- Validated directly against a real run: both books returned a genuine verbatim excerpt backing their finding
  (Augustine's memory/sight/expectation passage, Debord's "carcass of time" line). The `silent` → `quote = None`
  path wasn't exercised in that run (neither book landed `silent`), but it's a one-line deterministic assignment
  mirroring `finding`'s already-validated override from item 6.

**What:** add a verbatim-quote field to `CorpusFinding` (composer's per-corpus finding schema), grounding each
finding in an exact excerpt instead of paraphrase. **Why:** direct evidence a reviewer can check — same rationale as
the eval phase itself. **Synergy:** feeds the eval harness's faithfulness check for free.

### 9. App packaging

**Status: done, 2026-10-02.** Built as designed (see `notebooks/ParallelProse/v3-01-graphs.ipynb` for the
`run_query` destination), plus what the build turned out to need:

- `run_query(query: str) -> ReflectionState` (agent.py:346-365) starts the MCP server lazily, exactly once per
  process — a module-level `_server_task` flag, checked and set on first call, mirroring this file's own
  `bridged_tools_by_corpus`/`retrieval_agents_by_corpus` caching idiom (agent.py:28-29) — instead of restarting the
  server on every call the way the old `run()` did.
- `run_query` uses `ainvoke`, not `astream`: the goal is the one final state as a return value, not a live per-step
  print. `run()`'s old `show()`-based printing moved to a thin `demo()` wrapper under `__main__`, which just calls
  `run_query` and prints the fields it cares about.
- One real bug caught while placing it: the first attempt landed `run_query` still nested inside
  `if __name__ == "__main__":` — unreachable from outside the script, the exact problem being fixed. A second,
  independent attempt added a duplicate definition further down, after `reflection_app` compiled; the second one
  (correctly placed, module-level) won at import time, and the first was deleted as dead code.
- Validated directly: `run_query` imported and called from a separate script (no `__main__` involvement) returned a
  real `ReflectionState` dict with a populated `ComposerAnswer` inside it.
- `README.md` now carries a real-run write-up (query, agreement, disagreement, each book's finding and quote) from
  an actual `run_query` call. `notebooks/ParallelProse/v2-04-architecture-final.ipynb` documents the finished v2
  architecture (sections B–F, one per roadmap item 1–2, 4, 5, 6), each claim anchored to real `agent.py` line
  numbers, with real (not fabricated) code-cell output — a capstone paired with `v2-01`/`v2-02`'s earlier,
  pre-build sketches.

**What:** a `run_query(query) -> ReflectionState`-style function that runs the graph once and returns/persists the
full final state (the old `run()` only printed, returned nothing); a real-run write-up in `README.md`; the final v2
architecture notebook. **Why:** this is the shared infrastructure both the eval harness and a reviewer-facing demo
need. **Synergy:** must land before the eval harness, which reuses this run function rather than building a second
one.

### 10. `Critique` feedback scoping — instruction-only (cheap first try)

After testing v2, we have concluded that the architecture merge to turn v1 into a 2-book capable system, had some design
choices that weakened it making more a hybrid than a native 2-book system. So, two ways ahead: item 10 is the cheap one,
and item 11 is the thorough one.

**Status: done, measured, did not work, 2026-10-03.** Built: one sentence inserted into `reflect`'s instruction
block (agent.py:280-281) — "feedback must judge the comparison as a whole only — never single out one book's depth
or nuance specifically; that's reason's job for that book, already captured in corpora_critique." Measured against
the pre-declared test (does `feedback` single out one book's depth unprompted by the other) on 6 real runs, 3
compound-query + 3 non-compound: **6 of 6 still singled out one book by name** ("Debord's work is not sufficiently
emphasized," "Augustine's discussion... could be elaborated... Debord's insights... could be expanded"),
`needs_revision=True` in all 6. The instruction-only lever, which partially worked for the earlier quote-integration
and query-scope complaints, had no measurable effect on this specific failure mode. This result is the trigger for
item 11.

**What:** add an explicit instruction to `reflect`'s prompt scoping `feedback` to the
cross-book comparison (agreement/disagreement) only, leaving all per-book depth to the existing `label`/`reason` —
no schema change, no new fields. Measured, not assumed: run it repeatedly on real queries (compound and
non-compound) and check whether `feedback`'s text ever singles out one book's depth unprompted by the other — a
sharper test than "does it name a book," since legitimately describing both authors in one comparison sentence is
not the failure mode. **Why:** `ComposerAnswer` already splits cross-book vs. per-book cleanly (item 6); `Critique`
never got the same treatment — a holdover from v1's single-book design that `label`/`reason` already outgrew (see
`project_critique_single_book_debt.md`) — so `feedback`'s free text keeps re-litigating per-book depth that
`label`/`reason` already covers in a bounded, falsifiable way. Confirmed independent of query complexity: a
compound query ("how is X experienced, and what shapes it") and its non-compound version showed the same per-book
nagging rate and content, ruling out query shape as the driver. **Synergy:** the cheapest possible fix — one more
prompt sentence, the same lever already proven partially effective twice this session (quote-integration,
query-scope complaints). Its measured leak rate is the direct input to item 11's go/no-go decision.

### 11. `Critique` becomes 2-book native — structural (triggered by item 10's result)

**Status: done, validated, 2026-10-03.** Built as designed (see `notebooks/ParallelProse/v3-01-graphs.ipynb`,
item 11), plus what the build turned out to need:

- `reflect` stays one function and one graph node — no changes to `route_after_reflection`, `show()`, or the
  graph's wiring. `Critique` splits into two schemas instead: `PerBookCritique` (`corpora_critique`, today's
  unchanged per-book call) and `ComparisonCritique` (`needs_revision`/`feedback` only). The comparison call's
  prompt carries only `state['query']` and `state['answer']`'s `agreement`/`disagreement` strings — never chunks,
  attempts, or per-book `finding`/`quote`.
- One real bug caught during the build: `ComparisonCritique`'s class docstring and `feedback` field description
  were left over from the old 3-field `Critique` — one described "one entry per book," the other instructed the
  model to ground itself in "retrieved passages," neither of which this restricted call has access to. Both are
  schema-level text sent to the model as part of structured-output generation, so this was a real leaked surface,
  not just stale documentation; both were rewritten to describe only what each schema actually holds.
- Validated two ways: one real run confirmed `feedback` never named a book while both books independently landed
  `ok` with grounded, chunk-specific `reason` text (the unchanged per-book call still works). Then item 10's exact
  6-run test (3 compound-query, 3 non-compound) was rerun against the new split — **0 of 6 leaked**, reversing
  item 10's 0-of-6 *pass* rate to a 6-of-6 *pass* rate on the identical acceptance test.

**What:** split `reflect`'s one LLM call into two: an unchanged per-book call (`label`/`reason`/`narrowed_query`)
and a second, context-restricted call that never sees per-book chunks or findings, so it structurally cannot
comment on per-book depth. Item 10's actual leak examples (all 6 runs named a specific book — e.g. "Debord's work
is not sufficiently emphasized," "Augustine's discussion... could be elaborated") calibrate this second call's
prompt and acceptance test, rather than designing it blind. **Why:** instruction-only scoping (item 10) asked the
model to honor a distinction it didn't honor even once in 6 tries — removing the model's *access* to per-book
detail during the comparison-level judgment is the only real structural guarantee against the same leak
recurring. **Synergy:** directly consumes item 10's findings; must land before the test suite (item 16) so the
suite is written against `Critique`'s fully settled shape, not one about to change again.

## v4 — after v3 is complete

### 12. Synthesis layer — connect targeted queries to a stated thesis

**Status: in progress, started 2026-10-03.** **What:** a standalone, non-graph function
(`synthesize(thesis, bites) -> Synthesis`) that reads a session log of already-finished `(query,
ComposerAnswer)` bites plus one fixed thesis, and returns a connective narrative plus an
`uncovered_angle`/`candidate_query` naming what the thesis still lacks — a suggestion only, never auto-run;
the human decides every query, including whether to take the suggestion. A companion `save_bite`/`load_bites`
pair persists bites to a flat JSON session file (`{"thesis": ..., "bites": [...]}`), one thesis set once
per series. Paired with a brief for Claude web (`docs/claude_web_query_brief.md`) instructing it to decompose a
theme into one or more bounded theses (splitting when a theme fails the common-throughline test — do all of
one thesis's queries plausibly weave into one narrative?) and each thesis into single-themed, non-compound
queries. **Why:** `composer`/`reflect` are built and validated around one targeted query at a time (items 4-11);
bending them to also reason about a broader, cross-query thesis risks the same half-adopted-axis bug item
10/11 just fixed — one node aware of a new concern, the rest of the graph blind to it — and unlike the two-book
axis, "served the thesis" has no falsifiable schema field the way `label`/`reason` do, so a corrupted
grounding loop would be far harder to catch. Keeping the thesis entirely outside the grounding loop, as a
function that only ever consumes already quote-backed answers, avoids both risks. **Synergy:** manual-first by
design — automatic chasing (the system deciding to run its own suggested query) is deliberately deferred until
the manual version proves useful. Kept as its own item within v4 rather than folded into the test suite or eval
harness (items 16 and 30): it's a distinct capability layered on top of a finished, tested two-book comparison
system, not a prerequisite for either of those, which cover the graph as it stands today.

**Also in item 12 — `composer` keeps settled findings. Status: done, validated, 2026-10-04.**

- **What:** in a retry round, a book whose `label` is still `"ok"` was skipped by `retriever` (same chunks), so
  `composer` now keeps that book's previous `finding`/`quote` instead of re-sampling them: the kept findings go into
  the prompt (so `agreement`/`disagreement` stay consistent with them), and are re-imposed in code after the LLM
  call — the same "prompt asks, code guarantees" shape as the existing silent override. A book with `label` `None`
  (round 1) or `"miss"` (new chunks) still gets a fresh finding. No state, graph, `reflect` or `synthesis.py`
  change.
- **Why:** measured, not assumed. `needs_revision` stays `False` in practice, so every retry round reran
  `composer`'s first-round prompt at temperature 0.5 with no memory of the previous answer. A controlled
  recomposition of 12 round-1 states (chunks unchanged) gave a different quoted passage for 9 of 23 findings and a
  changed claim for ~8 of 23 — some clearly worse (e.g. Augustine's stated cause, sin, dropped from "what causes
  the pursuit of approval?"). One real run showed the same: Debord `ok`, byte-identical chunks, quote swapped to an
  off-topic line in round 2. This came out of evaluating (and rejecting, on the same measurements) a per-book
  subgraph restructure: the drift was real, but caused by sampling, not by the two-book design.
- **Bug caught during the build:** the first prompt wording listed only the settled book, and the model read it as
  the full list — it dropped the other book from `unique_findings` in 2 of 6 runs (baseline: 0 of 6). Fixed by
  stating that `unique_findings` must hold one entry per book and naming which books need a fresh finding: 10 of
  10 runs complete afterwards.
- **Validated:** the same controlled test now keeps `finding` and `quote` identical for 23 of 23 `ok` books (was 14
  of 23 identical quotes), 0 missing entries, and the rewritten `agreement` text stays consistent with the kept
  findings. Three real end-to-end runs: the crowd query reached a retry round and Debord's finding/quote stayed
  identical; single-round runs unaffected.
- **Open (pre-existing, not caused by this change):** the silent override only fires if `composer` runs *after*
  `reflect` labels a book `"silent"`. When the last `reflect` labels one book `silent` and no book `miss`, the
  graph ends right away, so the final answer still carries the model's own finding for the silent book (seen in a
  real crowd-query run: Augustine `silent`, final finding still describes him).

### 13. BM25 searches the same chunks as the vector store

**Status: done, validated, 2026-10-05 (uncommitted at time of writing).** **What:** `make_bm_25_retriever`
(retrieve.py) indexed `load_corpus` output, one document per chapter, so keyword hits came back as whole chapters, up
to 90,626 characters. It now indexes the vector store's own 400-character children and maps each hit to its
4,000-character parent (`parents_of`, via `doc_id` into the docstore), the same unit the semantic tool returns.
**Why:** one 90k-character chunk put the `reflect` prompt at 226,000 characters (about 56k tokens), which gpt-4o
rejected on this account and which buried the other book's passages. **Validated:** every BM25 and ensemble result
is at most 4,000 characters for both books; a keyword probe for "Alypius" now returns the games passage in 4 of 4
results (it didn't before). **Open:** the index is rebuilt on every call; caching it is a follow-up.

### 14. Passage size: keep 4,000-character parents

**Status: tested, no change, 2026-10-05.** **What:** the same crowd query, answer text and judge, five runs each
with gpt-4o-mini, with 400-character children in place of 4,000-character parents. **Result:** the parents put the
games passage in 3 of 4 retrieved chunks and the children in 1 of 4; the label was `ok` 4 of 5 times with either
size. **Why it matters:** smaller chunks lose the passage at retrieval and gain nothing at judgment, so the parent
size stays. The passage was retrieved in every round and still judged `miss` or `silent`, so the failure is in
reading it, not in finding it. Switching to gpt-4o didn't fix that either: it said `ok` 5 of 5, but from a different
passage.

### 15. A silent verdict reaches the final answer

**Status: done, 2026-10-05.** **What:** `route_after_reflection` sends a `silent` book with no `miss` left to a new
`finalize` node (`composer` again, then `END`), instead of ending right after `reflect`. `composer` also overwrites
`agreement` and `disagreement` in code when a book is silent ("does not address the query, so there is no cross-book
agreement"). **Why:** the silent override only ran when `composer` came after `reflect`, so a `silent` verdict in the
last round left the model's own finding in the final answer. An instruction-only version of the agreement fix left
Augustine in the text, so that part is enforced in code. **Validated:** routing checked on 7 cases; a real commodities
run that went `silent` ran `finalize` and got the override; the override was also checked directly with one book
silent and with both silent. The 12-query sweep run before this change had one `silent` (commodities, Augustine) that
skipped the override, which is the case this fixes. **Still open:** the `silent` verdicts are inconsistent (commodities
was `ok` 15 of 15 in an earlier test and `silent` once since), and item 30's labeled set is what can settle that.

### 16. Test suite

**Status: done, 2026-10-05.** Suite in `tests/`: 14 offline tests (routing, retriever skip and miss-retry, composer's kept-finding and silent override, reflect's per-book return) plus 2 BM25 checks on the real corpora; `pytest` added as a dev dependency. A mutation check (breaking the routing and the silent override) failed 5 tests. The old `test_retriever`, `test_accumulation` and `test_retriever_2` are gone: the first two were superseded, and `test_retriever_2` needs the network, so its live-quality check belongs with item 17.

**What:** a proper `tests/` suite covering the graph's core node logic — `retriever`'s
skip-on-`ok`/`silent`, `composer`'s silent-override (`finding` + `quote` blanking), `reflect`'s per-book label
return, `route_after_reflection`'s routing branches — and relocating the ad-hoc `test_retriever`, `test_accumulation`,
`test_retriever_2` functions currently embedded in `agent.py`'s `__main__` block into that suite (updated to the
current state shape where still relevant, dropped where superseded). **Why:** today's only "tests" are those three
stale functions — `test_accumulation` still assumes the flat pre-item-2 state shape (`narrowed_query`/`chunks`/
`lineage` at the top level, not nested under `corpora`) and would crash if run; none of the three assert anything,
they just print; and they sit mixed in with live-call demo code in the same `__main__` block (see `CLAUDE.md`,
"Guard module side effects"). **Synergy:** lands after packaging (item 9), after `Critique`'s 2-book-native
shape settles (items 10-11), and after the synthesis layer (item 12) and the retrieval and silent-verdict fixes (items 13-15), because `run_query()`, `Critique`, and
`synthesize()` are exactly the things this suite needs to test against shapes that are finished changing; also
lands before the eval harness (item 30), because that harness checks answer *quality*, a different concern from
code correctness — it benefits from running against code that's already covered, not the other way around.

### 17. Theme batches — one batch file, one run per theme

**Status: done, 2026-10-05.** Parser and runner in `ParallelProse.theme_batches` (offline tests, plus one real run on a one-query file). **What:** `run_theme_batches(batch_file)` reads a Claude web output file (the batch format in
`docs/claude_web_query_brief.md`: themes, each with its theses and their queries), then runs each theme's queries
through `run_query`, saves every answer with `save_bite`, and synthesizes each thesis with `synthesize`
(disabled since item 32; a new session has no `synthesis` key). Each
theme is its own folder, and a single file can hold any number of themes. **Why:** the subjectivism sweep needs
many themes at once, and running them by hand doesn't scale. **Depends on:** item 12 (`save_bite`, `load_bites`,
`synthesize`).

**Layout** (local only, under `data/`, gitignored):

```
data/theme_batches/
└── augustine_debord/                      project: the two books, A then B
    └── 2026-10-05_1430/                   session: run start time
        ├── manifest.json                  source file, tryout label, books, timestamps
        ├── source.md                      copy of the Claude web document
        └── theme-01_crowds-and-the-gaze/  one folder per theme; slug from the theme title
            ├── thesis-01.json             one per thesis: theme, thesis, bites, synthesis
            └── thesis-02.json
```

Consolidation is a merge, not an LLM step: `consolidate_synthesis_file(session_dir)` (`ParallelProse.consolidate_synthesis`) writes
`<timestamp>_synthesis.json` at the session root, with every thesis's synthesis under its theme. The slash command
`/consolidate-session <session folder>` (`.claude/commands/`) runs it. Slugs are generated by the system from the theme title (lowercase, accents stripped, spaces to hyphens, capped
near 40 characters). The synthesis result is stored inside each `thesis-NN.json`, not in a separate folder.

**One-sided counter.** `one_sided_report(session_dir)` (`ParallelProse.one_sided`, run as `python -m ParallelProse.one_sided <session folder>`) counts each query as balanced, one-sided (one book silent, named), or neither, and checks the one-sided share against 20%. It reads the silence marker from the saved findings.

**First sweep (2026-10-05, brief v3, 8 themes, 35 queries).** One-sided: 1 of 35 (2.9%), under the 20%
threshold, so the brief's current wording is kept. Spot-check: most balanced pairs address the same object
(looking and desire, pity at a spectacle, memory, before whom one lays oneself open). Two pairs are loose: "why do
people worship what they have made" (Debord's commodities do not read as worship) and "where can desire come to
rest" (Debord's sleep image is a stretch). The one-sided query, "how does identification with an imagined life take
the place of the spectator's own life," is a search miss, not real silence: Augustine's theatre passage on compassion
for "feigned and scenical passions" (Book III) answers it, but parent, BM25 and ensemble retrieval never return it
for this wording. Its silent label is wrong as worded, and this is the case that retrieval, not the brief, needs
to address. Label leniency is still open (item 30).

### 18. Thesis consolidator — one flat file per session

**Status: done, 2026-10-05 (uncommitted).** **What:** `consolidate_thesis_file(session_dir)`
(`ParallelProse.consolidate_thesis`, run as `python -m ParallelProse.consolidate_thesis <session folder>`) writes
`<timestamp>_thesis.json` at the session root. It holds `session`, then `books` (letter to title, from the session's
`manifest.json`), then `theses`: one entry per thesis file, carrying `theme_folder`, `file`, and the thesis file's full
contents (`theme`, `thesis`, `bites`, `synthesis`). **Why:** the thesis file is the only file with quotes; the flat
layout gives one place to read a whole session's evidence. **Tests:** `tests/test_consolidate_thesis.py`.

### 19. Synthesis consolidator renamed to `consolidate_synthesis`

**Status: done, 2026-10-05 (uncommitted).** **What:** `consolidate.py` became `consolidate_synthesis.py`, and
`consolidate_session` became `consolidate_synthesis_file`. The output is unchanged (`<timestamp>_synthesis.json`).
Updated: `theme_batches.py`, the test file (now `tests/test_consolidate_synthesis.py`), the README, the
`/consolidate-session` command, and the item 17 text. **Why:** the module name now matches the thesis consolidator
(item 18), so the two outputs are easy to tell apart.

### 20. Twin queries — side tag in the batch format

**Status: done, 2026-10-05 (uncommitted).** **What:** a query line may carry a book tag between its letter and the
colon: `Query N.Ma[A]:` or `Query N.Ma[B]:`. `parse_batch` reads the tag into the query tuple, outside the query text
sent to retrieval, and rejects a tag that is not a key of `CATALOG`. Before synthesis, `restrict_to_side` keeps only the
tagged book's unique findings and blanks the shared `agreement` and `disagreement`; untagged queries pass through
unchanged. **Why:** a query worded in one book's vocabulary fits that book only, so the other book's answer was noise
in the synthesis of its thesis. **Validated:** parser and synthesis-input tests (`tests/test_theme_batches.py`). Sessions
v5 and v6 ran with this filter active.

### 21. Quote verification — `verified` per book

**Status: done, 2026-10-05 (uncommitted).** **What:** `verify_quotes` (now in `quote_check.py`, see item 27) stores `verified` on every
bite: for each book, `true` if its quote appears in that book's retrieved chunks, `false` if not, `null` if the book has
no quote. Whitespace and case are ignored. **Why:** a defect. Quotes come from the composer's LLM with no check, and
in v5 only 3 of 10 Debord quotes appeared verbatim in the source text (4 had joined spans with ellipses, 3 were not
in the text, 1 differed only in spacing; Augustine 9 of 13). **Validated:** two offline tests. **Open:** the check
runs against the retrieved chunks, not the source text, and a truncated quote still passes as a substring. Bites from
v5 and v6 have no `verified` field.

### 22. Debord PDF: layout extraction and reindex

**Status: done, 2026-10-05 (uncommitted); Debord collection rebuilt locally.** **What (its layout-mode reading is superseded by item 28):** `_pdf_pages` (`ingest.py`)
replaces `PyPDFLoader` for the PDF branch. It reads each page in pypdf's layout mode and falls back to plain extraction
when layout mode raises `IndexError` (5 pages in this PDF). It also collapses runs of spaces. The Debord collection was
rebuilt with `add_parent_child_docs(rebuild=True)`: 854 child chunks (was 890). The previous index is kept at
`data/_backup_before_debord_reindex/`. **Why:** a defect. Plain extraction split words inside the text ("commod ity" in
34 chunks against 18 intact), so keyword search on those words failed. **Validated:** "commodity" went from 46 broken
occurrences to 2, and "spectacle" from 4 to 1. "represen tation" still appears 4 times. Augustine's collection was not
touched. **Open:** the 5 plain-fallback pages can still carry split words. `mcp_tools.py` calls
`add_parent_child_docs()` without `rebuild=True`, so a later loader change needs an explicit rebuild. Debord quotes in
older sessions come from the old index.

### 23. Both sides stored, with `side_is_target`

**Status: done, 2026-10-05 (uncommitted).** **What:** each bite keeps the full answer for both books, as before, and
adds `side_is_target`: per book, `true` or `false` for a tagged twin, `null` for an untagged query. The synthesis input
is unchanged from item 20. **Why:** a decision of the project owner. A clean quote from the non-target book (v5 query
2.1b) should stay available to the consumer. The synthesis keeps using the tagged side only.

### 24. Retrieval diagnostics per bite — `retrieval`

**Status: done, 2026-10-05 (uncommitted). Diagnostic, not a fix.** **What:** each bite stores `retrieval`: per book,
`label`, `reason`, and `lineage` (tool calls with their arguments and `forced_retriever`), taken from the final state
of `run_query`. **Why:** to inspect the `silent` and `miss` verdicts. The code has no numeric relevance threshold:
`silent` is the output of `reflect`'s LLM, guided by its prompt. **Validated:** not yet on a real run. Bites from v5
and v6 have no `retrieval` field.

### 25. Brief: vocabulary, twins, and known wording

**Status: done, 2026-10-05 (uncommitted).** **What:** `docs/claude_web_query_brief.md` now has: a vocabulary section
that is agnostic (match each book's own words; choose the query shape by what the books share; cautions about word
senses, inflections, and remembered quotations); a twin section that states what the stored result keeps and what the
synthesis receives; and a rule to quote the exact wording of a passage when that wording is known and matches the edition
in use. **Why:** v5 and v6 misses came from vocabulary and wording. In v6, passages quoted in their edition's wording came
back as hits, and scene descriptions came back as partial quotes. **Constraint:** the brief stays agnostic. Term-level
advice for a given book stays out of the file.

### 26. Synthesis cites bites by label, not by query text

**Status: done, 2026-10-06 (uncommitted).** **What:** `synthesize` takes `(label, query, answer)` triples. The
label is the batch label of the query (`1.1a`), and the prompt shows it as `[1.1a] Query: ...`. `based_on` and
`uncovered_angle.checked_bites` hold labels. `unknown_bite_ids` (`synthesis.py`) lists any cited label that was not
given, and `synthesize` raises `UnknownBiteLabelError` on one, so a stray id cannot pass silently. `run_theme_batches`
catches that error per thesis: the thesis file gets `synthesis_error` (and no `synthesis`), the bites are kept, and the
run continues. `consolidate_synthesis_file` carries `synthesis_error` into the consolidated file. Bites on disk keep their query
text; `load_bites` and `save_bite` are unchanged. **Why:** a defect. In v6 the model shortened a query when it wrote
`based_on`, so the claim no longer joined to its bite by string (evaluation S1). **Validated:** 3 offline tests
(`tests/test_synthesis.py`), a run test where a failing thesis is recorded and the next one still synthesizes, and the full suite (38 passing). Two real syntheses on v5 theses (one bite, and three bites):
every cited label was a known label. **Found on the first real attempt:** the model cited `Bite 6.1a`, copying the
prefix from the first rendering. The rendering was changed to the bare bracketed label and the prompt now says to cite
that label exactly. **Open:** existing `*_synthesis.json` files still hold query text; they are not re-synthesized, by decision.

### 27. Quote verification states why a quote fails

**Status: done, 2026-10-06 (uncommitted).** **What:** verification moved to `quote_check.py`. `normalize_text` folds
NFKC forms, case, whitespace, dash and quote variants, and drops soft hyphens (U+00AD) that the PDF leaves at line
breaks. `verify_quotes(answer, corpora, query)` returns, per book, a `status`: `verbatim`, `echo_of_query` (the quote
is the query itself), `differs_only_by_corpus_numbers` (matches once the corpus's bare thesis numbers are ignored),
`not_found`, or `no_quote`. A failed quote also carries `similarity`, `nearest` (the closest passage in that book's
retrieved chunks, one or two sentences) and `differences` (the first spans where quote and passage disagree). Each bite
stores `verification` beside the existing `verified`, which stays a boolean and is `true` only for `verbatim`.
**Why:** a defect. `verified: false` gave no reason, and the evaluation could not tell a real misquote from a
verifier false negative. Soft hyphens and dash variants caused false negatives; a quote equal to the query was accepted
as verified. **Validated:** 7 offline tests (`tests/test_quote_check.py`); the suite passes (43). Applied to the 9
quotes of v8 against the book's real paragraphs: 2 `verbatim`, 1 `echo_of_query`, 6 `not_found`. The 6 are real changes
in the quote (a changed "?" to ",", a paraphrase, a sentence cut short with a period added, an ellipsis joining two
passages), plus one corpus artifact (a PDF hyphen break, "state-t hat"). **Open:** a quote that echoes the query is
flagged, but quote selection is not re-run; the corpus's PDF hyphen breaks are not repaired; bites from v8 and earlier
have no `verification` field; `retrieval_query` (the search string actually sent) is not yet stored.

### 28. Quote matching: prefix and fragment; Debord text in plain order, with split words repaired

**Status: done, 2026-10-06 (uncommitted).** **What:** (a) `quote_check.py` compares quotes in a form where quote marks are
removed and the quote's trailing punctuation is ignored, on both sides of the comparison (`match_form`). Punctuation
inside the quote still counts. (b) Two new statuses: `prefix` (the quote opens a longer sentence) and `fragment` (the
quote sits inside one). Each carries `quote_full`, the whole sentence as written. Both count as verified, like `verbatim`.
(c) `ingest._pdf_pages` reads Debord in plain extraction order again. Plain order keeps the margin notes out of the body;
layout order merged them in, so 28 thesis numbers landed mid-sentence, against 1 in plain. Hidden hyphens are dropped,
split words are rejoined by `_join_split_words` (a fragment is joined when at least 90% of its occurrences form a word
found elsewhere in the text), and three splits are fixed by name in `KNOWN_PDF_SPLITS`. **Why:** (a) and (b) are the v9
false negatives: trailing punctuation, quote marks, and quotes cut short. (c) is a defect in the indexed text: the thesis
13 sentence sat inside thesis 3, and split words the rule cannot reach ("monolog ue") kept quotes from matching.
**Validated:** 49 offline tests (`tests/test_quote_check.py`, `tests/test_ingest.py`). Debord index rebuilt: 891 child
chunks, 83 parents. In it, the listed split words are gone, the only mid-sentence thesis number is a note reference
("40, 44, 47. survival"), and "its never-ending monologue of self-praise", "The social separation reflected in the
spectacle…", and "The moments within cyclical time…" are in the parent passages. **Open:** the automatic rule cannot
join a word whose whole form never occurs intact; `KNOWN_PDF_SPLITS` has to be extended by hand (a rule without a
dictionary joined "united states" and "few days"). Knabb's margin notes are still in the body text, as separate
passages. Quote selection still picks a neighbouring sentence, and an echoed quote is not re-selected. Backups of the
earlier indexes are in `data/_backup_before_debord_reindex/` and `data/_backup_before_desplit/`. Bites from v9 and earlier
were verified against the text they were produced with.

### 29. Quote selection: the sentence that shares the query's terms replaces the composer's neighbour

**Status: done, 2026-10-06 (uncommitted).** **What:** `select_quotes` (`quote_check.py`) runs in `run_theme_batches` before
verification. For each target book (the tagged side of a twin, or both books of an untagged query), the composer's quote
is replaced by the sentence of that book's retrieved chunks that shares the most query content terms, when that sentence
scores strictly higher. A term weighs more the rarer it is among the book's sentences. A replacement needs at least two
shared content terms (`MIN_SHARED_TERMS`). A quote that echoes the query scores lowest and is replaced by a real sentence,
never by the query. The composer's quote stays in the bite as `quote_selection.llm_quote`. The finding is not rewritten.
**Why:** D1. The retriever found the right passage, and the composer quoted a neighbouring sentence (v5 2.1a, v6 2.1a and
4.1a, v7 1.1a, v8 3.1c) or echoed the query (v7 2.1a, v9 2.1a, 3.1c and 5.1a). **Validated:** 56 offline tests
(`tests/test_quote_selection.py`). Replayed on the 15 v9 queries against the book paragraphs, with no LLM call: 5 quotes
replaced, all on target books, and verified quotes rose from 14 to 17. Examples: "Yet alone I had not done it:" (the echo
in 2.1a), "And behold, Thou wert within…", the full "dishes wherein" sentence, and the Triers and Emperor sentence. A first
version without the two-term minimum replaced a Debord quote on an Augustine query with an unrelated sentence, and the
non-target gate was added for that reason. **Open:** the rule is lexical, so it can pick a sentence that shares only
two generic terms; "For this queen of colours…" (replacing a colours passage) is plausible but not checked against the
book. The finding text is not rewritten, so it can still describe the composer's quote (D3). Bites from before this change
have no `quote_selection` and were not re-selected.

### 30. Evaluation harness

**Status: planned.** **What:** a LangSmith-hosted golden set (~10 targeted questions against Augustine/Debord,
including at least one question only one book addresses, to exercise `reflect`'s `"silent"` case), traced
automatically via LangSmith once the graph is instrumented, scored by two evaluators: faithfulness via
`ragas`/`deepeval`'s built-in metric, and a hand-built attribution metric (no off-the-shelf equivalent exists for
crediting a claim to one of two specific corpora). The comparison axis — chunk size vs. retriever preference via
docstring bias, or both — is deliberately left open, a per-run choice, not part of the harness's own design. **Why:**
comparing before/after the v2 changes would have a foreseeable outcome (the same reason v1-vs-v2 was
rejected); comparing configurations on the same version is a genuinely open question, so it's the comparison actually
worth running. **Synergy:** depends on item 9's run function; the faithfulness claim-decompose-then-judge-each-claim
pattern and the calibrate-before-trusting-the-judge methodology both carry over from researching a prior, unfinished
eval attempt in a sibling project, even though no code from it does.

### 31. Debord corpus moved from the annotated PDF to a plain EPUB

**Status: done, 2026-10-07 (uncommitted); both collections rebuilt locally.** **What:** B's source is now
`The_Society_of_the_Spectacle_(Knabb_2002)-Guy_Debord.epub` (same Knabb translation; checked against 6 passages
already verified from the PDF, word for word identical, including "parodies of real dialogue", never recovered
before). `catalog.py` points B at the new file. `_load_epub` (ingest.py) gained two changes used by both books:
`_block_text` drops a block that is only a bare number (this edition puts each thesis number in its own `<h3>`,
separate from its paragraph), and paragraphs are joined with a blank line instead of a single newline, so
`CharacterTextSplitter` (retrieve.py) has a break point inside a chapter — without it, a chapter with no blank
lines becomes one oversized, uncontrolled chunk. A third change, `NON_BODY_CHAPTERS`, drops chapters that are not
the author's own words (title page, contents, index, translator's note), the same reasoning as the editorial-notes
filter elsewhere: untagged non-authorial text risks being quoted as the author's. **Why:** D5 and more. The
annotated PDF interleaved Knabb's thesis-by-thesis endnotes into the body text (item 28); this EPUB has no such
endnotes at all (`cf.`, `quotation from`: 0 occurrences) and structurally separates the thesis number from its
paragraph, so the defect has no source to come from, instead of being filtered after the fact. **Validated:** 70
offline tests (3 new in `tests/test_ingest.py` for `_block_text`/`_is_non_body_chapter`). Loader output for B: 10
chapters (was 14 before the chapter filter), zero split-word or bare-mid-sentence-number occurrences outside of
three real dates inside Debord's own quoted epigraphs. All 6 known passages are present in the rebuilt parent
chunks, and a real ensemble-retrieval query returns "opposite of dialogue" in its top results. **Open:** the
paragraph-join fix applies to `_load_epub` generally, so A was also rebuilt for consistency (1788 children,
unchanged — the fix had no effect there). Child chunks for B are coarser than the 400-character target for any
single thesis-paragraph longer than that on its own (median 680, up to ~3100 characters for one long, coherent
paragraph) — `CharacterTextSplitter` keeps a real paragraph whole rather than cutting it, which items 13/14 already
accepted as the chosen tradeoff, but this makes the effect more visible for B than it was from the PDF's
page-driven line breaks. The survey's B outputs (`data/survey/B/`, `summary.json`, and the B embeddings cache) were
removed as stale, since they were built from the old text; they need a fresh run. The edition is Ken Knabb's 2002
translation; the title page does not say "2014" or "Annotated" — the wording match suggests the 2014 annotated
edition is the same translation with notes added, not a different revision, but that is an inference from this
sample, not confirmed from a source. Backup of the pre-migration index: `data/_backup_before_epub_migration/`.

### 32. `synthesize()` disabled — its own bar, tested and not met

**Status: done, 2026-10-07 (uncommitted).** **What:** `run_theme_batches` no longer calls `synthesize`,
`save_synthesis`, or `save_synthesis_error`. A session's thesis files carry only their bites; no `synthesis` or
`synthesis_error` key is written. The return value of `run_theme_batches` is `consolidate_thesis_file`'s output
(`<timestamp>_thesis.json`), not `consolidate_synthesis_file`'s. `synthesis.py`, `consolidate_synthesis.py`, and
`restrict_to_side` (theme_batches.py) are kept, unused, rather than deleted. **Why:** item 12 set its own bar at
the time it was built — "manual-first by design — automatic chasing is deliberately deferred until the manual
version proves useful" — and nine evaluation rounds (v3-v9) are the test of that bar. The result: `claims` and
`candidate_query` were never quoted or acted on (the citation bank and every query decision came from reading
`thesis.json`'s bites directly); `uncovered_angle` repeatedly claimed a gap that the bites already covered
(crowd, Debord's self-recognition passage, a secular book's "silence" on sin treated as a gap); `agreement`/
`disagreement` were templated and leaked between queries (S1-S5, sections 5 and 15 of the evaluation). The
vocabulary problem `synthesize` was partly meant to compensate for is now being addressed upstream, by the
survey/translation work, which narrows its would-be job further without making its own reasoning defects go
away. **Validated:** suite passes, 69 tests (was 70; the test exercising `UnknownBiteLabelError` end to end through
`run_theme_batches` was removed, since that path no longer runs — `tests/test_synthesis.py` still tests
`unknown_bite_ids` directly, since `synthesis.py` itself is unchanged).
**Open:** two replacements were discussed and not chosen yet: keeping only a (separately validated) gap-check,
or a mechanical gap-check built on the survey's discovery/reference-set machinery instead of an LLM judgment.
`README.md` and this file's own item 17 text were annotated, not rewritten, to point here.

### Backlog (deferred, not dropped)

Currently empty — era-annotation and quote-extraction, the only two entries previously here, were promoted into the
sequenced v3 items above (7 and 8).

## Out of scope here

**RAG-Tetris** (comparing a language feature's evolution across versions, e.g. Python's GC or type system across
releases) is a separate future project, built elsewhere, not in this directory. If a design choice here ever has to pick
between what's best for this project and what would ease future sharing with RAG-Tetris, this project wins — Tetris gets
addressed when it actually starts.
