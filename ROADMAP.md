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
  thesis (item 12, committed), then a proper test suite (item 16), then a theme parser (item 17), then the evaluation
  harness (item 30). Items 13-15 are the retrieval and silent-verdict fixes built after item 12 was committed; items
  18-29 are the session, brief, twin-query and quote-verification work the theme batches turned out to need; item 31
  moved the Debord corpus to a plain EPUB, and items 32, 34 and 35 discontinued the synthesis layer, the vocabulary
  pre-flight (item 33) and the data they left behind. The synthesis layer was always its own version — a distinct
  capability layered on top of a finished, tested two-book comparison system; the test suite and eval harness moved
  here from v3 since v3's own completion no longer waits on them, and now land after the synthesis layer so they cover
  it too. Items 36-43, next up, are the handoff between this system and the side that writes the queries and the
  ideas: bite identity, verification against the book, the witness-view export, a rejectable standard for idea units,
  the `ok` and `silent` labels, and a falsification round; item 41 closed 2026-10-11 with the `silent` split landed
  and the false `ok` diagnosed as a task problem, and item 44 carries that fix. Items 45-46 are instrumentation and
cost: a run record that states which model ran which role, the one gpt-4o role whose spend justifies moving to
DeepSeek (the attribution judge), and E re-measured in the configuration it actually runs in. See "v4 — after v3 is
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

**Status: discontinued 2026-10-08 (see item 34) — the synthesis layer and its session files were removed; the one sub-part that survived, composer keeping settled findings, landed 2026-10-04 (below).** **What:** a standalone, non-graph function
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

