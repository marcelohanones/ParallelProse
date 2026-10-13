"""LLM judges for the evaluation harness (roadmap item 30.3): faithfulness and attribution.

Faithfulness judges each (claim, sentence) pair on its own — one atomic claim against the verbatim sentence that
states it — and a book passes only when every pair passes. Attribution judges the book's headline, the synthesis:
which book's passages is it describing. Both judge a target record (evaluation.run_golden_entry), per book that was
not labelled silent.

The self-judging invariant (roadmap item 45.2). A judge never runs on the same model as the role that produced what
it grades. Faithfulness grades a (claim, sentence) pair: the claim comes from the composer and the sentence from the
picker, so its model stays off both. Attribution grades the headline, which comes from the composer, so its model
stays off the composer's — it may share the picker's, since the picker writes no headlines. The defaults satisfy it
(composer = picker = gpt-4o-mini, judges = gpt-4o), and the env overrides can break it: `PP_CRITIQUE_MODEL` moves the
picker's surface, so pointing it at the judge model makes faithfulness grade sentences its own model selected, and
that measurement is self-judged. Item 45.1's run record is what would show it after the fact.

Neither judge is trusted until it agrees with hand labels: judge_records writes the verdicts
beside empty human fields, and judge_agreement measures the agreement once those fields are filled.
"""

from dotenv import load_dotenv

load_dotenv()

import json
import os
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
ATTRIBUTION_JUDGE_MODEL = os.getenv("PP_ATTRIBUTION_JUDGE_MODEL", JUDGE_MODEL)
EVAL_DIR = DATA_DIR / "eval"


def _judge_client(model: str):
    """The client for one judge model. A DeepSeek model gets the DeepSeek client with thinking off: on this surface
    thinking would void temperature, refuse the named tool_choice langchain sends, and demand reasoning_content back
    (item 45.3's gate)."""
    if model.startswith("deepseek"):
        from langchain_deepseek import ChatDeepSeek
        return ChatDeepSeek(model=model, temperature=0, extra_body={"thinking": {"type": "disabled"}})
    return ChatOpenAI(model=model, temperature=0)


judge_llm = _judge_client(JUDGE_MODEL)                      # faithfulness
attribution_llm = _judge_client(ATTRIBUTION_JUDGE_MODEL)    # attribution, per judge (item 45.4)


class PairVerdict(BaseModel):
    supported: bool = Field(description="True only if the sentence alone, read literally, states the claim")


class AttributionVerdict(BaseModel):
    source: Literal["1", "2", "both", "neither"] = Field(
        description="Which set of passages the finding describes: 1, 2, both, or neither")
    reason: str


def _judge(client, role: str, schema: type[BaseModel], prompt: str, callbacks=None) -> BaseModel:
    """One judged call. The role tag lives here because the judges run outside the graph, where the graph's config
    cannot reach them; callbacks carries the run's RoleUsageTracker (item 45.1). The client is explicit so each judge
    can move provider on its own (item 45.4)."""
    config = {"tags": [f"role:{role}"]}
    if callbacks:
        config["callbacks"] = callbacks
    return client.with_structured_output(schema).invoke(prompt, config=config)


def _judged_books(record: dict):
    """(book, finding) for every book the run did not label silent: a silent book has no claim to judge."""
    for finding in record["answer"]["unique_findings"]:
        if record["retrieval"][finding["corpus_id"]]["label"] != "silent":
            yield finding["corpus_id"], finding


def faithfulness(record: dict, callbacks=None) -> dict[str, dict]:
    """Per book: does any pair's claim say more than its own sentence states? Each pair is judged on its own, so
    the question is well-posed — an atomic claim against the sentence it came from. Passes only when every pair
    passes, and a book with no pair passes nothing."""
    results = {}
    for cid, finding in _judged_books(record):
        pairs = finding.get("pairs") or []
        unsupported = []
        for pair in pairs:
            verdict = _judge(judge_llm, "judge_faithfulness", PairVerdict, (
                f"Claim: {pair['claim']}\n\nSentence: {pair['sentence']}\n\n"
                "Does this sentence alone, read literally, state this claim? Judge only against the sentence's "
                "words: not the rest of the book, not what you know about the author. A claim that generalizes, "
                "interprets or adds a cause beyond what the sentence states is not supported."),
                callbacks=callbacks)
            if not verdict.supported:
                unsupported.append(pair["claim"])
        results[cid] = {"pairs": len(pairs), "unsupported": unsupported,
                        "passed": bool(pairs) and not unsupported}
    return results


def _without_author_names(text: str) -> str:
    """The finding with every author's full name and surname replaced by "the author": a finding that names its
    author would let the attribution judge answer from the name instead of from the passages."""
    for book in CATALOG.values():
        for name in (book.author, book.author.split()[-1]):  # full name first, so no "Saint the author" is left
            text = re.sub(term_pattern(name).pattern, "the author", text, flags=re.IGNORECASE)
    return text


def attribution(record: dict, callbacks=None) -> dict[str, dict]:
    """Per book: is the headline credited to the right book? The judge sees both books' retrieved passages without
    their names, in an order fixed per entry and book (so the book under test is not always first), and says which
    set the finding describes. Passes when that is the book the finding is credited to, or both."""
    results = {}
    for cid, finding in _judged_books(record):
        other = next(c for c in record["chunks"] if c != cid)
        order = [cid, other]
        random.Random(f"{record['id']}-{cid}").shuffle(order)
        passages = "\n\n".join(
            f"Passages {i}:\n" + ("\n---\n".join(record["chunks"][book]) or "(none)")
            for i, book in enumerate(order, 1))
        verdict = _judge(attribution_llm, "judge_attribution", AttributionVerdict, (
            f"{passages}\n\nFinding: {_without_author_names(finding['headline'])}\n\n"
            "Which set of passages does this finding describe? Decide by the idea the finding states (its claim, its "
            "cause, its example), not by the words it uses: a word that appears in both sets is not evidence for "
            "both. Answer 1 or 2 if the idea is stated in one set. Answer both only if each set, read on its own, "
            "states the same idea. Answer neither if no set states it."),
            callbacks=callbacks)
        judged = {"1": order[0], "2": order[1]}.get(verdict.source, verdict.source)
        results[cid] = {"judged": judged, "passed": judged in (cid, "both"), "reason": verdict.reason}
    return results


def judge_records(records: list[dict], out_dir: Path = EVAL_DIR, callbacks=None) -> Path:
    """Runs both judges over a list of target records and writes one row per (claim, sentence) pair, with empty
    human fields to fill by hand: human_faithful (true/false) and human_source ("A", "B", "both" or "neither")."""
    rows = []
    for record in records:
        judged = {cid: faithfulness(record, callbacks=callbacks)[cid] for cid, _ in _judged_books(record)}
        attributed = attribution(record, callbacks=callbacks)
        for cid, finding in _judged_books(record):
            unsupported = set(judged[cid]["unsupported"])
            for pair in finding.get("pairs") or []:
                rows.append({"id": record["id"], "book": cid, "query": record["query"],
                             "claim": pair["claim"], "sentence": pair["sentence"],
                             "faithfulness": {"passed": pair["claim"] not in unsupported},
                             "attribution": attributed.get(cid),
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
