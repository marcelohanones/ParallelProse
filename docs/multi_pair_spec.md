# Spec — several (claim, sentence) pairs per book (the C change)

Status: design, for sign-off. Nothing here is built yet.

## Why this exists (measured, not assumed)

| Measurement | Result |
|---|---|
| The reader-facing bar — every claim in the finding supported by the printed sentence alone | **1/17** and **1/15** in two runs |
| The same findings against the passage they came from | **12/17** and **9/15** |
| Findings whose claims can each be paired with a single retrieved sentence stating it | **55 of 57 claims, 15 of 17 findings** |

The claim the composer writes is a three-part synthesis (`when X, Y happens, because Z` — that form is written into
the field description). One sentence cannot carry it, so the reader-facing check fails by construction. The material
to carry it piece by piece exists in the passage the model already read.

B anchored the quote to the passage and named the passage as the evidence. C makes each claim carry its own anchor,
so nothing has to be taken on trust from a single sentence.

## The contract it creates

Per book, the reader gets:

1. **a headline** — the book's position on the query, in one or two sentences. **This is the system's summary and is
   not offered as provable by any one sentence.** It replaces today's `claim_in_passage`.
2. **one to five pairs** — each an atomic claim *plus the verbatim sentence from the passage that states it*. Each
   pair is checkable on its own: does this sentence state this claim?

The book's evidence is the passage; the headline states where the book stands; the pairs are the grounded steps
between them.

## Shape

```python
class SentenceClaim(BaseModel):
    claim: str      # the proposition the sentence states — what this sentence says, not a generalization from it
    sentence: str   # verbatim, from the retrieved passage

class CorpusFinding(BaseModel):
    corpus_id: Literal["A", "B"]
    form: Literal["scene", "thesis", "confession", "diagnosis"] | None
    headline: str                 # the book's position; the system's summary, not proof-bearing
    pairs: list[SentenceClaim]    # 1..5
```

`agreement` and `disagreement` keep their meaning and their place in `ComposerAnswer`.

## What changes, file by file

| File | Change |
|---|---|
| `agent.py` | the two fields above; the composer prompt asks for the headline and the pairs, with the pairing rule stated |
| `quote_check.select_quotes` | **retired from the pipeline.** Its job was to rescue a composer that quoted the wrong sentence; under C the sentence is chosen per claim, by construction. The function stays; the call sites go |
| `quote_check.verify_quotes` | checks every pair's sentence, per book, instead of the one quote |
| `theme_batches.save_bite` | stores the pairs and their per-pair verification |
| `theme_batches.compute_bite_id` | one id per pair (it already hashes pair + corpus + quote, with the query as fallback) |
| `witness_view.py` | one record per pair instead of one per book, each carrying its claim, sentence, passage, verification |
| `judges.py` | the faithfulness judge becomes *does this sentence state this claim* — the question it was always trying to ask |
| `evaluation.py` | the golden target's record shape; the label evaluators are untouched |
| tests | the composer, quote check, witness view and theme-batch tests follow the shape |

## Decisions, with a recommendation each

- **D1 — headline plus pairs (recommended) or pairs only?** Pairs only would make the comparison prose harder to
  write and would drop the book's position from the export. The headline keeps the product audible; the pairs keep it
  honest. If the headline proves to be where over-claiming creeps back, that is measurable next.
- **D2 — who picks the sentence: the composer (recommended) or a separate selector?** The composer writes the claim
  and the sentence in one call, so they cannot drift apart — which is exactly how today's mismatch happened.
- **D3 — a pair whose sentence fails verbatim verification: drop the pair, or keep it flagged?** Recommended: keep it
  flagged. The export already carries verification per record, and dropping it would hide a failure the reader should
  see.
- **D4 — `form` stays at book level**, not per pair: it classifies the passage, and the passage is one.

## What it does not change

- E's per-book verdict, and therefore the `ok`/`silent` labels and the golden set's scoring.
- `agreement`/`disagreement` and the rest of `ComposerAnswer`.
- The retrieval side entirely.
- `one_sided`, which counts per book per query, not per pair.

## How it gets validated

- **The pair bar** — for every pair, does the sentence state the claim? This is the check that replaces the
  quote-alone bar, and it is now well-posed: an atomic claim against its own sentence.
- **The passage bar** stays as the ceiling reference (12/17 and 9/15 today).
- **The corpus**: the 40-entry golden set (two runs in flight), ~42–45 findings per run.
- **The before**: the recorded 16-entry runs give a per-side before for the 16 shared entries.

## Risks worth naming

1. **The composer may still generalize.** The rule is now in the field description; whether it is obeyed is exactly
   what the pair bar measures.
2. **Reader load.** Five pairs per book is more than one line. The cap is the mitigation; if it still reads heavy,
   the export can show the headline and one pair by default.
3. **More sentences to verify.** Five sentences per book per query, each checked verbatim — deterministic, but the
   failure mode to watch is a pair whose sentence is real yet says something else, which is the pair bar's job.
