"""LLM judges for the evaluation harness (roadmap item 30.3): faithfulness and attribution.

Both judge a target record (evaluation.run_golden_entry), per book that was not labelled silent. The judge model is
not the system's model (agent.py runs gpt-4o-mini), so the system never grades its own output. Neither judge is
trusted until it agrees with hand labels: judge_records writes the verdicts beside empty human fields, and
judge_agreement measures the agreement once those fields are filled.
"""

from dotenv import load_dotenv

load_dotenv()

import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from ParallelProse.catalog import CATALOG, DATA_DIR
from ParallelProse.survey import term_pattern

JUDGE_MODEL = "gpt-4o"
EVAL_DIR = DATA_DIR / "eval"

judge_llm = ChatOpenAI(model=JUDGE_MODEL, temperature=0)


class ClaimCheck(BaseModel):
    claim: str = Field(description="One separate factual claim the finding makes about the book")
    supported: bool = Field(description="True only if the quote alone, read literally, supports this claim")


class FaithfulnessVerdict(BaseModel):
    claims: list[ClaimCheck]


class AttributionVerdict(BaseModel):
    source: Literal["1", "2", "both", "neither"] = Field(
        description="Which set of passages the finding describes: 1, 2, both, or neither")
    reason: str


def _judge(schema: type[BaseModel], prompt: str) -> BaseModel:
    return judge_llm.with_structured_output(schema).invoke(prompt)


def _judged_findings(record: dict):
    """(book, finding) for every book the run did not label silent: a silent book has no claim to judge."""
    for finding in record["answer"]["unique_findings"]:
        if record["retrieval"][finding["corpus_id"]]["label"] != "silent":
            yield finding["corpus_id"], finding


def faithfulness(record: dict) -> dict[str, dict]:
    """Per book: does the finding claim more than its quote shows (D3)? The finding is split into claims and each is
    judged against the quote alone. Passes only when every claim is supported."""
    results = {}
    for cid, finding in _judged_findings(record):
        if not finding["quote"]:
            results[cid] = {"claims": 0, "unsupported": [], "passed": False, "reason": "no quote to check against"}
            continue
        verdict = _judge(FaithfulnessVerdict, (
            f"Finding: {finding['finding']}\n\nQuote: {finding['quote']}\n\n"
            "Split the finding into its separate factual claims about what the book says. For each claim, decide "
            "whether the quote alone supports it. Judge only against the quote's words: not the rest of the book, "
            "not what you know about the author. A claim that generalizes, interprets or adds a cause beyond what "
            "the quote states is not supported."))
        unsupported = [check.claim for check in verdict.claims if not check.supported]
        results[cid] = {"claims": len(verdict.claims), "unsupported": unsupported,
                        "passed": bool(verdict.claims) and not unsupported}
    return results


def _without_author_names(text: str) -> str:
    """The finding with every author's full name and surname replaced by "the author": a finding that names its
    author would let the attribution judge answer from the name instead of from the passages."""
    for book in CATALOG.values():
        for name in (book.author, book.author.split()[-1]):  # full name first, so no "Saint the author" is left
            text = re.sub(term_pattern(name).pattern, "the author", text, flags=re.IGNORECASE)
    return text


def attribution(record: dict) -> dict[str, dict]:
    """Per book: is the finding credited to the right book? The judge sees both books' retrieved passages without
    their names, in an order fixed per entry and book (so the book under test is not always first), and says which
    set the finding describes. Passes when that is the book the finding is credited to, or both."""
    results = {}
    for cid, finding in _judged_findings(record):
        other = next(c for c in record["chunks"] if c != cid)
        order = [cid, other]
        random.Random(f"{record['id']}-{cid}").shuffle(order)
        passages = "\n\n".join(
            f"Passages {i}:\n" + ("\n---\n".join(record["chunks"][book]) or "(none)")
            for i, book in enumerate(order, 1))
        verdict = _judge(AttributionVerdict, (
            f"{passages}\n\nFinding: {_without_author_names(finding['finding'])}\n\n"
            "Which set of passages does this finding describe? Decide by the idea the finding states (its claim, its "
            "cause, its example), not by the words it uses: a word that appears in both sets is not evidence for "
            "both. Answer 1 or 2 if the idea is stated in one set. Answer both only if each set, read on its own, "
            "states the same idea. Answer neither if no set states it."))
        judged = {"1": order[0], "2": order[1]}.get(verdict.source, verdict.source)
        results[cid] = {"judged": judged, "passed": judged in (cid, "both"), "reason": verdict.reason}
    return results


def judge_records(records: list[dict], out_dir: Path = EVAL_DIR) -> Path:
    """Runs both judges over a list of target records and writes one row per judged book, with empty human fields
    to fill by hand: human_faithful (true/false) and human_source ("A", "B", "both" or "neither")."""
    rows = []
    for record in records:
        faithful, attributed = faithfulness(record), attribution(record)
        findings = dict(_judged_findings(record))
        for cid in findings:
            rows.append({"id": record["id"], "book": cid, "query": record["query"],
                         "finding": findings[cid]["finding"], "quote": findings[cid]["quote"],
                         "faithfulness": faithful[cid], "attribution": attributed[cid],
                         "human_faithful": None, "human_source": None})
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"calibration_{datetime.now():%Y-%m-%d_%H%M}.json"
    path.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    return path


def judge_agreement(rows: list[dict]) -> dict[str, dict]:
    """How often each judge agrees with the hand labels, over the rows that have one, and where it does not."""
    report = {}
    for judge, human, judged in (("faithfulness", "human_faithful", lambda r: r["faithfulness"]["passed"]),
                                 ("attribution", "human_source", lambda r: r["attribution"]["judged"])):
        labelled = [r for r in rows if r[human] is not None]
        disagree = [f"{r['id']} {r['book']}" for r in labelled if judged(r) != r[human]]
        report[judge] = {"labelled": len(labelled), "agree": len(labelled) - len(disagree), "disagree": disagree}
    return report


if __name__ == "__main__":
    import sys
    rows = json.loads(Path(sys.argv[1]).read_text())
    print(json.dumps(judge_agreement(rows), indent=1))
