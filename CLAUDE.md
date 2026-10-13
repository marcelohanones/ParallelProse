# State invariants

## State invariant — a skip must forward the whole slot

Any graph node that can choose not to process an item (skip a book, skip a corpus, skip any
per-key unit of state) must still return that item's existing slot in full — never omit it from
the node's returned state.

**Why:** state fields like `corpora` are plain dicts/TypedDicts with no merge rule. Whatever a
node returns under a given key *replaces* the whole thing — it does not patch it. A node that
skips an item and returns nothing for that item doesn't leave it unchanged; it deletes it from
state. Downstream nodes that expect the item to still be there (e.g. `reflect` reading
`state["corpora"]["A"]`) then crash with a `KeyError`, or silently lose that item's chunks and
lineage without any error at all.

This bug shape has already surfaced more than once in this project under different names — a
skip-aware retriever loop, a per-book label update, a per-corpus retry — because it is a standing
risk of this LangGraph state design (full-replace-on-return, no merge), not a one-off mistake in
any single node.

**How to apply:** whenever a node gains a skip/short-circuit branch, the first question to ask is
always "what does this branch return for the item it skipped?" The only correct answer is: the
item's slot, forwarded whole and unchanged — never an omission, never a partial dict missing the
skipped item's key.

## Harness memory

`docs/harness_memory_design.md` records the agreed design for sharing memory between Claude Code and dsh — one writer per file, three layers, measured limits. Read it before changing how either harness stores or loads memory.
