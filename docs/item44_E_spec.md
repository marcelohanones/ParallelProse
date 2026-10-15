# Item 44 — E spec (build-ready)

**Status:** design closed 2026-10-11 (Claude web rounds 1-10, plus the harness C and A-alone runs). **No code written.** This document is the build's single source; the round-by-round record lives in `docs/claude_web_item41_reply{,_2,...,_9}.md` and `docs/claude_web_item41_evidence.md`.

## 0. Prerequisite: update ROADMAP.md before any code — **done 2026-10-12**

Item 44's section carried two failed prompt rewrites and an open false-`ok` gap; it was rewritten to the settled design (step 0, done 2026-10-12), covering:

- **Status**: "design closed 2026-10-11, build not started" — then per-step notes as steps land.
- **What**: E as the evidence-only per-book verdict (sections 2-6), the `p_answers`/`p_adjacent` triage, retry-once, the derivation and post-process, `P` as the canonical per-book record, option-1 placement, the read-site switch, the fixture set, and the calibration with the seed gate.
- **Why (measured)**: the C control (three variants, zero flips — the failure is the task, not capability) and the A-alone probe (the six flip, but the full set nets 26/32, every regression on a side whose answering anchor was absent from the chunks — the draft-mode bridging was masking retrieval misses).
- **Built as**: "not started" until step 1 lands, then the roadmap's own convention.
- **Queued data edits named**: `g13 A` `near_miss: false`; the new `g17` (Anon) entry; the `expect_e_first_retry` field row; the spec count rule 16 → 17.

## 1. The failure E exists to fix (measured)

- The per-book verdict is produced in the same call that critiques the composer's draft, and the prompt is a support-question ("does this passage support the draft"). All six golden disagreements (g07 B, g09 B, g10 B, g11 B, g13 A, g15 A) are expected `silent` and land `ok`.
- **C control**: baseline (gpt-4o-mini/0.5), temp 0, and gpt-4o/temp 0 produce identical verdicts — zero flips; under gpt-4o every reason says "supports the finding/claim". Task, not model.
- **A-alone**: draft removed and question re-pointed; the six flip to `silent`, but the full set nets 26/32 (5 fixed, 5 regressed, 1 still bad) because a retrieval miss becomes silence. Draft-mode bridging had been masking retrieval misses; `miss` fires under evidence mode (3 cases) and burned MAX_ITERATIONS.
- Records: `data/eval/c_control_{baseline,temp0,gpt4o,a_only,a_only_full}_2026-10-11_*.json`.

## 2. E's identity and placement

