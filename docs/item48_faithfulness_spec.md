# Item 48 — The faithfulness judge: extract, then decide (build-ready)

**Status:** design closed 2026-10-14 (CRITIQUE loop, CC x DSH x Markim, rounds 1-4). **No code written.** This
document is the build's single source. `[Markim]` rulings: **D1** the evidence unit is the sentence alone, read
literally; **D2** strict is the headline number, lenient the second column; **D3** instrument first, producer second;
**M1/M4** the gate holds on the 14 uncontested `covered` pairs, the 5 disputed are reported and never gated, the 8
doubt-noted stay inside the gate and are adjudicated case by case on failure; **M2** the per-book boolean survives for
LangSmith and `judge_records` while the pair-level strict rate plus the addition profile become the numbers read;
**M3** one row-shape change, this commit; **M5** calibration phase ceiling ~$1.00; **M6** the 13-ref family
ratification (9 agent-primary + 4 uncertains).

> *terms:* label class = reference class (`covered` / `covered_one_step` / `not_covered`, from the sheets) — runtime
> relation (`stated` / `one_step` / `absent`, from the schema). One criterion, two vocabularies: the first describes a
> pair, the second describes one segment of a claim.
> *terms:* `rider` (families file) = structural shape "a legitimate rewording plus an extra proposition"; it is **not**
> an `addition_kind` value and never maps to one. A rider pair is annotated at runtime by the kind of the thing that
> rode in.

## 0.0 Outcome — closed 2026-10-14: measured, not accepted, adopted as a floor

The acceptance round (140 pairs x 3 repetitions, `gpt-4.1-mini`, temperature 0, `v5b-counterpart-examples`,
`instructions_sha 3fdc872c19e7`, record `data/eval/item48_acceptance_gpt-4.1-mini_2026-10-14_2127.json`) **failed two
cells and passed four**:

| cell | 3 reps | bar | |
|---|---|---|---|
| `not_covered` rejected | 94, 94, 93 / 96 | >=82 | pass |
| union of false passes | **3** (p36, p70, m21) | <=16 | pass |
| gated agent refs leaked | **0** | 0 | pass |
| not a rejecter (`model_absent`) | 108, 108, 107 / 140 | <=120 | pass |
| `covered` not `absent` | 11, 12, 11 / 14 | >=13 | **fail** |
| typing-unstable pairs | 11 / 140 (4 gate-decision-unstable) | <=5 | **fail** |

