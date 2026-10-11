# Brief for writing idea units

This brief tells you how to write entries for the idea unit bank, one pair of books at a time: a JSON file named
`idea_units_<project>.json`, where `<project>` is the pair's project name. The two books are called `A` and `B`
throughout, as in the query brief (`docs/claude_web_query_brief.md`) and the golden set brief
(`docs/golden_set_spec.md`).

## What an idea unit is for

The witness view (`witness_view_<project>_<session>.json`) hands you testimony: quotes, where each one sits in
its book, what each book's finding says — never the system's own reading of how the two books relate. An idea
unit is where that relation gets written down, once, as a claim that can be checked rather than merely asserted.
A session writing a script reads only this file, never the witness view and never a session's raw quotes — the
idea unit is what stands between the evidence and the page.

This file is checked automatically before anything reads it. Rules marked **(checked)** reject the file when
broken; one rule **(flagged)** never rejects, only warns. If the file is rejected, you get the list of problems
back; fix only the named entries and hand the whole file back.

## The file, complete

The file is a JSON list, open-ended — it grows one unit at a time as new material is found, unlike the golden
set's fixed 16. This example shows one complete entry. Text in angle brackets describes what goes there.

```json
[
  {
    "id": "u01",
    "type": "convergence",
    "mechanism_a": "<what A asserts happens, in the form: when X, Y happens, because Z>",
    "mechanism_b": "<what B asserts, same form, in B's own words>",
    "form_a": "confession",
    "form_b": "thesis",
    "shared_structure": "<the structure both mechanisms share, in neither book's vocabulary>",
    "divergence_axis": "<the one nameable variable the two mechanisms differ on>",
    "falsification_test": {
      "query": "<a query, phrased exactly like a batch query, that would find the counter-example if one exists>",
      "side": "A"
    },
    "anchoring": ["a1b2c3d4", "e5f6a7b8"],
    "promotion": null
  }
]
```

## The fields

| Field | What to write |
|---|---|
| `id` | `u01`, `u02`, ... — **(checked)** unique. Once used, never changes. |
| `type` | One of four — **(checked)**: `convergence` (both books assert the same mechanism), `divergence` (the shared mechanism is real, but its outcome differs — not a convergence, and not a false positive either), `single_voice` (only one book addresses this at all), `false_positive` (an apparent pair that doesn't actually hold). |
| `mechanism_a` / `mechanism_b` | What that book *asserts happens*, in the form "when X, Y happens, because Z" — restricted to what the passage itself claims, never what the book merely talks about. **(checked)** For `single_voice`, exactly one of the two is set — the side that has no mechanism stays `null`. For every other type, both are required. |
| `form_a` / `form_b` | One of `scene`, `thesis`, `confession`, `diagnosis` — classifies the passage itself, which tells a script how to stage it. **(checked)** Set exactly when the matching `mechanism_*` is set — never one without the other. |
| `shared_structure` | The structure the two mechanisms share, written so it could describe either book without naming either one's vocabulary. |
| `divergence_axis` | The single variable the two mechanisms differ on — a nameable thing, not a list of differences. |
| `falsification_test` | A query, phrased exactly like an ordinary batch query, that would find the counter-example to `shared_structure` if one exists in the declared `side`'s book. **(checked)** Required for every type except `single_voice`. |
| `falsification_single_voice` | What, if found in the silent book, would break the claim that it stays silent. **(checked)** Required only for `single_voice`, and only then — it has no target side, because the test is for absence, not for a specific book's claim. |
| `anchoring` | A list of `bite_id`, never quoted text. **(checked)** Every id must resolve to a real bite whose quote is independently found in its own book — the same check the golden set's anchors pass, with no human countersignature needed. |
| `promotion` | `null` until a falsification round (a future item) registers a null search against this unit's test. When set: `decider`, `null_search_ref`, `date`, all required. Not cross-checked against a real registry yet — this field is a placeholder for when one exists. |

## Anchoring

Cite `bite_id`, not text. Copying a quote into the idea unit would let the unit be written from the quote's own
wording instead of from the mechanism it instantiates — exactly the Alípio problem the form fields exist to catch.
The loader resolves each id to the quote it names (read from every `witness_view_*.json` on disk) and confirms
that quote exists in its own book, the same way `_book_problems` already confirms a golden-set anchor does. A unit
whose `anchoring` id cannot be resolved, or whose underlying quote isn't actually in its book, is rejected outright
— this is not a judgment call, since existence is demonstrable.

## The cross-contamination flag — **(flagged)**, never rejects

When every `anchoring` bite for a unit resolves to the *same* book, `mechanism_a`, `mechanism_b` and
`shared_structure` are searched for a handful of words that belong to the *other* book (its signature vocabulary —
for this project: `spectacle`, `commodity`, `alienation`, `capital`, `image`, `representation` for B; `god`,
`soul`, `sin`, `grace`, `divine`, `spiritual`, `confession` for A). A hit is returned as a flag, not a rejection: a
unit that is genuinely anchored in both books is exempt from this check entirely, since naming both vocabularies is
then expected, not contamination.

## What an idea unit does not carry

- **A theme or thesis pointer.** Traceability runs through `anchoring`'s bite ids, which already identify the
  session and query that produced the evidence; a redundant pointer would only drift out of sync with it.
- **Quoted text.** The quote lives in the witness view; the idea unit carries only the mechanism it supports.
- **A verdict on whether to promote.** `promotion` records *that* a decision happened, naming who and against
  which null search — it is not itself the decision.

## What to hand back

The JSON file and nothing else: a list of entries, each with a unique `id`. No commentary inside it — JSON has no
comments, and `shared_structure`/`divergence_axis` are where the reasoning belongs.

If the file is rejected, you receive a list of problems, each naming the entry's `id`. Fix only the named entries
and hand the whole file back. Never renumber ids.
