# Brief for Claude web: decomposing a theme into ParallelProse theses and queries

Paste this before asking Claude web to turn a theme you want to investigate into something
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

Only the single chosen thesis and the single chosen query, for whichever series is currently
running, ever get typed into ParallelProse — nothing else in Claude web's output is kept or
remembered by the system. Every candidate thesis or query not chosen exists only to help you
decide; it leaves no trace once you move on.

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
   vocabulary. Offer 2-3 phrasings per query that genuinely lean toward *each book's own register*
   (not interchangeable rephrasings in one neutral voice) — one variant closer to how the modern
   book itself tends to put things, one closer to the older book's own translated vocabulary.
   ParallelProse's retrieval is half literal keyword matching, so a variant that only paraphrases in
   one register gives the wording-sensitive book no real second attempt.
5. **One book may simply not address it.** If there's real doubt whether *both* books touch what
   the query is actually asking about (not just whether the wording matches), flag that doubt rather than
   proposing it as a confident comparison — ParallelProse has no fix for a book that's genuinely
   silent on a topic; only for a book that's silent *because of wording*.
6. **An anachronistic or period-specific trigger term needs translating before it's queried, not
   querying literally.** A modern term with no period equivalent (e.g. "social media") will return
   nothing from an older book even if that book addresses the same underlying pattern under a
   different form. Name the *structural role* the term plays first (a venue where many watch one
   curated performance at once, for status or vicarious participation) and phrase the query around
   that role, in each book's own language, rather than the literal modern term. If no query can be
   built this way — the structural role itself has no textual anchor in one of the books — say so
   and leave it for `synthesize` to connect across other bites' findings instead of forcing a query
   that will only return silence.

## What to hand back

One structured decomposition, shaped like this:

```
Theme: <as given>

Thesis 1: <one bounded, declarative sentence>
  Query 1a: <single-themed, targeted query>
    variants: <2-3 reworded alternatives, optional>
  Query 1b: ...

Thesis 2 (only if the theme failed the common-throughline test): <...>
  Query 2a: ...
```

Not a flat batch of unrelated ideas — every query traces to one thesis, every thesis traces
to the theme. If the theme only needed one thesis, say so explicitly rather than manufacturing a
second one for coverage's sake.
