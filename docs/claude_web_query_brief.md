# Brief for Claude web: decomposing a theme into ParallelProse theses and queries

Paste this before asking Claude web to turn the themes you want to investigate into something
ParallelProse can actually run. Claude web's job is the full decomposition — theme into one or
more theses, each thesis sliced into queries — not just a single query suggestion.
Everything below exists because Claude web's instincts come from its own read of the books'
general reputations, with no knowledge of what ParallelProse's retrieval, grounding, or synthesis
can actually act on.

## What ParallelProse actually is

A two-book comparison system, not a general research assistant. Given one literal query, it:

- Runs that exact query against both books independently (same wording for both — there is no
  per-book query rewriting or vocabulary bridging).
- Composes an answer as agreement / disagreement / each book's unique finding, each finding backed
  by a verbatim quote.
- Critiques itself per book (does the retrieval actually support this, or is it thin?) and, if a
  book's retrieval looks like a wording miss, automatically retries that book alone with a
  narrowed query — but only if the first query was close enough to recover from.
- Can be run as a series of queries sharing one fixed thesis. The thesis never reaches
  retrieval or grounding; a separate, later step (`synthesize`) weaves several already-answered
  queries into one narrative relative to it, and flags parts of the thesis nothing has
  touched yet.

## The three levels: theme -> thesis(es) -> queries

- **Theme** — whatever you're handed, informal, yours to state however you like. Not run as-is.
- **Thesis (the "broad idea")** — one bounded, declarative sentence derived from the theme: what
  the two books can be shown to claim about it, in common or in conflict — ParallelProse's fixed
  north star for a whole series of queries. A theme can require more than one thesis (see the
  split test below) — when it does, each thesis becomes its own separate series, with its own
  queries, run and synthesized independently of the others.
- **Query** — a single, targeted, non-compound question, one narrow slice of its thesis. Never
  attempts to answer the whole thesis in one shot.

Every thesis and every query in the file is run. Nothing is chosen by hand: the batch runner
takes the whole file as the set of series to run, one theme at a time.

## What makes a thesis usable

1. **A real point of contact, not just a shared subject** — the same bar a query has to clear
   (below), one level up. "Both books discuss society" is too thin even as a thesis; "both
   books can be read as describing a kind of self-presentation that substitutes for direct
   experience" is a real point of contact two authors can plausibly be shown agreeing or
   disagreeing about.
2. **The common-throughline test — the split signal.** Before finalizing one thesis, check: do
   all of its queries' answers plausibly weave into *one* coherent narrative? If the theme is
   pulling toward two threads that wouldn't share a throughline even in principle, that's not one
   broad idea needing more queries — it's two theses. Split them rather than forcing a single
   overbroad one; a `synthesize` narrative built across unrelated threads is incoherent by
   construction, not just imprecise.

## What makes a query usable

1. **Targeted, not survey-style — and the thesis is not the query.** "What does this book
   cover?" or "what are the themes of X" cannot be answered — ParallelProse only does specific,
   answerable questions against retrieved passages, not open-ended summaries of a book's scope.
   Each query must be one narrow, targeted slice of its thesis, never an attempt to answer the
   whole thesis in one shot.
2. **Single-themed, not compound.** A query joining two asks with "and" (e.g. "how is time
   experienced, and what shapes that experience") is two targeted questions wearing one. It
   doesn't trip any known bug — but it dilutes retrieval relevance (a chunk strong on one clause
   competes against chunks mediocre on both), compresses two distinct critiques into one `reason`
   field per book, and — the reason it matters most here — produces a confounded unit of evidence:
   `synthesize`'s gap-finding can no longer tell whether a part of the thesis was cleanly tested or
   only ever tested jointly with another one. Slice a compound ask into two separate queries (two
   bites) instead.
3. **A real point of contact, not just a shared subject.** Both books touching the same broad
   topic is not enough — the system flags disagreement only when both books make a claim about the
   *same specific part* of it. Prefer queries where it's plausible both authors assert something
   comparable, not just adjacent.
4. **Wording matters, and ParallelProse's own retry only narrows reactively after a retrieval
   round, within the same framing as the original query.** It can't invent a different entry point
   into a query before the first round ever runs, and has no advance knowledge of either book's own
   vocabulary. Phrase each query once, using the words each book itself is likely to use, not one
   neutral modern voice — or, when one book's vocabulary is the only one that fits, as a twin pair
   (below). ParallelProse's retrieval is half literal keyword matching, so a wording that only
   paraphrases in the modern register gives the older book no real second attempt.