- E is a dedicated judge call (gpt-4o, temperature 0 — the judges' config), on the existing `critique_llm` config surface (`PP_CRITIQUE_MODEL` / `PP_CRITIQUE_TEMPERATURE`).
- **Placement (option 1)**: `retriever → E_first → [retry?] → retriever(narrowed) → E_second → composer(ok books only) → reflect(comparison critique)`.
- E sees `query + chunks + lineage`. **Never the composer's draft.** E's prompt must not use the word "support": the judgment form is "does the passage's own proposition answer the query", not "does this support the draft".
- Composer runs only on `ok` books; `reflect` shrinks to the comparison critique and short-circuits when fewer than two books are `ok`.
- The retry edge is global, the decision per book, and a non-retrying book forwards its whole slot — the repo's standing state invariant.

## 3. E_first schema (field order is part of the spec)

Fields generate in order; the order is the bias control.

1. `p_adjacent: Literal["yes","no"]` — "some returned chunk treats the query's theme under some proposition, whether or not it answers the query". Phrased independently of `p_answers`, never as "adjacent to what I did not find".
2. `p_answers: Literal["yes","no"]` — "some returned chunk's own wording answers the query".
3. `P: str | None` — the proposition: the answering passage's proposition when `p_answers = yes`; the adjacent passage's proposition when `p_answers = no && p_adjacent = yes`; `null` when both are no.
4. `retry: Literal["yes","no"]` — the model's proposal, normalized by the post-process (section 4).
5. `narrowed_query: str | None` — only when `retry = "yes"`; forced `null` otherwise, never an empty string or placeholder.

## 4. Derivation and post-process — both call sites

| `p_answers` | `p_adjacent` | `retry` | `ok` | `P` |
|---|---|---|---|---|
| yes | — | no (forced) | yes | answering proposition |
| no | yes | yes | E_second decides | adjacent proposition (answering one if it flips) |
| no | no | no | no (silent) | null |

Post-process — deterministic, outside the LLM, applied to **E_first and E_second**:

- `retry := "no"` whenever `p_answers = "yes"` (not only the reverse);
- `ok := "yes"` whenever `p_answers = "yes"` and no retry fired;
- `narrowed_query := null` whenever `retry = "no"`;
- **rewrite, log, never reject.**

E_second carries the same invariant even though it has no `retry` or `narrowed_query` fields.

## 5. E_second and the retry loop

- E_second = E_first's schema **minus `retry` and `narrowed_query`** — a schema restriction, not a prompt instruction.
- It runs **only** after a retry round. When the first look answers (`p_answers = yes`), `ok = yes` is already decided and E_second is not called. Cost: one call per book when the first look answers, two when it retries.
- Retry fires **at most once** (iteration 0 only). If lineage already shows a prior iteration, route straight to E_second — E_first is not called again.
- One call covers both books.

## 6. The canonical per-book record

E becomes the per-book record; composer's findings stop being it.

- `ok` → `{label: "ok", P}` from E; composer adds `claim_in_passage`, `quote` (verified), `form` afterwards.
- `silent` → `{label: "silent", silence_cause, P, retry_used: bool}` from E. `P` is the adjacent proposition (or null); `silence_cause` derives from `p_adjacent` (`adjacent_topic` when yes, `absence` when no), with `non_target_twin` still resolving deterministically outside the graph.
- Composer's `"query content is absent"` marker disappears; the silent-override block in `agent.py` becomes dead code.
- The degenerate answer (all-silent / one-silent) is owned by a thin aggregator reading E's records — not composer.

## 7. Read-site switch — coordinated landing

E landing without these switched breaks the consumers for a window. Same commit as E's schema, or dual-format reads during the transition:

- `one_sided.py:11` — read `label == "silent"` from E's record instead of the marker string.
- `witness_view.py:19` — drive the per-book record from E; a silent book must still produce its record, with `P` as the adjacent material, or silent testimony vanishes from item 39's export.
- `theme_batches.side_is_target` and the `bite_id` map (`answer_query`), and `quote_check.select_quotes` / `verify_quotes` — they iterate composer findings; silent books need their id and verification from E's record (query-addressed fallback when there is no quote).

## 8. Fixtures

- **Six bridge fixtures** (anchored to the bridge sentence, minted with `compute_bite_id`): g07 B `33bbcf03`, g09 B `fcd372dc`, g10 B `f38d23fe`, g11 B `4fe0ae73`, g13 A `debc63d9`, g15 A `b3ce714d`. Expected: `p_answers = no`, `p_adjacent = yes`, `retry = yes`, `silence_cause: adjacent_topic`, `P` clean under the probe.
- **Retry pair**: Anon `97138e60` (`expect_e_first_retry: "yes"`; final `ok = yes` after the retry); g12 A `ca15bc3a` (`expect_e_first_retry: "either"`; final `ok = no`).
- **Negative `p_adjacent` guard**: **g16 B** (`p_adjacent = no`; "method" x4 is the vocabulary trap); backups g16 A and g08 B. Without it an always-yes E passes.
- **Contested adjacency counter**: g12 A (golden `near_miss: false`, runtime `p_adjacent = yes`) — out of the triage denominator, counted separately.
- **`P` probe**: `P_must_contain` a passage-side phrase or content words; `P_must_not_contain` query-side terms absent from the passage. Trap: "utopian" **is** in g10 B's passage and must not be forbidden.
- Fixture ids are their own content-addressed set; `Ancoragem` additionally requires witness-view index membership (zero `witness_view_*.json` on disk today).

## 9. Calibration protocol

- All 32 labels, real calls, real graph.
- **Three outputs per side**, not one: `label`, `expect_e_first_retry`, the `P` probe.
- **Label line**: 6/6 to `silent`; 0 regressions on the 26 agreeing.
- **Triage line (separate)**: `retry_used = true` on the six near-miss **and** `retry_used = false` on the agreeing "nothing to search" sides (ok with the anchor retrieved; silent `near_miss: false` with off-theme chunks).
- **Contested adjacency** reported as its own counter.
- **Seed gate**: two seeded baseline runs, diffed per side; if the chunks differ on the failing side, the seed is not pinning and the frozen-chunk replay becomes a prerequisite rather than a deferred item. E is reported against a post-seed re-baseline, never the pre-seed runs.
- The seed knob (`PP_SEED`) goes on the shared client; it cleans future draws only.

## 10. Build order

0. **ROADMAP.md update** (section 0) — before any code.
1. E's schema and the post-process (`agent.py`).
2. Read-site switch (section 7) — **same commit as 1**, or dual-format.
3. Placement edges (option 1) — independent of E.
4. Seeded re-baseline + two-draw stability test.
5. Calibration (section 9) — **never starts before 4 is resolved.**

Execution order that matches the dependencies: 1, 3, 2, 4, 5 (3 is independent and can move earlier).

## 11. Queued edits and cleanups

- `data/golden_set_augustine_debord.json`: `g13 A` `near_miss: false`; the new `g17` (Anon) entry with `expect_e_first_retry`.
- `docs/golden_set_spec.md`: "exactly 16 / g01-g16" → 17+; the `expect_e_first_retry` field row and its coherence rule (`known_failure: false` never with `"yes"`).
- `agent.py`: the `PP_CRITIQUE_MODE=evidence` probe and the draft-mode per-book prompt are superseded by E — remove once E lands. `critique_llm` stays as E's config surface.
- Temp runners `.tmp_c_control.py` / `.tmp_c_report.py` are reusable for the calibration; remove or promote when it is written.
