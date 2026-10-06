ParallelProse compares what two books say about the same issue. It uses RAG as its retrieval engine: each book is
indexed as its own corpus, and a LangGraph agent retrieves from both, then composes a structured comparison —
agreement, disagreement, and each book's own unique take, each grounded in a verbatim quote from the source.

Architecture notebooks document the design as it evolved, one per version:

- `notebooks/ParallelProse/v1-01-architecture-overview.ipynb`
- `notebooks/ParallelProse/v1-02-mcp-bridge-internals.ipynb`
- `notebooks/ParallelProse/v2-01-comparison-architecture-intro.ipynb`
- `notebooks/ParallelProse/v2-02-comparison-mechanics.ipynb`
- `notebooks/ParallelProse/v2-04-architecture-final.ipynb`

## Running it

```python
import asyncio
from ParallelProse.agent import run_query

result = asyncio.run(run_query("How is time experienced by people, and what shapes that experience?"))
```

`run_query` runs the full retrieve → compose → reflect loop once and returns the final `ReflectionState` as data —
no printing, no side effects beyond that. The two books currently indexed are Saint Augustine's *Confessions*
(era `397`) and Guy Debord's *The Society of the Spectacle* (era `1967`); see `catalog.py` to add or swap books.

## Running a theme batch

A batch file holds themes, each with its theses and queries (format in `docs/claude_web_query_brief.md`). Run it from
the repository root:

```
.venv/bin/python -m ParallelProse.theme_batches data/theme_batches/<batch file>.md
```

The run writes a session folder under `data/theme_batches/<project>/<timestamp>/`, named after the start time, and
prints the path of the consolidated file when it finishes. The session keeps a copy of the batch file as `source.md`.

The batch already writes the consolidated file when it finishes. To rebuild it for an existing session, for example
after a session folder is edited, run:

```
.venv/bin/python -m ParallelProse.consolidate_synthesis data/theme_batches/<project>/<timestamp>
```

It writes `<timestamp>_synthesis.json` into the session folder, with every thesis's synthesis under its theme. Inside
Claude Code, `/consolidate-session <session folder>` runs the same command.

To flatten every thesis file in a session into one list, run:

```
.venv/bin/python -m ParallelProse.consolidate_thesis data/theme_batches/<project>/<timestamp>
```

It writes `<timestamp>_thesis.json` into the session folder. The file opens with a `books` mapping (letter to book
title, taken from the session's `manifest.json`), then a `theses` list where each entry carries its `theme_folder`,
`file`, and the thesis's full contents: `theme`, `thesis`, `bites`, and `synthesis`.

To count how many queries are one-sided (one book silent) in the newest session:

```
.venv/bin/python -m ParallelProse.one_sided "$(ls -td data/theme_batches/<project>/*/ | head -1)"
```

To count a specific session, pass its folder instead. Pauses of 30 seconds between queries keep the run under the
per-minute token limit.

## Example run

Query: *"How is time experienced by people, and what shapes that experience?"*

**Agreement:** Both texts explore the concept of time, emphasizing its subjective experience and how it is shaped
by external factors. They suggest that time is not merely a linear progression but is influenced by human
perception and societal structures.

**Disagreement:** Saint Augustine's work presents time as a complex philosophical concept tied to memory,
expectation, and the divine, whereas Guy Debord critiques modern commodified time, arguing that it is a product of
capitalist society that devalues human experience by reducing time to a series of exchangeable units.

**The Confessions of Saint Augustine (397):** Time is experienced by the soul through memory, present perception,
and expectation of the future, suggesting a subjective and philosophical understanding of time.
> "For these three do exist in some sort, in the soul, but otherwhere do I not see them; present of things past,
> memory; present of things present, sight; present of things future, expectation."

**The Society of the Spectacle (1967):** Time is shaped by commodification in modern society, resulting in a
devalued experience where time becomes a consumable commodity, leading to a disconnection from genuine human
development.
> "Under the social reign of commodified time, 'time is everything, man is nothing; he is at most the carcass of
> time'."

Both books were labeled `ok` by `reflect` — the retrieved passages directly supported each claim above, so no
retry round was needed.