5. **An anachronistic or period-specific trigger term needs translating before it's queried, not
   querying literally.** A modern term with no period equivalent (e.g. "social media") will return
   nothing from an older book even if that book addresses the same underlying pattern under a
   different form. Name the *structural role* the term plays first (a venue where many watch one
   curated performance at once, for status or vicarious participation) and phrase the query around
   that role, in each book's own language, rather than the literal modern term.

## Vocabulary: match each book's own words

Retrieval is largely literal keyword matching, and two books on the same subject often use different
words for it. A query worded in one neutral voice fits the book whose words it happens to share and
misses the other. Before writing a query, work out what each book would call the concept:

- Name the concept in neutral terms first, so you know what the query is about.
- For each book, write the words that book itself would use for it: its nouns for concrete things,
  its technical terms for abstract ones, and its own spellings and inflections.
- If you cannot name a book's words for a concept with confidence, say so in your reply and mark the
  query as a twin candidate. Do not guess a book's vocabulary and present it as known.

Choose the query shape by what the two books share:

| The books' vocabulary for the concept | Query shape |
|---|---|
| Both use the same words | One untagged query, in those shared words |
| Only one book's words fit | A twin pair, tagging the book whose words fit |
| Both books have the concept, in different registers | A twin pair, each in its own register, same intent |

Cautions that hold for any pair of books:

- A word can mean something different in each book. Before choosing a word, check which sense the
  target book uses, since the other sense can pull in the wrong passages.
- Match inflections and archaic forms. A modern paraphrase, or a different tense or verb form, can
  miss a passage that is in the text as written.
- When the exact wording of a passage is known and matches the edition in use, phrase the query with
  that wording. A query that describes the scene instead of quoting its wording tends to return the
  right passage, but a neighbouring sentence as the quote.
- Do not build a query from a remembered quotation unless you can check its wording against the
  edition in use. A remembered wording that differs from the edition will miss. A concept phrased in
  the book's own words is the safer fallback.

## Twin queries: one intent, one wording per book

Use a twin pair when the intent is about a concrete addressee, object, or scene that only one book's
vocabulary names, so the other book's wording would miss. Each twin is its own query under the same
thesis, written in the tagged book's words. The tag goes right after the letter, in square brackets,
before the colon: `Query 1.1a[A]:` for book A's wording, `Query 1.1b[B]:` for book B's.

The tag is read only by the batch runner. The text after the colon is sent to retrieval exactly as
written, and both books are still searched with it. The stored result keeps both books' findings
for that query. When the runner builds the synthesis, it passes only the tagged book's findings for
that query, and drops the shared agreement and disagreement. A twin is therefore worth writing when
its tagged side is the side you want the synthesis to draw on.

- Write both halves of a pair when both books have something to say about the intent.
- Write only the tagged half when only one book does.
- A query whose vocabulary both books share stays untagged, as a single query. Both books' findings
  are kept.

## What to hand back

One document for the whole batch, with every theme in it, shaped like this:

```
Theme 1: <title, as given>

Thesis 1.1: <one bounded, declarative sentence>
  Query 1.1a: <single-themed, targeted query>
  Query 1.1b: <...>
  Query 1.1c[A]: <twin, in book A's words>
  Query 1.1d[B]: <twin, in book B's words, same intent>

Thesis 1.2: <one bounded, declarative sentence>
  Query 1.2a: <...>

Theme 2: <title, as given>

Thesis 2.1: <...>
  Query 2.1a: <...>
```

Rules:
- Plain text only. No bold, headers, bullets, or code fences.
- Each theme, thesis, and query is one line.
- Each theme starts with `Theme N:`. Theme numbers follow the order in the file. The number of themes is not fixed.
- Each thesis starts with `Thesis N.M:`, where N is its theme's number and M counts its theses within that theme, starting at 1. The label is the thesis's unique ID, so every thesis in the file has its own.
- Each query starts with `Query N.Ma:`, where N.M is its thesis's label and the letter a, b, c, ... counts its queries within that thesis. Every query label is unique in the file, so `Query 2.1a:` is always the first query of Theme 2, Thesis 1, and never repeats a label used under another thesis.
- A twin query puts its book tag between the letter and the colon: `Query N.Ma[A]:` or `Query N.Ma[B]:`. Untagged queries keep the plain `Query N.Ma:` form.
- Exactly one query per letter. No alternates or variants. A twin pair is two letters under the same thesis, each with its own tag.
- Add a second thesis to a theme only if the theme failed the common-throughline test. If a theme needs only one thesis, write only `Thesis N.1:`.

Not a flat batch of unrelated ideas: every query traces to one thesis, and every thesis traces to its theme.
