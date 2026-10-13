# Brief for writing the golden set

This brief tells you how to extend the golden set for one pair of books: a JSON file named
`golden_set_<project>.json`, where `<project>` is the pair's project name. The two books are called `A` and `B`
throughout, as in the query brief (`docs/claude_web_query_brief.md`), which this brief builds on.

## What we are asking for

The golden set already exists with **16 entries, `g01` to `g16`**. Your job is to **extend it to exactly 40** by
writing entries `g17` to `g40`, and to hand back the **complete file**: the 16 existing entries unchanged, followed
by your 24 new ones.

The 16 existing entries are already scored against recorded runs. Changing one — its id, query, anchors or labels —
invalidates those records, so leave them byte for byte as they are. Adding entries is safe: the harness hashes the
whole set to name its dataset, so a longer set gets its own dataset and the older results stay comparable.

## What the golden set is for

ParallelProse answers one query at a time: it searches both books, labels each book `ok` (it found a passage that
addresses the query) or `silent` (the book does not address it), and writes a finding and a quote per book. Until now,
whether a run was right was decided by a person reading its output.

The golden set fixes that. It is 40 questions whose right outcome is decided in advance: for each book, which label it
should get and which passage it should find. Every evaluation run asks the same 40 questions and is scored against
those expectations automatically. This is what the scores are used for:

| #  | The evaluation must show                                                                                      |
|----|---------------------------------------------------------------------------------------------------------------|
| E1 | Whether a configuration change (chunk size, retriever preference) finds the right passages more or less often |
| E2 | Whether a book is labelled `silent` exactly when it does not address the query                              |
| E3 | Whether failures come from wording (the query's words vs. the book's) rather than from retrieval itself       |
| E4 | Whether known misses are still missed                                                                         |
| E5 | Whether the same passages come back for unrelated questions                                                   |
| E6 | Whether findings are faithful to their quotes and credited to the right book                                  |
| E7 | That two runs can be compared at all: same questions, same ids, every time                                    |

Every rule below serves one of these. Your file is checked automatically before any run uses it; rules marked
**(checked)** reject the file when broken. You cannot run those checks yourself, so follow them as written; if the
file is rejected, you get the list of problems back (see "What to hand back").

## The file, complete

The file is one JSON list of exactly 40 entries, `g01` to `g40` in order. These four entries show the four kinds of
entry you will write; they are numbered `g17` onward because `g01`–`g16` already exist. Text in angle brackets
describes what goes there.

```json
[
  {
    "id": "g17",
    "theme": "<short theme name>",
    "query": "<a targeted question, in the words both books use for the idea, that a passage in each book answers>",
    "side": null,
    "specificity": "abstract",
    "wording": "book",
    "known_failure": false,
    "expected": {
      "A": {
        "label": "ok",
        "anchors": [
          "<4-12 words copied exactly from A's answering passage>"
        ],
        "min_hits": 1
      },
      "B": {
        "label": "ok",
        "anchors": [
          "<4-12 words copied exactly from B's answering passage>"
        ],
        "min_hits": 1
      }
    },
    "note": "<why each passage answers the query>"
  },
  {
    "id": "g18",
    "theme": "<short theme name>",
    "query": "<a question, in neutral modern words, whose answer in A is spread over several passages>",
    "side": "A",
    "specificity": "specific",
    "wording": "paraphrase",
    "known_failure": false,
    "expected": {
      "A": {
        "label": "ok",
        "anchors": [
          "<4-12 words from A's first passage>",
          "<4-12 words from A's second passage, far from the first>",
          "<4-12 words from A's third passage>"
        ],
        "min_hits": 2
      },
      "B": {
        "label": "silent",
        "near_miss": true,
        "absent_terms": [
          "<B's own word for the idea>",
          "<the query's word>"
        ]
      }
    },
    "note": "<why the three passages answer it; for B: the other words searched, and the adjacent passage B does have>"
  },
  {
    "id": "g19",
    "theme": "<short theme name>",
    "query": "<a question neither book addresses under any wording>",
    "side": null,
    "specificity": "abstract",
    "wording": "paraphrase",
    "known_failure": false,
    "expected": {
      "A": {
        "label": "silent",
        "near_miss": false,
        "absent_terms": [
          "<term>",
          "<term>"
        ]
      },
      "B": {
        "label": "silent",
        "near_miss": false,
        "absent_terms": [
          "<term>",
          "<term>"
        ]
      }
    },
    "note": "<for each book: the words and structural equivalents searched, and that none of them address the idea>"
  },
  {
    "id": "g20",
    "theme": "<short theme name>",
    "query": "<the query, word for word, from the run where the miss happened>",
    "side": "A",
    "specificity": "specific",
    "wording": "book",
    "known_failure": true,
    "expected": {
      "A": {
        "label": "ok",
        "anchors": [
          "<4-12 words from the passage that run failed to find>"
        ],
        "min_hits": 1
      },
      "B": {
        "label": "silent",
        "near_miss": false,
        "absent_terms": [
          "<term>",
          "<term>"
        ]
      }
    },
    "note": "<the session where it failed, and what the run returned instead>"
  }
]
```