**Status: done, validated, 2026-10-05.** **What:** `make_bm_25_retriever`
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
`/consolidate-session <session folder>` (`.claude/commands/`) runs it (both removed in item 34). Slugs are generated by the system from the theme title (lowercase, accents stripped, spaces to hyphens, capped
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

**Status: done, 2026-10-05.** **What:** `consolidate_thesis_file(session_dir)`
(`ParallelProse.consolidate_thesis`, run as `python -m ParallelProse.consolidate_thesis <session folder>`) writes
`<timestamp>_thesis.json` at the session root. It holds `session`, then `books` (letter to title, from the session's
`manifest.json`), then `theses`: one entry per thesis file, carrying `theme_folder`, `file`, and the thesis file's full
contents (`theme`, `thesis`, `bites`, `synthesis`). **Why:** the thesis file is the only file with quotes; the flat
layout gives one place to read a whole session's evidence. **Tests:** `tests/test_consolidate_thesis.py`.

### 19. Synthesis consolidator renamed to `consolidate_synthesis`

**Status: done, 2026-10-05; removed 2026-10-08, see item 34.** **What:** `consolidate.py` became `consolidate_synthesis.py`, and
`consolidate_session` became `consolidate_synthesis_file`. The output is unchanged (`<timestamp>_synthesis.json`).
Updated: `theme_batches.py`, the test file (now `tests/test_consolidate_synthesis.py`), the README, the
`/consolidate-session` command, and the item 17 text. **Why:** the module name now matches the thesis consolidator
(item 18), so the two outputs are easy to tell apart.

### 20. Twin queries — side tag in the batch format

**Status: done, 2026-10-05.** **What:** a query line may carry a book tag between its letter and the
colon: `Query N.Ma[A]:` or `Query N.Ma[B]:`. `parse_batch` reads the tag into the query tuple, outside the query text
sent to retrieval, and rejects a tag that is not a key of `CATALOG`. Before synthesis, `restrict_to_side` keeps only the
tagged book's unique findings and blanks the shared `agreement` and `disagreement`; untagged queries pass through
unchanged. **Why:** a query worded in one book's vocabulary fits that book only, so the other book's answer was noise
in the synthesis of its thesis. **Validated:** parser and synthesis-input tests (`tests/test_theme_batches.py`). Sessions
v5 and v6 ran with this filter active.

### 21. Quote verification — `verified` per book

**Status: done, 2026-10-05.** **What:** `verify_quotes` (now in `quote_check.py`, see item 27) stores `verified` on every
bite: for each book, `true` if its quote appears in that book's retrieved chunks, `false` if not, `null` if the book has
no quote. Whitespace and case are ignored. **Why:** a defect. Quotes come from the composer's LLM with no check, and
in v5 only 3 of 10 Debord quotes appeared verbatim in the source text (4 had joined spans with ellipses, 3 were not
in the text, 1 differed only in spacing; Augustine 9 of 13). **Validated:** two offline tests. **Open:** the check
runs against the retrieved chunks, not the source text, and a truncated quote still passes as a substring. Bites from
v5 and v6 have no `verified` field.

### 22. Debord PDF: layout extraction and reindex

**Status: done, 2026-10-05; Debord collection rebuilt locally.** **What (its layout-mode reading is superseded by item 28):** `_pdf_pages` (`ingest.py`)
replaces `PyPDFLoader` for the PDF branch. It reads each page in pypdf's layout mode and falls back to plain extraction
when layout mode raises `IndexError` (5 pages in this PDF). It also collapses runs of spaces. The Debord collection was
rebuilt with `add_parent_child_docs(rebuild=True)`: 854 child chunks (was 890). The previous index is kept at
`data/_backup_before_debord_reindex/`. **Why:** a defect. Plain extraction split words inside the text ("commod ity" in
34 chunks against 18 intact), so keyword search on those words failed. **Validated:** "commodity" went from 46 broken
occurrences to 2, and "spectacle" from 4 to 1. "represen tation" still appears 4 times. Augustine's collection was not
touched. **Open:** the 5 plain-fallback pages can still carry split words. `mcp_tools.py` calls
`add_parent_child_docs()` without `rebuild=True`, so a later loader change needs an explicit rebuild. Debord quotes in
older sessions come from the old index. *Closed: B loads from an EPUB since item 31; the PDF repair code and the
backups were removed in item 35.*

### 23. Both sides stored, with `side_is_target`

**Status: done, 2026-10-05.** **What:** each bite keeps the full answer for both books, as before, and
adds `side_is_target`: per book, `true` or `false` for a tagged twin, `null` for an untagged query. The synthesis input
is unchanged from item 20. **Why:** a decision of the project owner. A clean quote from the non-target book (v5 query
2.1b) should stay available to the consumer. The synthesis keeps using the tagged side only.

### 24. Retrieval diagnostics per bite — `retrieval`

**Status: done, 2026-10-05. Diagnostic, not a fix.** **What:** each bite stores `retrieval`: per book,
`label`, `reason`, and `lineage` (tool calls with their arguments and `forced_retriever`), taken from the final state
of `run_query`. **Why:** to inspect the `silent` and `miss` verdicts. The code has no numeric relevance threshold:
`silent` is the output of `reflect`'s LLM, guided by its prompt. **Validated:** not yet on a real run. Bites from v5
and v6 have no `retrieval` field.

### 25. Brief: vocabulary, twins, and known wording

**Status: done, 2026-10-05.** **What:** `docs/claude_web_query_brief.md` now has: a vocabulary section
that is agnostic (match each book's own words; choose the query shape by what the books share; cautions about word
senses, inflections, and remembered quotations); a twin section that states what the stored result keeps and what the
synthesis receives; and a rule to quote the exact wording of a passage when that wording is known and matches the edition
in use. **Why:** v5 and v6 misses came from vocabulary and wording. In v6, passages quoted in their edition's wording came
back as hits, and scene descriptions came back as partial quotes. **Constraint:** the brief stays agnostic. Term-level
advice for a given book stays out of the file.

### 26. Synthesis cites bites by label, not by query text

**Status: done, 2026-10-06.** **What:** `synthesize` takes `(label, query, answer)` triples. The
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
that label exactly. **Open:** existing `*_synthesis.json` files still hold query text; they are not re-synthesized, by decision. *Moot: synthesis was removed in item 34.*

### 27. Quote verification states why a quote fails

**Status: done, 2026-10-06.** **What:** verification moved to `quote_check.py`. `normalize_text` folds
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

**Status: done, 2026-10-06.** **What:** (a) `quote_check.py` compares quotes in a form where quote marks are
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
were verified against the text they were produced with. *Closed: the PDF notes by item 31 (EPUB, no margin notes),
quote selection by item 29; the split-word code and these backups were removed in item 35.*

### 29. Quote selection: the sentence that shares the query's terms replaces the composer's neighbour

**Status: done, 2026-10-06.** **What:** `select_quotes` (`quote_check.py`) runs in `run_theme_batches` before
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

**Status: done 2026-10-12 (the harness is built and available).** 30.1 done 2026-10-09 (the 16-entry golden set passes
every `load_golden_set` check); 30.2 done 2026-10-09 (`answer_query` shared with
`run_theme_batches`, `run_golden_entry` returns a bite plus `id` and per-book `chunks`; one live run of g01 checked);
30.3 done 2026-10-09 (`anchor_hits`, `label_agreement`, and the
two LLM judges in `judges.py`), judges calibrated against 27 hand-labelled findings from the first full run:
faithfulness agrees 27/27; attribution 26/27 after its prompt was changed to decide by the idea a finding states, not
by shared words (it answered "both" on vocabulary overlap; g05 A remains, a finding that borrows the other book's
word "spectacle"). First-run findings, one run only: every one of 6 disagreeing labels is a false `ok` (a book
expected silent labelled `ok`), 26 of 27 findings claim more than their quote (D3), and 3 of 4 wrong-passage quotes
came from `select_quotes`' lexical replacement (item 29). 30.4 in progress: 30.4.1 `push_golden_set` done
2026-10-10 (the 16 entries are the LangSmith dataset `golden-augustine_debord-e90f8206`, each entry split into
inputs / reference outputs / metadata; the name carries a hash of the entries, so an unchanged push reuses the
dataset and an edited golden set gets its own, leaving old experiments comparable). 30.4.2 `anchor_hits` and the
other adapters done 2026-10-10: `golden_target(inputs)` plus one evaluator per metric, each a wrapper over the
functions above, which keep their signatures and stay callable without LangSmith. One key per book per metric
(`anchor_hits_A`, `label_agreement_B`, ...), since LangSmith averages per key and a shared key would merge the two
books; a book with nothing to answer omits its key rather than scoring 0; the per-book detail (missing anchors, the
expected/final pair) rides along in each result's `comment`. `EVALUATORS` (deterministic, free) is kept apart from
`JUDGES` (one judge-model call per judged book) so a configuration sweep can skip the paid calls.
`run_golden_entry` now delegates to `run_golden_query(id, query, side)`, so the target can work from an example's
inputs alone. 30.4.3 `run_experiment` done 2026-10-10: it pushes (or reuses) the dataset, calls `aevaluate` with
`golden_target` and the chosen evaluators, `num_repetitions=3` and `max_concurrency=2` (every example shares the one
MCP server `run_query` starts per process and one model rate limit; a throttled example lands as a low score, not a
crash), and stores in the experiment's metadata the configuration read from the live objects — `configuration()`
takes the four splitter settings per book from `mcp_tools.REGISTRY` and both model names, never a typed label — plus
the `judges` flag and the dataset name. CLI: `python -m ParallelProse.evaluation [--run] [--judges] [--repetitions N]
[--concurrency N]`. **No local per-book/per-cell summary:** LangSmith's UI gives the per-key averages and filters by
each example's metadata (`specificity`, `wording`, `known_failure`), so E1's cells are read there (decided
2026-10-10). **Open:** no experiment has been run yet; `LANGSMITH_TRACING` is kept false while building and turned on
for the experiment command, so each score has its graph trace behind it. **Watch when varying chunk size:**
`add_parent_child_docs` (retrieve.py:91) decides whether to rebuild by comparing chunk *counts*, not the chunks
themselves, so a new `chunk_size` that happens to yield the same count would keep the old embeddings while
`configuration()` records the new setting — pass `rebuild=True` once, or check the count actually moved. (The
repeated `Created a chunk of size ... longer than the specified 400` lines come from that counting re-split, not from
re-embedding; kept visible on purpose as a reminder of the paragraph-keeping tradeoff from items 13/14/31.) **What:** four functions, each built in order, each one's output the next one's input:

- **30.1 Golden set** — `data/golden_set_augustine_debord.json`, written by Claude web from the brief
  `docs/golden_set_spec.md` (which carries a complete example of the file) and read by `load_golden_set` (new module
  `evaluation.py`). The standard: exactly 16 entries; per book, an expected label
  (`ok`/`silent`), with verbatim `anchors` and `min_hits` for an `ok` book (one anchor for a single-passage answer,
  several for a scattered one) and `absent_terms` plus a `near_miss` flag for a `silent` one. Entries are written
  passage-first, and the set must cover label combinations, four retrieval cells per book (single/scattered ×
  specific/abstract), book wording vs. paraphrase, known failures, and at least 8 themes. The loader rejects the file,
  before any run, when an entry or the set's composition breaks the spec. The first two known-failure entries are the
  "Anon, anon" and "restless" misses in Augustine.
- **30.2 Target** — runs one golden query the way `run_theme_batches` does (`run_query`, `select_quotes`,
  `verify_quotes`, with the entry's `side`) and returns the record the evaluators read.
- **30.3 Evaluators** — anchor hits against the chunks retrieved per book, and label agreement, both deterministic;
  plus faithfulness and attribution, as LLM judges calibrated against hand labels before being trusted. Whether a
  quote exists in the book is already checked deterministically by `verify_quotes`, so faithfulness judges only
  whether a finding claims more than its quote shows (D3): the finding is split into claims, each judged against the
  quote alone. Attribution is hand-built: no off-the-shelf metric credits a claim to one of two specific corpora. The
  judge sees both books' retrieved passages unnamed, in an order fixed per entry and book, and the finding with the
  authors' names replaced by "the author" (findings name their author, which would let the judge answer from the
  name). Both judges run on `gpt-4o`, not the system's `gpt-4o-mini`. `judge_records` writes their verdicts beside
  empty hand-label fields (`data/eval/calibration_*.json`); `judge_agreement` measures agreement once those are filled.
- **30.4 Runner** — a LangSmith experiment over the golden set, one configuration per run, repeated, since the same
  configuration can flip a question between runs. LangSmith is not yet a dependency. The comparison axis — chunk size
  vs. retriever preference via docstring bias, or both — is a per-run choice, not part of the harness's design.

**Why:**
comparing before/after the v2 changes would have a foreseeable outcome (the same reason v1-vs-v2 was
rejected); comparing configurations on the same version is a genuinely open question, so it's the comparison actually
worth running. **Synergy:** depends on item 9's run function; the faithfulness claim-decompose-then-judge-each-claim
pattern and the calibrate-before-trusting-the-judge methodology both carry over from researching a prior, unfinished
eval attempt in a sibling project, even though no code from it does.

### 31. Debord corpus moved from the annotated PDF to a plain EPUB

**Status: done, 2026-10-07; both collections rebuilt locally.** **What:** B's source is now
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
sample, not confirmed from a source. Backup of the pre-migration index: `data/_backup_before_epub_migration/` (removed in item 35, with the rest of
`data/survey/`).

### 32. `synthesize()` disabled — its own bar, tested and not met

**Status: done, 2026-10-07.** **What:** `run_theme_batches` no longer calls `synthesize`,
`save_synthesis`, or `save_synthesis_error`. A session's thesis files carry only their bites; no `synthesis` or
`synthesis_error` key is written. The return value of `run_theme_batches` is `consolidate_thesis_file`'s output
(`<timestamp>_thesis.json`), not `consolidate_synthesis_file`'s. `synthesis.py`, `consolidate_synthesis.py`, and
`restrict_to_side` (theme_batches.py) are kept, unused, rather than deleted (deleted later, in item 34). **Why:** item 12 set its own bar at
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
*Decided in item 34: nothing replaces it; the survey design is in the Backlog.*
`README.md` and this file's own item 17 text were annotated, not rewritten, to point here.

### 33. Per-book vocabulary: a static index, a reference document, and a free pre-flight check

**Status: done, 2026-10-07; removed 2026-10-08, see item 34.** **What:** new module `src/ParallelProse/vocabulary.py`, decoupled from
`survey.py` on purpose — `survey.py`'s concern is whether a theme is covered, this module's is whether one exact
word exists. `build_vocabulary(cid)` tokenizes `load_corpus`'s text directly (no embedding, no LLM); `save_vocabulary`
/`load_vocabulary` persist it to `data/vocabulary/<book>.json`; `lookup(term, vocabulary)` returns exists/count, and
when absent, the book's own nearest real spellings (`difflib`, never an external dictionary). `distinctive_words`/
`write_reference_document` render the 200 most frequent content words (stopwords dropped) to
`data/vocabulary/<book>_reference.md`, meant to be handed to Claude web whole, before it writes a query. A second
piece, `vocabulary_report` (`theme_batches.py`), reads a batch file's text alone — not the pipeline, not an LLM —
and flags each query's content words absent from its target book(s), with the book's nearest real word; a tagged
twin query is checked only against its own book, an untagged one against both. CLI: `python -m ParallelProse.
vocabulary <book> [terms...]` (no terms: rebuilds the index and the reference doc) and `python -m
ParallelProse.theme_batches --check <batch.md>`. **Why:** raised by Claude web, discussed with the user, who
rejected any protocol where Claude web asks a word-by-word question relayed by the user ("garimpo") — not a
fallback, off the table entirely. The real split is: a document handed over before any query (this item's
reference doc), and, when Claude web still writes a word the book does not have, whether the correction is cheap
(this item's mechanical report) or expensive (an LLM rewrite — `translate.py`, designed, not built). **Validated:**
80 offline tests (`tests/test_vocabulary.py`, `tests/test_theme_batches.py`). Indexes and reference docs built for
A and B (203 lines each). `--check` run on a real past batch (v6, `2026-10-05_2153/source.md`) caught the actual
"Ponticianus" misspelling from that round, suggesting "pontitianus" (the book's real spelling, 4 occurrences) — the
same fix that took a full evaluation round to surface, now free, instant, and before any query is submitted.
**Open:** the per-theme half of the vocabulary lag (vocabulary discovered while surveying a theme, exposed as soon
as that theme's first query is processed, not only at the end of a whole batch) still needs the automatic-discovery
survey to exist; `translate.py`'s LLM rewrite is still not built. *Moot: removed in item 34; survey and
translation are in the Backlog.*

### 34. Discontinued: the vocabulary pre-flight, the synthesis layer, and the off-target idea

**Status: done, 2026-10-08.** **What:** removed `vocabulary.py` (the per-book index,
`<book>_reference.md`, `lookup`), the `--check` pre-flight (`vocabulary_report`, `flagged_words`), `synthesis.py`
(`synthesize`, `Synthesis`, `unknown_bite_ids`, `load_bites`, `save_synthesis`, `save_synthesis_error`),
`consolidate_synthesis.py`, the `/consolidate-session` command, and `restrict_to_side`, with their tests and README
sections; `data/vocabulary/` deleted. `save_bite` moved into `theme_batches.py`, its only caller. The `off_target`
label proposed in the open-items list is dropped before being built. Suite: 63 tests passing (was 80).

**Why — the vocabulary pre-flight (item 33).** Measured offline on all 118 historical queries (v3-v10), no LLM call:

- The flag rate had already collapsed before item 33 existed: v3 and v4 hold 78 of the 86 flags, v5-v10 hold 8 across
  52 queries. The drop lines up with the brief's vocabulary section (item 25) and with Claude web quoting passages in
  the edition's own wording.
- 1 of the 86 flags was a real defect ("Ponticianus", v6). The rest are words the book does not use, or inflections
  the exact-form index cannot match (`persuasion`/`persuasions`, `happens`/`happen`). No spelling-similarity threshold
  separates the one catch from the noise: the inflections score highest.
- Flags against outcomes: on the declared target side, flags show no relation to `silent` or `miss`. An apparent
  8x link (12.8% vs 1.0% silent) came from bites that predate `side_is_target` (item 23): 9 of its 10 silent cases
  were the non-target side of `[A]`-tagged twins.
- `<book>_reference.md` lists the 200 most frequent words, so it lacks exactly the rare, scene-specific words a
  targeted query depends on. Handing over the full word list instead trades that for exact-match lookups by the
  model, which fail silently and get worse as a corpus grows.

**Why — off-target.** Already handled by twin tagging (item 20): Claude web declares the side. What remains is D8, the
pipeline still running and retrying the non-target side of a tagged query — a pipeline fix that reads the tag, not a
detector.

**Why — the synthesis layer.** Item 32 disabled `synthesize()` and kept its code unused; parked code goes. Older
sessions keep their `synthesis` key on disk, and `consolidate_thesis_file` still carries it through, but nothing reads
it in code.

**Open:** `docs/claude_web_query_brief.md` still describes `synthesize` as a live step, left as is by decision for
now. The survey/translation design moves to the Backlog below.

### 35. Housekeeping: superseded data and the PDF split-word repair

**Status: done, 2026-10-08.** **What:** deleted the three index backups (`data/_backup_before_debord_reindex/`,
`_backup_before_desplit/`, `_backup_before_epub_migration/`, 116 MB), `data/survey/` (172 MB of survey outputs and
embedding caches, rebuilt from scratch whenever the survey is), and the annotated Debord PDF that B no longer loads
from. In `ingest.py`, `_join_split_words`, `KNOWN_PDF_SPLITS` and their two tests are gone; the plain PDF branch
stays (page text, soft hyphens dropped, chapters from the outline), since no catalog book is a PDF today but the
Portuguese Debord in `data/` is one. Suite: 61 tests passing. **Why:** all of it served the annotated PDF or
indexes that items 28 and 31 replaced; `survey.py` itself is kept (see Backlog).

### 36. Bite identity: a content-addressed `bite_id`

**Status: done (2026-10-11).** **What:** every bite gains a `bite_id` derived from its own content — the pair, the corpus id
and the quoted span — written by `save_bite` (`theme_batches.py:72`) and carried through `consolidate_thesis_file`.
Never derived from the session folder or from the bite's position inside the file. **Why:** bites have no id at all
today: a bite is addressed by session timestamp plus position in `<timestamp>_thesis.json`, so a reindex that moves a
passage into another chunk, or a session file rebuilt after an edit, silently repoints every reference to it.
**Synergy:** prerequisite for item 39's export, which is addressed by id, and for item 40's `Ancoragem`, which only
survives a reindex if the id is content-addressed.

### 37. Quote verification runs against the book, not only against the retrieved chunks

**Status: done (2026-10-11).** **What:** `verify_quotes` (`quote_check.py:62`) gains a second pass. A quote no retrieved chunk
contains is looked up in the book's own text — `load_corpus`, the same source `_book_paragraphs` reads
(`evaluation.py:191`) — under two new statuses: one for text the book contains outside the retrieved chunks, one for
text the book does not contain. Two matching repairs ride along: a quote-mark character `QUOTE_MARKS`
(`quote_check.py:11`) does not fold, and sentence-internal punctuation, which `TRAILING_PUNCTUATION`
(`quote_check.py:12`) ignores only at the quote's end. `VERIFIED_STATUSES` (`quote_check.py:14`) and `verified_flags`
(`quote_check.py:157`) decide which new status counts as verified.

**Why:** measured over every session on disk — 26 bites carry `verified: false`. 11 come from sessions older than item
27 and have no recorded cause; of the 12 that do, roughly 4 are a quote whose tail falls outside the retrieved chunks,
2 are the matching gaps above, 3 are non-contiguous joins (D2, correctly rejected) and 2 are a word the model inserted
(correctly rejected). Checked against the corpora: `give me chastity and continency, only not yet` and `held down
pleasantly, as in sleep` each occur once, contiguous, in A, and `what appears is good` once in B — text the books
contain that the current check calls `not_found`, because it only ever searched the retrieved chunks. The same check
settles the other direction: `the spectacle is the opposite of dialogue` has 0 occurrences in B, whose text reads `It
is the opposite of dialogue.`, so that quote's `verified: false` was correct and the citation bank's wording is a
reconstruction. **Synergy:** this is what makes item 40's `Ancoragem` rule enforceable without a human re-check
ledger: existence gets demonstrated the way `_book_problems` (`evaluation.py:203`) already demonstrates it for
golden-set anchors.

**Built as:** the book-level pass landed as a new `found_in_book` status (quote absent from the retrieved chunks,
present in the book — a retrieval gap, not an invention), reached only when the chunk-level checks already fail.
`book_paragraphs` moved from `evaluation.py` down into `quote_check.py` (cached, so a session reparses each epub
once, not once per query) and `evaluation.py` now imports it. Of the two matching repairs: the trailing-punctuation
one (the "as in sleep." / "as in sleep:" case) was reproduced against the real saved session and found **already
fixed** by the current `TRAILING_PUNCTUATION` regex — locked in with a regression test, no code change needed. The
quote-mark-folding repair was **not built**: every non-ASCII punctuation character in both full books and in every
model-generated quote across every saved session was enumerated, and none falls outside what `PUNCTUATION_MAP`
already folds — there is no observed failure to fix. Revisit only if one surfaces.

### 38. Edition metadata per corpus

**Status: done (2026-10-11).** **What:** `Book` (`catalog.py`) gains translator, year and publisher — A is Pusey, B is Knabb
2002, the wording item 31 established for the text that had been catalogued as "2014 Annotated" — carried into the
session's `manifest.json` and into item 39's export. **Why:** already on the open-items list for the credit line, and
now a dependency rather than a nicety: the edition decides what may cross over to a script, so it has to travel with
the quote instead of living only in the catalog. **Synergy:** needed by item 39; independent of the rest.

### 39. The witness view: one export per session, quotes with provenance

**Status: done (2026-10-11).** **What:** a function that reads a session's `<timestamp>_thesis.json` and writes
`witness_view_<project>_<session>.json`, one record per book per query: `bite_id`, session, query code and query text,
`corpus_id`, edition, `retrieval` (label, `side_is_target`, `forced_retriever`, lineage), the quote, the whole
`verification` object, `quote_selection`, and the finding in a block of its own, after the quote. It never carries
`agreement`, `disagreement`, `needs_revision` or anything derived from them, never a quote for a book labelled
`silent`, and never `verification.nearest` under the `quote` key. A `context_window` of one or two sentences either
side of the quote, cut from the book's text, belongs to this record.

**Built as:** `src/ParallelProse/witness_view.py` (`build_witness_view`), called from `run_theme_batches` right
after `consolidate_thesis_file`. Two gaps surfaced while building, not in the original text: the query's own code
(`"1.1a"`) was being discarded in the batch loop — `save_bite` now takes and stores it as `"code"` — and no
function cut human-readable text from the book (`book_paragraphs` only returns `match_form`-normalized text for
matching). `context_window` (new, in `quote_check.py`) solves that, backed by a raw-paragraph/sentence cache
sharing the same parsed epub as `book_paragraphs` (`_chapters`, cached). `reason` is left out of the `retrieval`
sub-object (not in the given field list); everything else follows the spec as written. One real bug caught before
it shipped: the first `context_window` draft matched sentences by substring containment, which let a short quote
trivially match tiny over-split sentence fragments throughout the whole book, returning most of it as "context" —
fixed by locating the quote's character span in the joined book text instead (the same substring-search style
`book_paragraphs`/`verify_quotes` already use), confirmed against the real "chastity" quote (now returns one
sentence before and after, ~800 characters, not 400KB). 109/109 tests pass.

**Why:** the comparison fields are a hypothesis the reader cannot un-see, and this file's reader is the side whose job
is to produce the comparison — handing over the system's own reading of convergence anchors that work to it. They are
also the only fields in the output no evaluator scores, and `route_after_reflection` (`agent.py:364`) never reads
`needs_revision`, so nothing in the graph depends on them leaving. `verification` travels whole because the boolean
alone cannot separate a punctuation miss from an echo of the query: 3 bites on disk carry `status: "echo_of_query"`,
and 8 of the 16 records in `data/eval/records_2026-10-09_2050.json` had their quote replaced by `select_quotes`, which
the boolean hides too. The window is cut from the book rather than from the parent chunk because a parent carries 100
characters of overlap (`retrieve.py:47`), so a sentence split at the seam is not recoverable from it.

**Scope:** this file feeds query and theme work only. It is not a copyright firewall — it exists to carry the quote —
and it never goes to a session writing a script, which reads item 40's output instead.

**Synergy:** needs items 36 and 38. Its field list is specified by the side that consumes it, the same arrangement
that made the golden set land on the first try (item 30.1).

### 40. Idea units: a spec and a validator

**Status: done (2026-10-11).** **What:** `docs/idea_unit_spec.md` plus `load_idea_units` in a new module, built the way item
30.1 was — the spec carries one complete example, and the loader rejects the file before anything reads it. The rules:

- `tipo` is one of convergence, divergence, single voice, false positive. Four, not three: a pair whose shared
  mechanism is real and whose outcome differs is neither a convergence nor a false positive.
- `Ancoragem` is a list of `bite_id`, never quoted text, and every id's bite must pass item 37's book check.
  Validated with `_phrase_pattern` (`evaluation.py:26`), the matcher `_book_problems` already uses, so the rule needs
  no human countersignature.
- A signature-word list per side, tested as cross-contamination — a term belonging to one book appearing in a unit
  anchored entirely in the other — raised as a flag, not a rejection, since a genuinely cross-book unit must name
  both vocabularies.
- A falsification test phrased as a batch query with its target side declared, and a separate field for a single-voice
  unit, which has no target side.
- Promotion reads a registered null search (term, side, corpus, date) and a named decider. It never promotes because
  retrieval came back empty.

**Why:** the measured asymmetry is that the system's output has a rejectable standard and the idea layer has none, and
the golden set is this project's own evidence that writing the standard first is what makes the material land on the
first try. Calibration cases, all already in hand: a quote the current check rejects and the book contains (item 37);
`g05`, whose A-side finding borrows B's word "spectacle" and is the attribution judge's only disagreement in 27;
`g08`, a known failure whose run returns the wrong passage for a query worded from the book; `g09`, where B is
`silent` with `near_miss: true` on a pair the citation bank rates highly, which the taxonomy has to adjudicate as a
divergence of axis or a false positive. **Synergy:** depends on items 36 and 37; its output is the only file a
script-writing session reads, which is what puts the quotes out of reach rather than merely off-limits.

**Built as:** `src/ParallelProse/idea_units.py` (`IdeaUnit`, `load_idea_units`, `build_bites_index`) +
`docs/idea_unit_spec.md`, mirroring `evaluation.py`'s `GoldenEntry`/`load_golden_set` structure. Field names and
enum values are English (`type`, `anchoring`, `mechanism_a/b`, `form_a/b`, `shared_structure`, `divergence_axis`,
`falsification_test`), not the original proposal's Portuguese — confirmed with the user, since the roadmap's own
`tipo`/`Ancoragem` backticks were quoting the source proposal, not mandating the schema's language. `anchoring`
resolves against a `bite_id -> {corpus_id, quote}` index built by scanning every `witness_view_*.json` under a
project's sessions (item 39's output), then re-run through `_phrase_pattern` against `book_paragraphs` — the same
check `_book_problems` runs for golden-set anchors, independent of the bite's own stored `verification.status`.
The signature-word cross-contamination list is a small hardcoded dict (confirmed with the user it isn't a revival
of item 34's removed vocabulary system — different scope, flag-only, never rejects). `promotion` ships as a
structurally-validated optional skeleton (`decider`, `null_search_ref`, `date`); cross-checking it against a real
null-search registry is item 43's job. Verified end-to-end against the real book and the real "chastity" quote
(item 37's own example): a unit anchored to it is accepted, and corrupting the indexed quote text is rejected with
`not found in book A`. 125/125 tests pass.

### 41. `ok` defined, `silent` split, and the false `ok` diagnosed

**Status: closed (2026-10-11) — the split and the definition landed, the false-`ok` cause was measured, and the fix
moved to item 44.** **What:** three steps, in order. Write down what `ok` asserts — that this book answers the
query, not that the query's subject appears in it — in `CorpusCritique.label`'s description (`agent.py:53`). Then fix
the disagreement that measures: in the first full golden-set run, 6 of 32 labels disagree with the golden set, and
every one of the 6 is a book expected `silent` and labelled `ok` (g07 B, g09 B, g10 B, g11 B, g13 A, g15 A). Then
split what `silent` covers today — absence in the book, a retrieval miss, the non-target side of a twin — and only
then promote genuine absence to an editorial category.

**Why:** `label_agreement` already scores this field, so the fix is measurable the day it lands. Promoting `silent`
before the split imports the error: of the 12 silent verdicts in the history, 9 were the non-target side of a tagged
twin. **Synergy:** feeds item 40, whose single-voice type is populated from genuine absence; independent of items
36-39.

**Built as:** step 3 landed and works: `CorpusCritique` gains `silence_cause` (LLM-judged `adjacent_topic`/`absence`,
only when `label == "silent"`), threaded through `CorpusState`, with `theme_batches.resolve_silence_cause`
deterministically overriding to `non_target_twin` when `side_is_target[cid] is False` — the critique LLM never sees
`side`, so that override lives outside the graph. Step 1 landed as the definition above. Step 2 did **not**, and the
measurement says it could not have, in that place: two prompt rewrites moved zero labels, and **neither temperature
nor model moves them either** — the C control ran the six entries as baseline (`gpt-4o-mini`/0.5), at temperature 0,
and at `gpt-4o`/temperature 0, with identical verdicts, every `reason` reading as support for the composer's draft
(`data/eval/c_control_{baseline,temp0,gpt4o}_2026-10-11_*.json`). The verdict call is a support-question, not a
badly-worded relevance judgment, so its fix is a different call shape — see item 44.

### 42. `claim_in_passage` and `form` in the composer's output

**Status: done (2026-10-11).** **What:** `CorpusFinding.finding` (`agent.py:78`) becomes a claim restricted to what the
passage asserts — when X, Y happens, because Z — with an explicit escape for a passage that states no Z, so the model
marks it unstated instead of supplying one. A sibling `form` field classifies the passage itself: scene, thesis,
confession, diagnosis, a closed list.

**Why:** 26 of the 27 hand-labelled findings from the first golden-set run claim more than their quote shows (D3), and
the faithfulness judge agrees with those hand labels 27 of 27, so this change has a calibrated instrument the day it
ships. One caveat that calibration carries: only 1 of the 27 labels is a pass, so the judge's accuracy on a *faithful*
finding rests on a single case — and that is the side this change exists to populate, so the calibration set needs
findings that should pass before the judge measures the result. `form` is the one abstraction inside the retrieved
passage itself, and it ships without a metric. **Synergy:** this is the finding item 39 exports in its own block and
the claim item 40's units are written against.

**Built as:** renamed to `claim_in_passage` (matching the item's own title), confirmed with the user before
touching ~8 files — `agent.py` (composer's "kept" reuse and silent-override blocks now also carry `form`
through), `judges.py` and `one_sided.py` (internal dict-key reads), while `witness_view.py`'s and `judges.py`'s
*external* outputs keep the key name `"finding"` unchanged, now reading from the renamed internal field. `form`
is `None` exactly when there's no passage (`label == "silent"`), mirroring `quote`. 131/131 tests pass.

### 43. A falsification round

**Status: done 2026-10-12.** **What:** each idea unit's falsification test runs as a query in an ordinary batch file, with
its target side tagged, and its outcome is recorded as a null search (term, side, corpus, date) instead of read as a
verdict. No pipeline change: a falsification test is a query with a declared side, which items 17 and 20 already
support.

**Why:** a convergence is worth a script only once someone has looked for what would break it, and the gate has to
read the search rather than the silence, because a retrieval miss and an absence in the book look identical from
outside. Three golden-set entries (g07, g08, g09) are known failures precisely because their runs return the wrong
passage, so a falsification test landing on one of those formulations would otherwise read as "nothing against it".
**Synergy:** runs last. It depends on item 37 (a quote nobody can locate is not evidence), on item 44 (a false `ok`
reads as the counter-example having been found), and on item 40, where the units and their tests are written.

**Built as:** `src/ParallelProse/null_search.py` (`NullSearch`, `load_null_searches`, `record_null_search`) plus the `promotion` cross-check in `load_idea_units`. A null search is one record — `{ref, unit, term, side, corpus, date}` — that a falsification test was run and came back empty: it is the search, never a verdict. `load_idea_units(path, bites_index, null_searches)` rejects a `promotion` whose `null_search_ref` does not resolve, whose record names another unit, or whose recorded `side` disagrees with the unit's own falsification test; with no registry supplied, any promotion is rejected as unverifiable. `docs/idea_unit_spec.md`'s `promotion` row states the cross-check and a new "null-search registry" section documents the file. 152/152 tests pass.

### 44. E: an evidence-only per-book verdict — the false `ok` fix

**Status: done 2026-10-12 (design closed 2026-10-11) — 44.1-44.3 built; 44.4 resolved (the seed does not pin); 44.5 closed by reframing its acceptance to the defect it exists to fix (below).** Build-ready spec: `docs/item44_E_spec.md`. Decomposed into five units below, following the spec's build order; 44.1 takes the
spec's dual-format door, so the read-site switch (44.2) lands after the schema rather than in the same commit.
**Built as:** 44.1.1 landed (`agent.py`): `EVerdictBase` (`corpus_id`, `p_adjacent`, `p_answers`, `P`), `EFirst` (the base plus `retry`/`narrowed_query` — the field order is the bias control), `ESecond` (exactly the base, i.e. EFirst minus the two retry fields — a schema restriction, not a prompt line), the `EFirstBatch`/`ESecondBatch` per-book wrappers, and `e_judge_first(query, corpora)` — one `critique_llm` call over `format_context` (chunks) + `format_attempts` (lineage), never the composer's draft, never the word "support", returning the model's raw verdicts for `postprocess_e` (44.1.2) to normalize. 44.1.2 landed too (`agent.py`): `EPostVerdict` + `postprocess_e(verdict) -> EPostVerdict` — deterministic, outside the LLM, applied to both `EFirst` and `ESecond` (whose missing retry fields read as `no`/`None`): `retry` forced `no` when `p_answers = yes`, `narrowed_query` nulled whenever `retry = no`, and `ok` derived (`yes` when `p_answers = yes`; `no` when the book does not answer with no retry fired; `None` when a retry must decide) — every rewrite logged, never rejected. 44.1.3 landed (`agent.py` + `theme_batches.py`): `e_record(verdict, retry_used)` builds the canonical per-book record (`{label, P}`, a silent book adding `silence_cause` derived from `p_adjacent` plus `retry_used`), and `reflect` now calls `e_judge_first` + `postprocess_e` in place of its draft-support `PerBookCritique` call — E is wired as an interim placement inside `reflect` (the chosen option B), shipping **dual format**: the composer-derived `reason` (now a deterministic `p_answers=`/`p_adjacent=` summary), the `ComposerAnswer` findings and the `query content is absent` marker all stay, so `one_sided`, `witness_view`, `quote_check` and the `bite_id` map keep reading them. `CorpusState` gains `P`/`retry_used` (forwarded whole by `retriever`, per the repo's state invariant) and `retrieval_diagnostics` exports them. A retry-proposed book maps to `miss` so the existing router still runs it, and `retry_used` is true when the prior label was `miss`. **Option-1 placement and the E_second retry loop remain 44.3.** 141/141 tests pass.

**44.3 built as** (`agent.py`, `tests/test_agent.py`): `e_first` and `e_second` are graph nodes over a shared `_e_records` tail — `e_judge_first`/`e_judge_second` → `postprocess_e` → `e_record`, every slot forwarded whole (the state invariant). `e_judge_second` is the retry look's own call (same evidence-only prompt without the retry sentence, `ESecondBatch`). `route_after_e_first` returns `"retry"` when any book is left `miss`, else `"done"`; the retry arm is `retry_retriever` (a second registration of the same `retriever` callable) whose static edge lands on `e_second`, so retry-once is graph shape rather than an iteration counter. `composer` runs on `ok` books only — a silent book gets no finding, fewer than two `ok` writes agreement/disagreement deterministically, and zero `ok` skips the LLM. `reflect` shrinks to the comparison critique, short-circuits below two `ok`, and no longer returns `corpora`. Cleanup: `finalize`, `route_after_reflection`, the `PP_CRITIQUE_MODE` probe, the draft-mode `CorpusCritique`/`PerBookCritique` schemas and the `query content is absent` marker are gone. Graph: `retriever → e_first → {retry_retriever → e_second | composer} → composer → reflect → END`. 145/145 tests pass.

**44.4 + 44.5 measured (2026-10-12, real calls, real graph; `PP_CRITIQUE_MODEL=gpt-4o`, `PP_CRITIQUE_TEMPERATURE=0`).** Two seeded full-set runs (`PP_SEED=44`) diffed per side: **12/32 sides retrieved different chunks, 5 of the 6 bridge sides among them** (g09 B, g10 B, g11 B, g13 A, g15 A; only g07 B stable) — the seed does not pin, so the frozen-chunk replay is a prerequisite and E is reported against a re-baseline. Provisional label line: **28/32 agree on run 1, 27/32 on run 2** (g01 A flipped ok→silent); all **6/6 bridge sides silent**; every mismatch is an A side whose answering anchor was not retrieved (g05 A, g06 A, g09 A, g10 A), with `retry_used=true` and `silence_cause=adjacent_topic`. Triage: `retry_used=true` on 5/6 bridge sides (g10 B false). Records: `data/eval/seed44_run1_2026-10-12_1555.json`, `seed44_run2_2026-10-12_1601.json`, `data/eval/seed44_gate_2026-10-12.json` (local; `/data` is gitignored).

**44.5 closed by reframing the acceptance (2026-10-12).** The strict label line (6/6 fixed, 0 regressions) is not met, and the two seeded runs differ, so a per-side label count is not a stable measurement without frozen evidence. The acceptance is therefore the defect E exists to fix: **the six golden sides that were false `ok` — g07 B, g09 B, g10 B, g11 B, g13 A, g15 A — all come back `silent` in both runs.** The remaining four mismatches (g05 A, g06 A, g09 A, g10 A) are retrieval misses, verified by anchor check: the answering anchor occurs **0 times** in the retrieved chunks, so E is right to refuse the claim; the pre-E graph masked exactly this with draft-mode bridging. One case is E-side and unexplained: **g01 A** (anchor retrieved 1/1) labelled `ok` in run 1 and `silent` in run 2 — the parked replay would isolate it. The queued 44.5 data edits (`g13 A near_miss`, the `g17` Anon entry, `expect_e_first_retry`, the count rule) are **not applied**: they belonged to the strict measurement, not this acceptance.

**What:** a dedicated per-book judge that answers two questions on the retrieved
evidence alone — `p_adjacent` first ("does some chunk treat the query's theme under some proposition?"), then
`p_answers` ("does some chunk's own wording answer the query?") — and emits `P`, the passage's proposition (the
answering one, or the adjacent one for a silent book), plus a retry signal derived from the two: retry only when
`p_answers = no` and `p_adjacent = yes`, at most once, with `narrowed_query` null whenever retry is no. The
derivation is rewritten by a post-process outside the LLM, never rejected. E runs between `retriever` and `composer`
(option 1): composer then runs only on `ok` books, `reflect` shrinks to the comparison critique, and E's per-book
record becomes canonical — `{label, P}` for `ok`, `{label, silence_cause, P, retry_used}` for `silent` — which the
export, `one_sided` and the `bite_id` map read instead of composer findings. Five units, each built in order, each
one's output the next one's input:

- **44.1 E's judge, post-process, and canonical record** — the `E_first` schema (`p_adjacent`, `p_answers`, `P`,
  `retry`, `narrowed_query`, generated in that order — the bias control) and `E_second` as the same schema minus
  `retry`/`narrowed_query` (a schema restriction, not a prompt instruction), both on the `critique_llm` surface
  (`PP_CRITIQUE_MODEL`/`PP_CRITIQUE_TEMPERATURE`, the judges' gpt-4o/temperature 0). The post-process is
  deterministic, outside the LLM, applied to both looks: `retry := "no"` whenever `p_answers = "yes"`;
  `ok := "yes"` whenever `p_answers = "yes"` and no retry fired; `narrowed_query := null` whenever `retry = "no"` —
  rewrite, log, never reject. E sees `query + chunks + lineage`, never the composer's draft, and its prompt must not
  use the word "support". **Ships with dual-format reads** (spec §7), so the existing consumers keep working and
  44.2 can follow independently.
- **44.2 The read-site switch** — `one_sided.py` reads `label == "silent"` from E's record instead of the marker
  string; `witness_view.py` drives the per-book record from E so a silent book still produces its record with `P` as
  the adjacent material; `theme_batches.side_is_target`, the `bite_id` map (`answer_query`), and
  `quote_check.select_quotes`/`verify_quotes` read E's record, with a query-addressed fallback when there is no quote.
  Drops the dual-format path.
- **44.3 Placement and the retry loop** — `retriever → E_first → [retry?] → retriever(narrowed) → E_second →
  composer(ok books only) → reflect(comparison critique)`. Retry fires at most once (iteration 0 only); when lineage
  already shows a prior iteration, route straight to E_second. One call covers both books. The retry edge is global,
  the decision per book, and a non-retrying book forwards its whole slot — the repo's standing state invariant.
  `reflect` short-circuits when fewer than two books are `ok`. Cleanup rides along: the `PP_CRITIQUE_MODE=evidence`
  probe, the draft-mode per-book prompt, and the dead silent-override block in `agent.py` are removed.
- **44.4 The seed gate** — `PP_SEED` on the shared client (it cleans future draws only), then two seeded baseline runs
  diffed per side. If the chunks differ on the failing side, the seed is not pinning and the frozen-chunk replay
  becomes a prerequisite. E is reported against a post-seed re-baseline, never the pre-seed runs.
- **44.5 Calibration** — all 32 labels, real calls, real graph, three outputs per side (`label`,
  `expect_e_first_retry`, the `P` probe). Label line: 6/6 to `silent`, 0 regressions on the 26 agreeing; the triage
  line is separate: `retry_used = true` on the six near-miss and `retry_used = false` on the agreeing "nothing to
  search" sides; contested adjacency is its own counter. Fixtures: six bridge fixtures (g07 B, g09 B, g10 B, g11 B,
  g13 A, g15 A), the retry pair (the Anon query and g12 A), `g16 B` as the `p_adjacent = no` guard, a
  contested-adjacency counter, and a `P` probe. **Never starts before 44.4 is resolved.** Queued data edits land
  here: `g13 A` `near_miss: false`, the new `g17` Anon entry, and the golden spec's count rule 16 to 17.

**Why:** measured twice. The C control showed the failure is the task, not capability (three variants, zero flips;
every reason reads "supports the finding/claim"). The A-alone probe — draft removed, question re-pointed — flipped
all six false `ok`s but netted 26/32 on the full set: every regression sat on a side whose answering anchor was
absent from the chunks, because draft-mode bridging had been masking retrieval misses. E therefore needs both the
evidence-only judgment and the retry signal, with `P` keeping the adjacent material that item 40's single-voice units
and item 39's silent witness read. **Synergy:** unblocks item 43 (a false `ok` reads as the counter-example having
been found); feeds item 40; takes the item-37 direction for book-level checks.

### 45. DeepSeek for the gpt-4o roles: the attribution judge first

**Status: 45.1 done and validated 2026-10-13 on live runs that never touch DeepSeek; 45.2 written down; 45.3-45.4 not started.**

**What:** the recurring OpenAI cost sits in gpt-4o, so only what runs on gpt-4o moves — and only after the spend is
attributed to a role by measurement rather than by estimate. Everything on gpt-4o-mini stays on OpenAI:
`deepseek-flash` matches gpt-4o-mini's list price off-peak and costs double at peak, so there is nothing to save
there. Embeddings stay on OpenAI too — DeepSeek has no embeddings endpoint, re-embedding the whole index costs about
$0.004, and swapping the model would move retrieval and invalidate the golden set for no saving. That narrows the
migration to the evaluation judges, and inside them to **attribution** (~7k input tokens per query against
faithfulness's ~0.5k). Four units, each built in order:

- **45.1 The run record per role** — one committed writer for the run JSONs in `data/eval`, carrying provider, the
  model **requested and the model returned**, temperature per role (composer, critique, judge), the `sha256` of each
  prompt text, `usage_metadata` including `prompt_cache_hit_tokens`, and the wall-clock time (peak and off-peak are
  half-price apart). `evaluation.configuration()` gains `critique_model`, which it does not record today, and
  `agent.py:22-23`'s seed comment is corrected — `SEED_KWARGS` reaches `critique_llm` too, not only the retrieval
  agent and the composer. **Validated on a run that does not touch DeepSeek** — re-record an existing entry and check
  the fields — so the recorder is not carrying the migration's evidence before it is itself proven. Today the only
  committed writer under `data/eval` is `judges.judge_records`; every run JSON (`seed44`, `set40`, `afterC2`,
  `c_control`) came from ad-hoc code and records no model at all, which is why the gpt-4o/gpt-4o-mini split could not
  be read off the artifacts and why the 25/27-vs-26/27 attribution confusion was possible.
  **How usage is attributed to a role.** `langchain_core`'s `UsageMetadataCallbackHandler` cannot do it: it keys its
  accumulator on the model name (`callbacks/usage.py:58-74`), and in routine runs the composer and the critique share
  gpt-4o-mini, so their tokens land in one bucket. Instead, one small `BaseCallbackHandler` that buckets by a
  **per-role tag**, correlating `on_chat_model_start` to `on_llm_end` by `run_id`, **instantiated per run and passed
  through config** — never a module-level accumulator, since `run_experiment` runs at `max_concurrency=2` and a shared
  one would blend two examples. Five mechanics, each one a trap already located:
  - **Read the role tag by prefix, never by position.** LangChain injects its own tags (`seq:step:N`,
    `runnables/base.py:3438`), so the handler searches the list for `role:`. Two `role:` tags on one call — a parent's
    and an object's — is **ambiguous and must raise**, not be silently resolved to the first.
  - **Tag per invocation, never on the client object.** The same `llm` serves the retrieval agent (`agent.py:215`) and
    the composer and `reflect` (`agent.py:360`, `:552`), so an object-level tag would fuse three roles into one; and
    `create_agent` types `model: str | BaseChatModel` (`langchain/agents/factory.py:769`), which the `RunnableBinding`
    that `with_config` returns is not.
  - **The returned model and the requested model are different fields, and taking the wrong one voids the whole
    point.** The returned one is `generations[0][0].message.response_metadata["model_name"]`, filled from the API's own
    `response_dict["model"]` (`langchain_openai/chat_models/base.py:1876`). The requested one is
    `response.llm_output["model_name"]`, which `_combine_llm_outputs` sets from `self.model_name`
    (`base.py:1404`). Record both, from those two fields — that pair is exactly what catches a `deepseek-v4-pro`
    request served as Flash, or a moved `gpt-4o` snapshot.
  - **Cache hits read the same way on both providers**, through `usage_metadata["input_token_details"]`: langchain-openai
    maps `prompt_tokens_details.cached_tokens` and `ChatDeepSeek` maps `prompt_cache_hit_tokens`. One caveat in that
    mapping — the key is **prefixed by service tier when one is present** (`f"{service_tier_prefix}cache_read"`,
    `base.py:4190`), so match a key *ending* in `cache_read` rather than hard-coding `"cache_read"`.
  - **Two collection points, because the judges are not in the graph.** `attribution_evaluator` calls
    `judges.attribution(record)` directly (`evaluation.py:349-351`), outside any config `run_query` received — and that
    is precisely the role this unit exists to size. So the handler is also passed explicitly into
    `attribution()` / `faithfulness()` (or into `judges._judge`), not only through the graph's config. In sequential
    local runs the two points coincide; under `aevaluate` they do not.
- **45.2 The self-judging invariant, written down** — the **faithfulness** judge never on the same model as the
  **composer** nor the **picker** (its claim comes from the composer, its sentence from the picker); the
  **attribution** judge never on the same model as the **composer** (it judges headlines). Satisfied today (composer =
  picker = gpt-4o-mini, judges = gpt-4o), so this unit is the statement, not a change — and it is what decides, later,
  whether a judge may follow the composer through a provider swap.
- **45.3 DeepSeek access and the two-round smoke test** — the client plus `DEEPSEEK_API_KEY`, then the schemas against
  the live API. Round 1 sends them as langchain builds them; round 2 sends the strict schema built here. Gate for 45.4:
  both judge schemas accepted, `parallel_tool_calls` accepted (langchain-openai sends it on the function-calling path
  and DeepSeek does not document it), and thinking disabled — thinking is on by default, it voids `temperature`, and it
  refuses a named `tool_choice`, all three from DeepSeek's own reference. One clause here is weaker evidence than the
  rest and is marked as such: the API requires `reasoning_content` to be echoed back on requests carrying `tools`
  (documented, verbatim, in the thinking-mode guide), and `ChatDeepSeek` appears not to re-insert it — that second half
  is **read in the client's source, never observed live**. It does not change the conduct, since thinking is disabled
  either way. Informative only: the nested-batch schema.
- **45.4 The attribution judge on `deepseek-flash`** — the client chosen by env var in `judges.py`, **per judge**, so
  faithfulness stays on gpt-4o. Measured on the frozen chunks of `data/eval/records_2026-10-09_2050.json`, the run the
  27 hand labels came from, through `judges.attribution(record)` unchanged with a `finding` → `headline` adapter; the
  same ids appear in later runs with different chunks, and judging against those would compare the new judge to
  passages the human never saw. **The gpt-4o baseline is reproduced first: 26/27, single error g05 A judged `B`**
  (`calibration_2026-10-09_2122`, the current "decide by the idea" prompt). 25/27 with g15 A judged `both` means the
  old prompt or a bad join; 26/27 with the error elsewhere means the `gpt-4o` alias moved snapshot. **Adoption bar:
  ≥26/27 in each of three repetitions, and no new error pattern.** The three repetitions reuse the same 27 cases, so
  they filter sampling noise, not a systematic error of kind — which is why the pattern rule is the one carrying
  information, and why a single unlucky disagreement (an equivalent judge fails all three about 11% of the time)
  reopens the bar rather than rejecting the judge.

**Built as (45.1, 2026-10-13):** `src/ParallelProse/run_record.py` is the one committed writer. `RoleUsageTracker` buckets calls by the `role:<name>` tag and warns when a call carries none; **two role tags raise**, per the mechanics above, never resolve. `prompt_sha` hashes the batch shape `on_chat_model_start` really hands over — the unit test had passed a flat list, and the first live run exposed the difference as one sha for eight calls. `write_run_record` stamps `recorded_at`, `peak`, the per-role configuration (class, base_url, requested model, temperature) and, per role, calls, input/output tokens, cache reads under any service tier, returned models and prompt shas. The six call sites carry their tags (`retrieval_agent`, `composer`, `reflect`, `critique_e`, `sentence_picker`, `judge`); `run_query`/`answer_query`/`run_golden_query` thread the tracker, and `_judge` takes callbacks because the judges run outside the graph. `evaluation.configuration()` gains `critique_model`, `role_configuration()` reads the six roles off the live clients, `record_golden_entry(entry)` is the recording path, and `agent.py:22-23`'s seed comment now names both seeded clients. **Validated live, never touching DeepSeek:** a graph run recorded four roles with zero warnings (`data/eval/smoke45b_2026-10-13_221246_g01.json`), a direct `reflect` call recorded the fifth (192 in / 61 out), and a judge call recorded gpt-4o at 11,682 input / 4,992 cache-read tokens, returned `gpt-4o-2024-08-06` against the requested alias `gpt-4o`. The validation also caught a defect the tests did not: an `on_llm_end` with no start was counted without a warning; fixed. 161/161 tests pass. First measured number for 45.4: **~5.8k input tokens per attribution call, two calls per record, ~43% cache hits already.**

**Built as (45.2, 2026-10-13):** the invariant is stated where it governs, not only here. `judges.py`'s module docstring carries the rule and its scope — faithfulness off the composer's and the picker's models, attribution off the composer's and free to share the picker's — and the critique client's comment in `agent.py` points at it. The scope is the part worth having: the defaults satisfy the invariant, but an env override can break it, since `PP_CRITIQUE_MODEL` moves the picker's surface, so pointing it at the judge model makes faithfulness grade sentences its own model selected. No behaviour changed and no test was added: the unit is the statement.

**Why:** measured. Attribution on gpt-4o costs about $0.019 per query against about $0.001 on `deepseek-flash`
off-peak — a ~94% cut off-peak, ~88% at peak — and the judge's independence survives, because it grades headlines
written by gpt-4o-mini. `deepseek-flash` is the only stable target: the 2026-09-10 announcement says "We're phasing
out V4-Pro" and routes every `deepseek-v4-pro` request to V4.1-Flash at Flash rates from 04:00 UTC on 2026-09-14, so
asking for v4-pro already returns Flash. That is also why 45.1 records the model the API *returns* and not only the one
requested: without it a run labelled v4-pro is a Flash run under the wrong name, and the same guard catches a moved
`gpt-4o` snapshot. The alternative that keeps the provider stays available and asynchronous: gpt-4o through the Batch
API is $1.25 in / $5.00 out per 1M against $2.50 / $10.00 standard — exactly half, read off that model's own row, not
assumed from the generic batch discount — with the calibration untouched.

**Out of scope, with the reason, so it is not reopened by habit:** **E and the picker stay on OpenAI.** In routine runs
they are gpt-4o-mini; `PP_CRITIQUE_MODEL=gpt-4o` was only ever a measurement override, so there is no saving to take.
Had they moved, three things would have had to move with them — the strict route is closed for `P`,
`narrowed_query`, `sentence_index` and `form`, since `null` is absent from DeepSeek's strict type list and the server
rejects unsupported types, leaving non-strict plus Pydantic validation and a bounded retry; E's field-order bias
control (`p_adjacent` before `p_answers`) has no server guarantee outside strict and would have to be enforced by
splitting E into two calls, one schema without `p_answers`, the way `ESecond` already restricts a schema instead of
instructing a prompt; and `PP_SEED` has no DeepSeek equivalent. **Faithfulness stays on gpt-4o** — ~0.5k tokens per
call, so migrating it buys almost nothing, and its judge has no human calibration at all in its current (claim,
sentence) pair form (see the Backlog). **Synergy:** 45.1 is the instrument every later measurement reports through,
including item 46's.

### 46. E measured in the configuration it actually runs in

**Status: triggered 2026-10-13, not started.** **What:** re-measure item 44's acceptance — the six golden sides that
were false `ok` (g07 B, g09 B, g10 B, g11 B, g13 A, g15 A) all coming back `silent` — on the `critique_llm` surface as
the code actually defaults it: gpt-4o-mini at temperature 0.5. Item 44.5 measured it at gpt-4o and temperature 0.
`ROADMAP.md:1041` is complicit: it describes that surface as "the judges' gpt-4o/temperature 0", which is the
measurement override, not the default in `agent.py:31-33`. Report through item 45.1's run record, so the configuration
travels with the numbers this time.

**Why:** the acceptance that closed item 44 was never measured in the configuration that serves queries, so the
project's headline result rests on a setting nobody uses. This is a validity gap, not a cost question, and it is cheap
to close. If the six hold on gpt-4o-mini, item 44 is confirmed as shipped and nothing follows. If they do not,
`deepseek-flash` returns to the table **on capability, not on cost** — a stronger model at gpt-4o-mini's off-peak
price — and then item 45's out-of-scope paragraph becomes the build list: non-strict with validation, and E split into
two calls so the bias control holds by construction.

### Backlog (deferred, not dropped)

**Faithfulness judge: hand labels in the (claim, sentence) pair form.** The current judge (`PairVerdict`, since
`024e4d8`) grades one atomic claim against the sentence it was paired with. Every hand label on disk predates it: all
147 rows across `calibration_2026-10-09_2104/_2122`, `calibration_post42` and `calibration_balanced_2026-10-12` carry
the judge output in the old `{claims, unsupported}` whole-finding form, so the "27/27" and "128/147" figures measure the
retired instrument. **The faithfulness judge therefore has no human calibration today, on gpt-4o or anywhere.** Needs a
balanced set of pass and fail pairs labelled by hand; the 27 augustine_debord rows hold a single positive case, and the
120 RAGTruth rows are another domain and another bar (they measure transfer, not behaviour on these passages).
Prerequisite for migrating faithfulness, and for trusting its current numbers at all.

**E and the picker on DeepSeek.** Not a cost item (see item 45's out-of-scope paragraph) — opened only if item 46 shows
the six false `ok`s do not hold on gpt-4o-mini, i.e. on capability. Carries its own build list: non-strict structured
output with Pydantic validation and one bounded retry loop owned by `_verdicts_for_every_book` (at most 3 calls per
look, raising a message that names the book, repeating the prompt rather than feeding the error text back into an
evidence-only surface), E split into two calls for the field-order control, and `order_ok` recorded per verdict out of
the raw arguments as a sanity check on that split.


**First evaluation experiment run.** The harness is built and available; no experiment has been run with `LANGSMITH_TRACING` on. Deferred 2026-10-12 by decision — run it when a scored, repeatable experiment is needed (it can fold in E's calibration).

**Retrieval misses on four Augustine sides (g05 A, g06 A, g09 A, g10 A).** E correctly labels them `silent`; the golden anchor that would make them `ok` never reaches the chunks (verified 0 occurrences in two seeded runs). This is the whole remaining gap between the current label agreement and 32/32, and it is a retrieval problem, not a judgment one — so it belongs with the retrieval work (items 13/14/37's neighbourhood), not with E. Revisit when the retrieval side is next opened.

**Frozen-chunk replay (was item 44.5b).** Design closed 2026-10-12 — capture each look's chunks+lineage from the live graph with `astream`, then replay E over exactly that; two functions, `capture_evidence` -> `replay_e`, walked through concept/design/pseudo-code. Parked before build: it buys a reproducible calibration number, not a better one — freezing retrieval keeps the four misses as `silent` and changes no verdict, because the anchors are absent from the frozen chunks. Pick it up only if a repeated, evidence-controlled calibration line is required, e.g. to isolate the g01 A flip.

**Per-theme survey and query translation (`survey.py` rebuild, `translate.py`).** Designed, not built: discover each
theme's vocabulary from the book sentences closest to thesis + query, gate on whether the bare query's retrieval
reaches those sentences, and rewrite the query by LLM only when it doesn't. Deferred on the same evidence as item 34.
Of the 12 silent verdicts in the history, 9 were the non-target side of a twin, 1 is plausibly genuine, and 2 are
retrieval misses ("Anon, anon" is verbatim in the book and still not returned) — at most one ("imagined life") looks
like a wording failure this would fix. Revisit only if the evaluation harness (item 30) shows wording failures that
retrieval fixes cannot reach. The existing `survey.py` (term-list levels 0-2, unused) is kept as the starting point for
that rebuild.

## Out of scope here

**RAG-Tetris** (comparing a language feature's evolution across versions, e.g. Python's GC or type system across
releases) is a separate future project, built elsewhere, not in this directory. If a design choice here ever has to pick
between what's best for this project and what would ease future sharing with RAG-Tetris, this project wins — Tetris gets
addressed when it actually starts.
