import json
from pathlib import Path

from ParallelProse.catalog import CATALOG
from ParallelProse.quote_check import context_window


def build_witness_view(consolidated_path: Path) -> Path:
    """Reads a session's <session>_thesis.json and writes witness_view_<project>_<session>.json beside it: one
    record per book per query, carrying only testimony (the quote, its provenance, the finding) — never the
    system's own comparison (agreement/disagreement/needs_revision), which the next reader must not inherit.
    The records are enumerated from E's per-book record (bite["retrieval"]), not from the composer's findings:
    a silent book always keeps its record, with E's P (the adjacent proposition) as its finding and no quote;
    any other book carries the composer's claim_in_passage and quote."""
    data = json.loads(consolidated_path.read_text())
    manifest = json.loads((consolidated_path.parent / "manifest.json").read_text())
    session, project, books = data["session"], manifest["project"], data.get("books") or {}

    records = []
    for thesis in data["theses"]:
        for bite in thesis["bites"]:
            findings = {f["corpus_id"]: f for f in bite["answer"]["unique_findings"]}
            for cid, record in bite["retrieval"].items():
                finding = findings.get(cid)
                if record["label"] == "silent":
                    text, quote = record.get("P"), None
                elif finding is not None:
                    text, quote = finding["claim_in_passage"], finding["quote"]
                else:
                    text, quote = record.get("P"), None
                records.append({
                    "bite_id": bite["bite_id"][cid],
                    "session": session,
                    "query_code": bite["code"],
                    "query": bite["query"],
                    "corpus_id": cid,
                    "edition": books.get(cid),
                    "retrieval": {
                        "label": record["label"],
                        "side_is_target": bite["side_is_target"][cid],
                        "lineage": record["lineage"],
                        "silence_cause": record["silence_cause"],
                    },
                    "quote": quote,
                    "verification": bite["verification"][cid],
                    "quote_selection": bite["quote_selection"][cid],
                    "context_window": context_window(CATALOG[cid], quote) if quote else None,
                    "finding": text,
                })

    out = consolidated_path.parent / f"witness_view_{project}_{session}.json"
    out.write_text(json.dumps({"session": session, "project": project, "records": records},
                              indent=2, ensure_ascii=False))
    return out