What each example shows:

- **g17**: both books `ok`, each with a single answering passage (one anchor). The most common kind.
- **g18**: a *scattered* answer. A's answer is spread over several passages, so A gets 3 anchors and `min_hits: 2`
  (the run must find at least 2 of them). B is a *near miss*: B discusses something adjacent but not this.
- **g19**: both books silent. This checks that the system does not invent an answer when neither book applies.
- **g20**: a known failure: a query the system already missed in a past run, kept so the evaluation shows whether
  it is still missed.

## The fields

| Field                | What to write                                                                                                                                                                                                                                                                                                      |
|----------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `id`                 | `g01` to `g40`, in order. **(checked)** unique. Once a run has used an id, it never changes, even if you rewrite the entry.                                                                                                                                                                                        |
| `theme`              | A short name for the entry's theme. Used only to count themes (see "Set composition").                                                                                                                                                                                                                             |
| `query`              | One targeted, single-themed question, following the query brief ("What makes a query usable"). **(checked)** it never contains either author's surname: the same text is searched in both books, and a name only adds noise.                                                                                       |
| `side`               | `null` when both books share the query's vocabulary; `\"A"` or `\"B"` when the query is written in one book's words. Same meaning as the query brief's twin tag `[A]`/`[B]`.                                                                                                                                         |
| `specificity`        | `\"specific"`: the answer is a named person, place, event, work, or a term the book itself defines. `\"abstract"`: the answer is an idea, a cause or a judgment.                                                                                                                                                     |
| `wording`            | `\"book"`: the query uses the book's own words for the idea, without quoting the passage. `\"paraphrase"`: neutral, modern words. **(checked)** a `\"paraphrase"` query shares no word with any of the entry's anchors (words of 3 letters or more, not counting common function words like *the*, *which*, *would*). |
| `known_failure`      | `true` only for a query a past run is known to have missed.                                                                                                                                                                                                                                                        |
| `expected`           | Exactly one expectation for `A` and one for `B` **(checked)**, each `ok` or `silent` as below.                                                                                                                                                                                                                     |
| `ok` expectation     | `\"label": "ok"`, `anchors`, `min_hits`. A single answering passage: 1 anchor, `min_hits: 1`. A scattered answer: 2 to 5 anchors, `min_hits` from 2 up to the number of anchors. **(checked)**                                                                                                                      |
| `silent` expectation | `\"label": "silent"`, `near_miss` (`true`/`false`), `absent_terms` (2 to 5 terms). No anchors. **(checked)**                                                                                                                                                                                                        |
| `note`               | Required on every entry **(checked)**. Says why each expectation holds; for a silent book, what "Silent books" below asks for.                                                                                                                                                                                     |

## Anchors

An anchor is a short phrase copied from the passage that answers the query. A run passes a book's `ok` expectation when
the passages it retrieved for that book contain at least `min_hits` of the anchors.

1. **Copy anchors only from text that comes from the edition in use**: a quote marked verified in a past run's
   output, or passage text you were given from the book. Never write an anchor from memory or from another
   translation. A remembered wording that differs by one word never matches. **(checked)** the anchor is found in
   the book. Case, quotation marks, dash types and line breaks are ignored; every other character, spelling and
   punctuation included, must match.
2. 4 to 12 words **(checked)**: long enough to occur once in the book, short enough to sit inside any retrieved passage.
3. From inside one paragraph; never across a paragraph break. **(checked)**
4. Occurs only once in its book. If a phrase recurs, take a longer stretch of the same sentence. **(checked)**
5. Not quoted by the query: the query and the anchor never share 4 words in a row. **(checked)**
6. The words that carry the answer, the ones a reader would underline, not an incidental phrase near them.
7. Scattered answers: each anchor from a different paragraph, and at least two of them far apart in the book:
   different chapters, or several pages apart within one. **(checked)** at least two anchors are 5,000 characters or
   more apart.
8. **A paragraph is used by at most one entry per book**, across the whole set — including the 16 entries that already
   exist. A passage counted twice weighs double in the score. **(checked)** The anchors already in use are listed in
   the appendix: do not reuse them, and do not anchor a new entry inside the paragraph any of them came from.

## Silent books

1. `silent` means the book does not address the *idea* under any wording, not that the query's words are missing. A
   modern word absent from an older book is not silence if the book treats the same pattern in its own vocabulary (query
   brief, "What makes a query usable", rule 5).
2. `absent_terms`: 2 to 5 words or short phrases that never occur in the book. **(checked)** At least one is the word
   the book itself would use for the idea, not only the query's word.
3. `note` lists the other words and structural equivalents you considered, and why none of them address the idea.
4. `near_miss: true` when the book discusses an adjacent topic but not the claim asked; `note` then names that adjacent
   passage. A near miss is the hard test: the system has related text in front of it and must still answer `silent`.

## Set composition

The 40 entries together must fill every row below. **(checked)** One entry can count toward several rows at once.
The 16 existing entries already fill some of every row; your 24 must close the gap.

