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
  objective (item 12, in progress), then a proper test suite (item 13), then the evaluation harness (item 14).
  The synthesis layer was always its own version — a distinct capability layered on top of a finished, tested
  two-book comparison system; the test suite and eval harness moved here from v3 since v3's own completion no
  longer waits on them, and now land after the synthesis layer so they cover it too. See "v4 — after v3 is
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
recurring. **Synergy:** directly consumes item 10's findings; must land before the test suite (item 13) so the
suite is written against `Critique`'s fully settled shape, not one about to change again.

## v4 — after v3 is complete

### 12. Synthesis layer — connect targeted queries to a stated objective

**Status: in progress, started 2026-10-03.** **What:** a standalone, non-graph function
(`synthesize(objective, bites) -> Synthesis`) that reads a session log of already-finished `(query,
ComposerAnswer)` bites plus one fixed objective, and returns a connective narrative plus an
`uncovered_angle`/`candidate_query` naming what the objective still lacks — a suggestion only, never auto-run;
the human decides every query, including whether to take the suggestion. A companion `save_bite`/`load_bites`
pair persists bites to a flat JSON session file (`{"objective": ..., "bites": [...]}`), one objective set once
per series. Paired with a brief for Claude web (`docs/claude_web_query_brief.md`) instructing it to decompose a
theme into one or more bounded objectives (splitting when a theme fails the common-throughline test — do all of
one objective's queries plausibly weave into one narrative?) and each objective into single-themed, non-compound
queries. **Why:** `composer`/`reflect` are built and validated around one targeted query at a time (items 4-11);
bending them to also reason about a broader, cross-query objective risks the same half-adopted-axis bug item
10/11 just fixed — one node aware of a new concern, the rest of the graph blind to it — and unlike the two-book
axis, "served the objective" has no falsifiable schema field the way `label`/`reason` do, so a corrupted
grounding loop would be far harder to catch. Keeping the objective entirely outside the grounding loop, as a
function that only ever consumes already quote-backed answers, avoids both risks. **Synergy:** manual-first by
design — automatic chasing (the system deciding to run its own suggested query) is deliberately deferred until
the manual version proves useful. Kept as its own item within v4 rather than folded into the test suite or eval
harness (items 13-14): it's a distinct capability layered on top of a finished, tested two-book comparison
system, not a prerequisite for either of those, which cover the graph as it stands today.

### 13. Test suite

**Status: planned.** **What:** a proper `tests/` suite covering the graph's core node logic — `retriever`'s
skip-on-`ok`/`silent`, `composer`'s silent-override (`finding` + `quote` blanking), `reflect`'s per-book label
return, `route_after_reflection`'s routing branches — and relocating the ad-hoc `test_retriever`, `test_accumulation`,
`test_retriever_2` functions currently embedded in `agent.py`'s `__main__` block into that suite (updated to the
current state shape where still relevant, dropped where superseded). **Why:** today's only "tests" are those three
stale functions — `test_accumulation` still assumes the flat pre-item-2 state shape (`narrowed_query`/`chunks`/
`lineage` at the top level, not nested under `corpora`) and would crash if run; none of the three assert anything,
they just print; and they sit mixed in with live-call demo code in the same `__main__` block (see `CLAUDE.md`,
"Guard module side effects"). **Synergy:** lands after packaging (item 9), after `Critique`'s 2-book-native
shape settles (items 10-11), and after the synthesis layer (item 12), because `run_query()`, `Critique`, and
`synthesize()` are exactly the things this suite needs to test against shapes that are finished changing; also
lands before the eval harness (item 14), because that harness checks answer *quality*, a different concern from
code correctness — it benefits from running against code that's already covered, not the other way around.

### 14. Evaluation harness

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

### Backlog (deferred, not dropped)

Currently empty — era-annotation and quote-extraction, the only two entries previously here, were promoted into the
sequenced v3 items above (7 and 8).

## Out of scope here

**RAG-Tetris** (comparing a language feature's evolution across versions, e.g. Python's GC or type system across
releases) is a separate future project, built elsewhere, not in this directory. If a design choice here ever has to pick
between what's best for this project and what would ease future sharing with RAG-Tetris, this project wins — Tetris gets
addressed when it actually starts.
