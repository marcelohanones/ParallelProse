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
