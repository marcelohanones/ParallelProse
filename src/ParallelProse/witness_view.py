import json
from pathlib import Path

from ParallelProse.catalog import CATALOG
from ParallelProse.quote_check import book_passage


def build_witness_view(consolidated_path: Path) -> Path:
    """Reads a session's <session>_thesis.json and writes witness_view_<project>_<session>.json beside it: one
    record per (claim, sentence) pair per book, carrying only testimony — the claim, the verbatim sentence that
    states it, the passage it came from, and their provenance — never the system's own comparison
    (agreement/disagreement/needs_revision), which the next reader must not inherit. The passage is the evidence
    unit; the sentence is the most direct line in it. A silent book still gets one record, with E's P as its claim
    and no sentence."""
    data = json.loads(consolidated_path.read_text())
    manifest = json.loads((consolidated_path.parent / "manifest.json").read_text())
    session, project, books = data["session"], manifest["project"], data.get("books") or {}

    records = []
    for thesis in data["theses"]:
        for bite in thesis["bites"]:
            findings = {f["corpus_id"]: f for f in bite["answer"]["unique_findings"]}
            for cid, record in bite["retrieval"].items():
                finding = findings.get(cid) or {}
                common = {
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
                }
                pairs = finding.get("pairs") or []
                if not pairs:
                    records.append({"bite_id": None, **common, "sentence": None, "verification": None,
                                    "passage": None, "claim": record.get("P") or finding.get("headline")})
                    continue
                for n, pair in enumerate(pairs):
                    records.append({"bite_id": bite["bite_id"][cid][n], **common,
                                    "sentence": pair["sentence"],
                                    "verification": bite["verification"][cid][n],
                                    "passage": book_passage(CATALOG[cid], pair["sentence"]),
                                    "claim": pair["claim"]})

    out = consolidated_path.parent / f"witness_view_{project}_{session}.json"
    out.write_text(json.dumps({"session": session, "project": project, "records": records},
                              indent=2, ensure_ascii=False))
    return out