**Adopted anyway, as a floor.** `faithfulness`'s `passed` is the lenient view, so the column reads *no addition
detected*; the figure is a **lower bound** (3 of 8 genuinely faithful natural pairs cleared, 2 of 78 over-claims
leaked). On the defect the item exists to catch: **3 false passes in 288 negative judgements**, against v1's 46-62 in
a single pass. Named false negatives: **p39** (`modality:is considered`, all three reps), **p43** (`other:In modern
society,`, all three), **m02** (rep 1, the model's own `agent:The spectacle` -- not a repair), **m29** (rep 3).

**Report rules that travel with every future round:** the natural-set figure never appears without its rejecter
baseline (79/86 against 78/86 -- an edge of one pair) and without the cleared/leaked pair; the strict column appears
with the **count of `stated` pairs** that round produced (10, 9, 13 here), not merely with a vacuity flag; the
tolerance zone (`covered_one_step`) is reported with its composition and never gated; code repairs
(`repaired_absent`, `c2_repairs`, `invalid_add`, `invalid_counterpart`) are counted apart from judgements.

**The producer item's metric (settled here, section 14):** pairs carrying at least one `agent`, `cause_means` or
`consequence` item -- 29/33/28, 26/30/31, 31/31/34 per repetition -- counted per pair, never per item, and excluding
`other`, `evaluative`, `modality` and `quantity_generalization` for the reasons in `judges.DEFECT_FAMILIES`.

**Reference maintenance owed, rule before labels:** a blind adjudication of p39, p43 and the p36/m08-versus-m27/p68
contradiction, with the question stated first -- *does dropping a qualifier or broadening a term count as adding
content?* -- and the consequence of each answer pre-stated. Recorded as maintenance; never scored against the
instrument.

## 0.1 What the first dry-run changed (2026-10-14, after ~$0.007 of 13 calls)

The v2 instrument below was built, tested (197 tests) and dry-run. **It aborted:** 0 of 7 `covered` watch pairs typed
`stated`, and the three gated agent pairs (m10, p19, p72) came back `one_step` with an empty addition list. Twelve of
thirteen pairs were `one_step`; exactly one segment in the whole run was `stated`. Three consequences, all carried
into the sections below:

- **The holistic `relation` field was where the collapse happened (v4).** The model now *extracts* `adds` — the parts
  of a segment the sentence does not have at all, each with its kind — and code derives `absent` from `adds` being
  non-empty. `relation` is reduced to `stated | one_step` and is read only when `adds` is empty. The prompt carries an
  anti-renaming clause: *a different word for something the sentence already states is not an addition.*
- **[Markim] M7: D2 is flipped.** The headline view is **lenient**, strict is the second column. The reason is not the
  model: `pair_labels.py`'s own definition of `covered_one_step` says "the same content, **reworded**", while four of
  the 14 gate pairs are labelled `covered` *on rewording notes* (p39, p43, p82, c14 — p43's note reads "'The present
  age' = 'modern society'; the rest is verbatim"), and the labellers split 7/12 at that boundary. The judge was
  implementing the definition the sheet supplies. Four conditions ride with the flip: the strict column is always
  reported; the gate's positive cell becomes the 39 uncontested positives typed non-`absent`; a `covered` pair typed
  `absent` is zero-tolerance (it is also what the abort rule fires on); and every round reports `stated_typings`,
  because a round that never types `stated` makes the strict column **vacuous** rather than good.
- **One instrument bug, found by the run.** C2's lower bound counted `while` as dropped content and forced a `covered`
  pair (p43) to `absent`. Fixed surgically: `textform.DROPPABLE_CONNECTIVES` (while, whereas, though, although,
  besides, also, yet, both, either, neither) may be dropped by `read_as`; the causal and consecutive ones
  (`because`, `therefore`, `thus`, `hence`, `by`, `through`, `leading`) stay non-droppable **by name**, since they are
  families the judge exists to catch and 22 of the 140 claims carry one. Every exemption that fires is logged.

**Measured and rejected, for the record:** a deterministic subject rule (downgrade when the subject's content words
are absent from the sentence) catches all 9 gated agent refs *and* would force 18 of the 25 `one_step` pairs to
`absent`. A `subject_span` field was proposed and dropped too: null is a sentence-side absence while an addition is a
claim-side presence, and p07 (claim subject "It", resolved by the sentence) is the false negative it would produce.
The agent case lives inside `adds` as `kind: agent`.

## 0. Prerequisite: ROADMAP item 48 before any code

Write item 48's section first, carrying: **Status** ("design closed 2026-10-14, build not started"), **What** (this
spec's sections 2-8), **Why (measured)** (section 1), and the correction to item 47's table — the constant-rejecter row
reads **86.4% strict / 68.6% lenient**, not "69% | 69%" (the lenient floor had been copied into the strict cell). The
sentence it supports survives: both judges score below a judge that rejects everything.

## 1. The failure this item exists to fix (measured)

- The judge is one call per `(claim, sentence)` pair asking for a boolean (`judges.pair_prompt`, `PairVerdict`). Against
  the 140 hand labels it passes **46 of 96 `not_covered` pairs** on `gpt-4.1-mini` (**48 union, 43 always** over three
  repetitions) and **62 of 96** on `gpt-4o` (**65 union, 62 always**). Capability runs backwards, as in item 46, so the
  cause is the task.
- Recomputed floors: a judge that rejects every pair scores **121/140 = 86.4% strict** and **96/140 = 68.6% lenient**,
  against the instrument's 51%/65% (mini) and 38%/56% (`gpt-4o`).
- **The error has a shape.** Pairs whose note records a legitimate rewording plus a rider false-pass **10 of 11**; added
  agent/subject **9 of 14** (narrow note read) and **21 of 41** (broad) — a 3x swing from the regex alone, which is why
  the family is a checked-in file (section 6.3). The prompt forbids "generalizes, interprets or adds a cause" and never
  names an agent, a means, a quantity or a modality: three of five error families are not even prohibited.
- **The defect is in production output.** Of the 86 natural pairs (`afterC2_run1`), the labels call **78 `not_covered`,
  4 `covered_one_step`, 4 `covered`**. The instrument passes 44/86; the lenient reference passes 8/86. Per book:
  **the instrument reports 10/37 faithful; the labels say 2/37 lenient, 1/37 strict.**
- Records: `data/eval/item47_faithfulness_gpt-41-mini.json`, `item47_faithfulness_gpt-4o.json`,
  `faithfulness_pair_labels_2.md`, `_mined.md`, `_constructed.md`, `_constructed_2.md` (+ `_constructed_2_intent.json`).
- **Void, and to be marked so:** every faithfulness figure reported before this item, plus the 147 older calibration
  rows (they grade the retired whole-finding judge). **Not in doubt:** the 140 labels, the attribution seat (item 47),
  E (items 44/46).

## 2. Identity and placement

- The faithfulness judge is an **evaluation instrument**, not a runtime gate: `judges.faithfulness` is called by
  `evaluation.faithfulness_evaluator`, never by the graph. Nothing in this item changes what a query returns.
- **Model:** default moves from `gpt-4o` to **`gpt-4.1-mini`**, this commit, on correctness (46 false passes against 62)
  and price (~1/9). New override `PP_JUDGE_MODEL` mirrors `PP_ATTRIBUTION_JUDGE_MODEL`, so reverting is one env var.
- **Self-judging invariant holds:** composer and picker are both `gpt-4o-mini` (`agent.py`), so `gpt-4.1-mini` is legal
  for this seat. A `gpt-5*` name here would need `reasoning_effort="none"` (item 47's langchain trap).
- The judge sees **one claim and one sentence**. Never the passage, never the book, never the other pairs of the same
  finding — D1 is the unit, and it is also the unit the 140 labels encode.
- The verdict **does not leave the LLM**: the relation *is* the judgement (section 3), and code polices self-consistency
  (section 4). This differs from item 44, where `ok` was a function of the fields. Say so in the record: a judge at any
  score proves a classification, not a semantics.

## 3. Schema — extract, then decide (field order is the bias control)

One call per pair. `with_structured_output`, temperature 0. Per segment, fields generate in this order:

1. `segment: str` — a **verbatim slice of the claim**, in claim order. The segments partition the claim (section 4, C1).
2. `read_as: str` — the segment restated as a full proposition, **claim vocabulary only** (the subject borrowed from
   elsewhere in the claim, nothing invented). Checked both ways (C2).
3. `evidence_span: str | None` — a **verbatim substring of the sentence** that states it, or null. Checked (C3).
4. `relation: Literal["stated", "one_step", "absent"]` — **the only judged field, and the only gated one**:
   - `stated` — the sentence alone states it and adds nothing (paraphrase allowed).
   - `one_step` — one obvious rewording or step of abstraction gets you there, with nothing added.
   - `absent` — it needs something the sentence does not contain.
5. `addition_kind: Literal["agent", "cause_means", "consequence", "quantity_generalization", "modality",
   "evaluative", "other"] | None` — **annotation, never gated**, required iff `relation == "absent"`, forced null
   otherwise. Precedent: the attribution judge's `reason`. It is what makes the addition profile (M2) a deterministic
   cross-tab against the families file instead of a manual pass.

The wrapper is `PairJudgement(segments: list[ClaimSegment])`. The word "supported" appears nowhere in the prompt or the
schema. `judge_pair(claim, sentence) -> bool` keeps its signature (strict pass), with `judge_pair_detail` returning the
full judgement.

## 4. The four deterministic checks and the derivation (code, outside the LLM)

All four use the pinned helpers of section 9. Every rewrite is **logged, never silently dropped**.

- **C1 — partition.** `normalize_text` of the concatenated segments, separators only, equals `normalize_text(claim)`,
  and every content word of the claim falls in exactly one segment. Failure -> **one bounded retry**, then the pair
  fails with `pair_error`. This is what stops the rider from being dropped: its words would be unaccounted for.
- **C2 — containment, both ways.** Under `terms_match` (section 9): content words of `segment` ⊆ `read_as` ⊆ content
  words of the claim. The lower bound forbids dropping the rider; the upper bound forbids importing sentence
  vocabulary to make the relation trivially true.
- **C3 — span.** `match_form(evidence_span)` is a substring of `match_form(sentence)`. Failure -> relation downgraded
  to `absent` with an `invalid_span` flag. A non-null span on an `absent` segment is forced null.
- **C4 — derivation.** `strict_pass` = every segment `stated`; `lenient_pass` = no segment `absent`; monotonicity
  asserted (`strict_pass` implies `lenient_pass`); `addition_kind` nulled unless `absent`.
- **Repair is not judgement.** Pairs carrying `invalid_span` or `pair_error` count as **fails in the rate** (never
  excluded — that would hide instrument breakage) and are **excluded from the addition profile**; both counts are
  reported. A round with a high repair rate is not reportable.
- **Relocation counters, reported by reference class** (a raw count fires on legitimate paraphrase): singleton
  decompositions refined to "singleton **and** the claim has a content word unmatched by the sentence"; segments typed
  `stated` whose `evidence_span` omits a content word of `read_as`; C1 retries.

## 5. The prompt

- States the criterion, not a list of prohibitions: the three relations **are** the labels' three classes, named as
  such.
- Names all five addition families found in the notes — **agent/subject, cause or means, consequence, quantity or
  generalization, modality** — plus evaluative qualifiers.
- Carries the **dominance rule** explicitly: a segment the sentence does not contain is `absent` **even when every other
  segment is a perfect rewording**. That is the 10-of-11 failure, written as a rule.
- **Order: instruction block and schema first, the pair last.** The static prefix is then a cache candidate across the
  140 calls and the three repetitions. Unproven until measured (section 10): the provider caches only prefixes above a
  model-specific minimum (commonly cited as 1,024 tokens, in 128-token increments), and the structured-output schema
  sits in the prefix too, which helps. Item 46's ~97% cache hit was measured on calls whose prefix qualified; it does
  not transfer unmeasured.

## 6. Reference data, frozen before the first call

### 6.1 The label set and the two views
`pair_labels.py` is unchanged: 140 pairs, three classes, `reference(labels, "strict"|"lenient")`. **`_content_terms`
stays byte-identical** — it produced every historical count in this spec.

### 6.2 Gate scope (M1/M4)
| row | n | in the gate |
|---|---|---|
| `covered`, uncontested | 14 | **yes** |
| `covered`, disputed (d06-d09, d11 — intent said one_step, review said covered) | 5 | no, reported |
| `covered_one_step` | 25 | yes |
| `not_covered` | 96 | yes |
| doubt-noted (p13, p38, m07, m09, m20, c09, m22, p65) | 8 | yes, reported separately, adjudicated by Markim on failure |

### 6.3 `data/eval/faithfulness_pair_families.json` — 96 refs, 13 gated
One primary family per `not_covered` ref: **13 ratified by Markim** (gate) and **83 advisory** (the other 33 false
passes and the 50 pairs the judge already rejects — they still need a family for the profile).
- **Agent/subject, the zero-tolerance family — its definition, not only its members:** *the sentence's subject is a
  pronoun or an unnamed generic, and the claim names an entity absent from the sentence.* Members: **m10, p19, p72**
  (pure subject substitution) and **p37, p01, p74, m06, p35, c05** (added agent alongside a rider). All nine
  false-pass **6/6** (three repetitions on both models), so all nine are live failure points.
- **Excluded by that definition, on purpose: p11** — its sentence names the ideology where the claim credits the
  spectacle, i.e. a subject *swap*, not an added agent. It false-passes 6/6 and stays advisory. Covering swaps is a
  new, larger family and a new `[Markim]` ruling.
- The 4 uncertains: **m26** cause_means, **p20** rider (secondary: evaluative), **p85** rider, **p55** rider with
  `source: "next sentence"` — the single cross-sentence gloss, folded in rather than given a seventh family; promote it
  only if it recurs (>=3 pairs) in a future label set. At runtime it lands in `other`.
- Each row also stores the missing-content-word count, as the audit behind C4's refined singleton detector.

### 6.4 `data/eval/faithfulness_watch_refs.json` — the paraphrase watch column, as a predicate
Predicate: *an uncontested `covered` pair whose `_content_terms(claim) - _content_terms(sentence)` is non-empty*,
computed once with the **frozen** helper, no stemming. Result: **c03, c14, m27, p39, p43, p68, p82** (7 refs). The
other 7 uncontested positives are mined near-copies (zero missing words) — overlap-selected by construction.
Why it exists: a lexically-read `stated` would pass the near-copies and fail these 7, so `8/14` reads as *lexical
collapse* rather than *weak judge*. For contrast, the 5 disputed carry 3, 5, 7, 5, 3 missing words — M1 removes the
deepest paraphrases from the gate, which is exactly why the column is needed.

## 7. The bar — the 3x3 typing matrix, and nothing else

Each reference class has exactly one correct typing. Scored in **each** of three repetitions.

| reference class (n) | correct typing | bar (M7) |
|---|---|---|
| `covered` + `covered_one_step`, uncontested (39) | anything but `absent` | **>=36/39** — the v1 non-regression floor (it passed 14 + 22) |
| `covered`, uncontested (14) | — | **zero** typed `absent`; `stated` vs `one_step` is reported, never gated; watch refs pair by pair |
| `not_covered` (96) | >=1 `absent` | **>=82/96**; **union over reps <=16**; **zero** false pass on the nine gated agent refs |
| `covered`, disputed (5) | — | reported, never gated (M1) |
| stability | — | **<=5 unstable pairs of 140** |
| `stated_typings` | — | reported every round; all-zero marks the strict column **vacuous** |

**Correction, 2026-10-14 (found while testing the scorer):** the `covered_one_step` row first read "≥22/25 typed `one_step`, ≤4 typed all-`stated`", and those two cannot both hold — the two cells bound the same 25 pairs, so 4 leaking to `stated` leaves at most 21 typed `one_step`. The ≥22 floor exists as non-regression against the v1 instrument, which passed 22 of these 25 with no middle typing at all, so its v2 reading is **lenient**: typed `one_step` or `stated`, never `absent`. The ≤4 leak cell is unchanged and still carries the strict side (DSH's `f + g ≤ 18`).

**Accuracy is a report, never a gate**, and the two numbers can move opposite to the matrix. Proof, recorded here so
nobody re-derives it: with the 14 passing, strict accuracy = `135 + d - g - f` (`f` = `not_covered` strict false
passes, `g` = one-step pairs typed all-`stated`, `d` = disputed typed all-`stated`), so a **passing** matrix at the
ceilings with `d = 0` scores 117/140 = 83.6% — *below* the 121 floor — while a **failing** matrix (13/14 covered,
`f = g = 0`, `d = 5`) scores 139/140 = 99.3%. Report strict and lenient accuracy with their floors (86.4% / 68.6%)
beside them, and that footnote.

**No composite scalar.** The mean of the three per-class rates is rejected on arithmetic, not taste: a
constant-`absent` judge scores (0/14, 0/25, 96/96) = 0.33 and a constant-`stated` judge scores (14/14, 0/25, 0/96) =
0.33 — opposite failure modes, one catastrophic, same number. If a single dashboard number is wanted it is a **product**
number (M2's strict pair rate, or the book count), never a calibration composite.

## 8. What the per-book record carries (M2, M3, and the unpaired denominator)

`faithfulness(record)` keeps returning a per-book dict — `_rows` copies every key except `passed` into the LangSmith
comment, so everything below travels with the score at no cost and `judge_records` inherits it:

- `passed` (unchanged, strict, so `judge_agreement`'s `human_faithful` reader stays correct), `pairs`, `unsupported`.
- `rate` — the strict pair rate, `None` when `pairs == 0` (`passed` is already false via `bool(pairs)`, so an
  all-unpaired book is a hard fail, never a vacuous pass).
- `unpaired` and `coverage = pairs / (pairs + unpaired)`. **Measured gap this closes:** in `afterC2_run1`, 37 judged
  books carry **86 pairs and 15 unpaired claims** (101 claims, coverage **85.1%**, 13 books with >=1 unpaired;
  distribution (pairs, unpaired): 3x(1,1), 2x(1,2), 7x(2,0), 8x(2,1), 17x(3,0)). `faithfulness` loops over `pairs`
  only, so those 15 are judged by nothing and `judge_records` writes no row for them: the rate's denominator excludes
  the producer's own known failures, and routing hard claims to `unpaired` would raise the rate with no quality change.
  **The pair rate alone is not reportable; the rate and the coverage are reported together.**
  *Limitation to write down:* `unpaired` conflates "no single sentence states it" with "the sentence it matched already
  carries another claim" (`agent.py:155-157`), and the record keeps only claim strings. Splitting it is a producer-side
  change (parked). Those 15 claims are also outside every label set on disk, so nothing says whether they over-claim —
  a later mini-labelling job if the producer item needs it.
- `addition_profile` — counts by `addition_kind`, capped (counts and kinds, never full text, or the comment column
  bloats) — plus `invalid_span` and `pair_error` counts.
- `judge_version: 2` — per-book, not only in the run record, so a score sorted across experiments carries its own era.
- `judge_records` rows (M3): add `human_lenient` (the lenient label lives only in the sheets today, so the second
  column is otherwise not re-measurable), key rows **by pair index** (today the per-pair pass is derived from a *set of
  claim strings*, so two pairs sharing claim text in one finding mislabel each other), and inherit `judge_version`.
- `configuration()` (which already imports the model *names*): record `faithfulness_judge_model` and a one-line
  **invariant check** — `judge_model in {system_model, critique_model}` is a recorded violation, turning the docstring
  rule into a checked one.

## 9. `textform.py` — one pinned helper, no consumer churn

`judges.py` must not import `quote_check`: `quote_check.py:9` imports `agent`, `agent.py:17` imports `mcp_tools`, and
`mcp_tools.py:19-24` builds `REGISTRY` and runs `add_parent_child_docs()` **at module import** — importing the judge
would open both Chroma stores.

- Move to `textform.py`: `SOFT_HYPHEN`, `PUNCTUATION_MAP`, `QUOTE_MARKS`, `TRAILING_PUNCTUATION`, `normalize_text`,
  `match_form`, `STOPWORDS`, `_content_terms`.
- `quote_check` imports them **and re-exports them under their current names**, so all four existing importers stay
  untouched: `survey.py:22` (`STOPWORDS`), `theme_batches.py:14` (`match_form`), `evaluation.py:13` (`_content_terms`,
  `book_paragraphs`, `match_form`), `tests/test_quote_check.py:3` (`normalize_text`). `book_paragraphs` and
  `book_passage` stay in `quote_check`: they need the corpus, not the text primitives.
- **New:** `terms_match(a, b)` — token equality **or** shared prefix >= 4 characters — used **only** by C2's two
  containment guards, so a borrowed subject's inflection ("reducing" / "reduces") does not fail the round. A prefix
  rule is loose ("form" / "former"): acceptable for a containment guard, **never** for a verdict. `_content_terms`
  gains no stemming.

## 10. Dry-run before the round (13 pairs, ~$0.01)

Final prompt text, one repetition, weighted to the boundaries the gate turns on:
- the **7 watch refs** (c03, c14, m27, p39, p43, p68, p82) — does the span requirement survive paraphrase;
- **m10, p19, p72** — the three pure subject substitutions, the sharpest points of the zero-tolerance family;
- **p62** — an added means relation;
- **p31** — a long multi-clause claim (tiling and singleton stress, em-dashes);
- **p86** — a quote-heavy sentence with curly quotes and an embedded heading (normalization stress).

Read off the responses: `prompt_tokens`, `completion_tokens`, `prompt_tokens_details.cached_tokens`, C1 retries,
singleton rate, `invalid_span` count, and the three relations per pair. That one run fixes the cost line, settles
whether the cache refund books, and says whether the paraphrase boundary is reachable at all.

## 11. Calibration protocol

- All 140 pairs, three repetitions, temperature 0, `gpt-4.1-mini`, production prompt via `judges.pair_prompt` (never a
  copy — item 47's rule).
- Scored as the section 7 matrix, per repetition, plus: union and always counts on `not_covered`; the watch column per
  pair; the disputed and doubt-noted rows; proposition-set instability across repetitions; repair counts.
- **Abort rule: threshold 1.** The first `absent` segment on an uncontested `covered` pair makes the round
  **unreportable** — but the calls finish, because the negative-side diagnostics are what the prompt revision needs.
  Cap the report, not the calls.
- If instability exceeds 10 pairs, *then* consider a cached decomposition pass (+1 call/pair) — calibration-only, since
  production is always fresh; production's stability mechanism is C1-C3.
- Records: `data/eval/item48_faithfulness_v2_<model>_rep{1,2,3}.json`, plus the dry-run record.

## 12. Cost, and the ceiling

Derived from this project's own measurements (~$0.43 per Mtok input on `gpt-4.1-mini`, from ~$0.03 per 140-call round
at ~0.5k input), not from a price list:

| | estimate |
|---|---|
| dry-run, 13 pairs | **~$0.01** |
| one 140-pair round, uncached | **$0.08-0.13** (instructions +$0.024-0.054; output ~150-250 tokens/call, the one assumption left) |
| three repetitions | **$0.25-0.40** |
| **phase ceiling (M5)** | **~$1.00** — dry-run + one round + one prompt revision + slack |

Cached line booked as unproven (section 5). Actual-versus-estimate is reconciled in item 48's record before any
revision round is authorized; if the first round misses the matrix twice, the loop reopens instead of spending.

## 13. Build order

0. **ROADMAP item 48** (section 0) — before any code.
1. `textform.py` + re-export + `terms_match` (section 9). `162/162` tests must still pass, untouched.
2. Freeze `faithfulness_pair_families.json` (M6) and `faithfulness_watch_refs.json` (predicate) — data, no code.
3. `judges.py`: schema, prompt, the four checks, the derivation (sections 3-5). `judge_pair` keeps its boolean
   signature; `judge_pair_detail` is the new entry point.
4. `faithfulness()`'s per-book record, `judge_records` rows, `PP_JUDGE_MODEL`, `configuration()`'s invariant check
   (section 8) — **same commit as 3** (M3: one row migration, not two). Update `tests/test_judges.py` (its `_judge`
   stub and its exact row-key/`{"passed": ...}` assertions) and add deterministic tests for C1-C4, `terms_match` and
   the matrix scorer — all free, no API.
5. Dry-run (section 10). Read, then decide whether to proceed.
6. The three-repetition round (section 11) against the matrix.
7. Item 48's ROADMAP record: the matrix per repetition, the watch column, the corrected floors, coverage, the cache
   verdict, and actuals against section 12.

## 14. Limits recorded, not fixed here

- After M1 the strict positive class is 14 pairs, of which **8 are mined near-copies, 2 constructed and only 4 are
  unbiased production output** (the mined 8 are real output, selected by claim-sentence word overlap). `14/14` is not
  "the judge is good on our output"; it is "the classification holds on 14 positives, 7 of them paraphrastic".
- 13 of 140 pairs carry a recorded hesitation (5 disputed + 8 doubt-noted), 11 of them positives under some view, so
  the achievable ceiling is bounded by label noise.
- Subject *swaps* (p11) are outside the gated family by definition; so are the 15 unpaired claims, and the two causes
  behind them.
- `terms_match`'s prefix rule is deliberately loose, and confined to C2.
- **The product is not fixed by this item.** A calibrated instrument reports ~1-2/37 books and 85.1% coverage instead
  of 10/37. The quality fix is the producer item (claims sized to their sentence, or the composer emitting the
  supporting span with each claim) — parked by D3, and from then on measurable **with no new hand labels**, which is
  what this item buys.
