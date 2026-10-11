import json
from pathlib import Path

from ParallelProse.catalog import CATALOG
from ParallelProse.quote_check import context_window


def build_witness_view(consolidated_path: Path) -> Path:
    """Reads a session's <session>_thesis.json and writes witness_view_<project>_<session>.json beside it: one
    record per book per query, carrying only testimony (the quote, its provenance, the finding) — never the
    system's own comparison (agreement/disagreement/needs_revision), which the next reader must not inherit."""
    data = json.loads(consolidated_path.read_text())
    manifest = json.loads((consolidated_path.parent / "manifest.json").read_text())
    session, project, books = data["session"], manifest["project"], data.get("books") or {}

    records = []
    for thesis in data["theses"]:
        for bite in thesis["bites"]:
            for finding in bite["answer"]["unique_findings"]:
                cid = finding["corpus_id"]
                quote = finding["quote"]
                records.append({
                    "bite_id": bite["bite_id"][cid],
                    "session": session,
                    "query_code": bite["code"],
                    "query": bite["query"],
                    "corpus_id": cid,
                    "edition": books.get(cid),
                    "retrieval": {
                        "label": bite["retrieval"][cid]["label"],
                        "side_is_target": bite["side_is_target"][cid],
                        "lineage": bite["retrieval"][cid]["lineage"],
                    },
                    "quote": quote,
                    "verification": bite["verification"][cid],
                    "quote_selection": bite["quote_selection"][cid],
                    "context_window": context_window(CATALOG[cid], quote) if quote else None,
                    "finding": finding["finding"],
                })

    out = consolidated_path.parent / f"witness_view_{project}_{session}.json"
    out.write_text(json.dumps({"session": session, "project": project, "records": records},
                              indent=2, ensure_ascii=False))
    return out