| Requirement                                                                                                                 | Minimum              | Serves |
|-----------------------------------------------------------------------------------------------------------------------------|----------------------|--------|
| Entries                                                                                                                     | exactly 40           | E7     |
| Both books `ok`                                                                                                             | 20                   | E6     |
| `A` ok, `B` silent                                                                                                          | 8                    | E2     |
| `A` silent, `B` ok                                                                                                          | 8                    | E2     |
| Both books silent                                                                                                           | 4                    | E2     |
| Silent expectations with `near_miss: true`                                                                                  | 2 per book           | E2     |
| `ok` expectations per book, in each of four cells: single/specific, single/abstract, scattered/specific, scattered/abstract | 4 per cell, per book | E1     |
| `\"wording": "book"` entries                                                                                                 | 12                   | E3     |
| `\"wording": "paraphrase"` entries                                                                                           | 12                   | E3     |
| `known_failure` entries                                                                                                     | 4                    | E4     |
| Distinct `theme` values                                                                                                     | 20                   | E5     |

A *single* `ok` expectation has one anchor; a *scattered* one has two or more.

## Writing the set

1. **Plan the 24 new slots first.** Work out what the existing 16 already cover, then assign each new slot its label
   combination, cell, `wording` and theme so that together the 40 fill every row of "Set composition". Write the
   entries to that plan.
2. **For an entry with at least one `ok` book, start from the passage, not the question.** Pick the passage (or, for a
   scattered answer, the passages) first, from text of the edition in use. Choose the anchors. Then write the query
   the passage answers, at the slot's `wording`, by the query brief's rules, without quoting the anchor.
3. **Then decide the other book.** Look for the same idea in it, in its own words and by structural equivalents. If
   it has a passage, that passage gets its own anchors. If not, the book is silent: fill `absent_terms` and `note`.
4. **For a both-silent entry**, start from the question and make the case for silence in each book.
5. **For a known-failure entry**, take the query word for word from the run where it was missed. The anchors come
   from the passage that run failed to find. Two known failures already exist (`g07`, `g08`, `g09` in the appendix
   list the historical misses); the remaining slots can be new ones you have evidence for, or further instances of
   the same kind.

## What the golden set does not carry

- **Reference answers.** Faithfulness and attribution are judged on each run's own findings, quotes and passages.
- **A thesis.** Golden queries run alone; no thesis is involved.
- **Settings.** Which configuration a run uses is chosen per run, not in this file.
- **An expected quote.** The score uses the passages retrieved and the label, not which sentence the system quotes.

## What to hand back

The JSON file and nothing else: one list, exactly 40 entries, `g01` to `g40`, with `g01`–`g16` unchanged from
the copy you were given. No commentary inside it; JSON has no comments, and your reasoning belongs in each entry's
`note`.

If the file is rejected, you receive a list of problems, each naming an entry's `id` and, where it applies, a book.
Fix only the named entries and hand the whole file back. Never renumber ids.

## Appendix — anchors already in use

These paragraphs are taken. Do not reuse an anchor below, and do not anchor a new entry inside the paragraph one of
them came from. (Rule 8 under "Anchors".)

**Book A (Confessions):**

  g01: "the baggage of this present world was I held down pleasantly"
  g02: "weeping not his own death for want of love to Thee"
  g02: "the auditor is not called on to relieve, but only to grieve"
  g03: "sight being the sense chiefly used for attaining knowledge"
  g04: "Those two times then, past and to come, how are they"
  g04: "a present of things past, a present of things present"
  g05: "the circuits of the stars, and pass themselves by"
  g06: "did my wretched soul desire; for I had store of better"
  g07: "and our heart is restless, until it repose in Thee"
  g08: "chanting, and oft repeating, Take up and read; Take up and read"
  g09: "observed a poor beggar, then, I suppose, with a full belly, joking"
  g10: "served up the Sun and Moon, beautiful works of Thine"
  g10: "but a mere phantom, and my error was my God"
  g10: "My heart passionately cried out against all my phantoms"
  g11: "a lust served, became custom; and custom not resisted, became necessity"
  g11: "drew along my chain, dreading to be loosed"
  g11: "rolling and turning me in my chain, till that were wholly broken"

**Book B (The Society of the Spectacle):**

  g01: "The spectacle is the guardian of that sleep"
  g02: "The more he contemplates, the less he lives"
  g03: "the sense of sight to the special preeminence once occupied by touch"
  g04: "Cyclical time is already dominant among the nomadic peoples"
  g04: "This irreversible time is the time of those who rule"
  g04: "This pseudocyclical time is in fact merely a consumable disguise"
  g05: "is the opportunity to go and see what has been banalized"
  g06: "The satisfaction that no longer comes from using the commodities"
  g06: "use value now has no existence outside the illusory riches"
  g12: "by means of delegates who are answerable to their base"
  g12: "the only undefeated aspect of a defeated movement"
  g12: "Such councils can be effective only if they transform existing conditions"
  g13: "As specialists of apparent life, stars serve as superficial objects"
  g14: "Separation is itself an integral part of the unity of this world"
  g14: "it reunites them only in their separateness"
  g14: "bringing isolated individuals together as isolated individuals"
  g15: "Plagiarism is necessary. Progress depends on it"
