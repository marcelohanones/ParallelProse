import json
import sys
from collections import Counter
from pathlib import Path

SILENT = "query content is absent"
THRESHOLD = 0.20


def classify(answer: dict) -> str:
    silent = {f["corpus_id"] for f in answer["unique_findings"] if f["finding"] == SILENT}
    if not silent:
        return "both"
    if silent == {"A", "B"}:
        return "neither"
    return f"one-sided ({next(iter(silent))} silent)"


def one_sided_report(session_dir: Path) -> dict:
    counts = Counter()
    for thesis_file in sorted(session_dir.glob("theme-*/thesis-*.json")):
        for bite in json.loads(thesis_file.read_text())["bites"]:
            counts[classify(bite["answer"])] += 1
    total = sum(counts.values())
    one_sided = sum(n for k, n in counts.items() if k.startswith("one-sided"))
    return {"total": total, "counts": dict(counts), "one_sided_share": one_sided / total if total else 0.0,
            "within_threshold": (one_sided / total if total else 0.0) <= THRESHOLD}


if __name__ == "__main__":
    report = one_sided_report(Path(sys.argv[1]))
    print(json.dumps(report, indent=2))
