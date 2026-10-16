"""Token basis for the item 53 verification round's embedding cost (CC-18).

Why this file exists. The pre-registration quoted "398 tokens" and "US$ 0,00000796" with no artifact on disk, and
a number with no protocol in the file is a prediction, not a measurement (the ledger pattern the stage has been
catching all along). This script counts the tokens of the SAME 40 probes the round will embed, and writes the
count with its encoding, its model and its rate beside it.

Cost: zero -- no API call, the probes are read from the saved exact round.
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import date
from pathlib import Path

import tiktoken

DATA = Path(__file__).resolve().parents[2] / "data" / "eval"
SOURCE = DATA / "g2_exact_round_2026-10-16.json"
MODEL = "text-embedding-3-small"  # the OpenAIEmbeddings model in retrieve.py:64-65
ENCODING = "cl100k_base"         # the encoding the item 52 round reconciled its 4.079 tokens with
RATE_USD_PER_MILLION = 0.02     # docs/stage2_g2_proposal_2026-10-16.md, secao 6 (Custo)


def main() -> int:
    probes = json.loads(SOURCE.read_text())["probes"]
    encoding = tiktoken.get_encoding(ENCODING)
    rows = [{"key": key, "probe": entry["probe"], "tokens": len(encoding.encode(entry["probe"]))}
            for key, entry in sorted(probes.items())]
    tokens = [row["tokens"] for row in rows]
    total = sum(tokens)
    out = {"what": "the embedding token basis of the item 53 verification round (40 probes), counted, not estimated",
           "date": str(date.today()), "source": SOURCE.name, "model": MODEL, "encoding": ENCODING,
           "rate_usd_per_million": RATE_USD_PER_MILLION, "rate_source": "docs/stage2_g2_proposal_2026-10-16.md secao 6",
           "probes": len(rows), "distinct_probes": len({row["probe"] for row in rows}),
           "tokens": {"total": total, "min": min(tokens), "median": int(statistics.median(tokens)), "max": max(tokens)},
           "cost_usd": round(total * RATE_USD_PER_MILLION / 1e6, 11), "rows": rows}
    dest = DATA / ("g2_probe_tokens_" + str(date.today()) + ".json")
    dest.write_text(json.dumps(out, indent=1))
    print("saved", dest)
    print("probes", out["probes"], "| distinct", out["distinct_probes"], "| tokens", out["tokens"],
          "| cost US$", out["cost_usd"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

