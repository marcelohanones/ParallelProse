"""Item 46's instrument: E judged over frozen evidence, so the model is the only variable.

A live re-run cannot answer "did the judgment change?", because retrieval moves with it -- item 44.5
measured 12 of 32 sides retrieving different chunks between two runs with the same seed. This replays
`e_judge_first`/`e_judge_second` over the chunks and lineage a saved run already holds, and compares the
labels against the ones recorded in that file. It is the frozen-chunk replay the Backlog had parked.

Two things it cannot do, by construction. A `miss` is not a final label: in the graph it routes to the
retry arm and `e_second` decides, and there is no new retrieval here -- so a `miss` means "E asked for
another look", not an outcome. And the comparison is only as good as the recorded labels: it reads the
model that produced them from the file's own run record where present, never assumes one.

Scoring: `silent` -> `ok` is reported on its own, never folded into the agreement count. That direction
is a false `ok` -- the defect item 44 exists to remove -- and agreement alone ranked a model that
introduces them above one that does not (see ROADMAP item 46).
"""

import json
from pathlib import Path
from typing import Callable, Iterable

from ParallelProse.catalog import DATA_DIR

EVAL_DIR = DATA_DIR / "eval"


def corpora_of(record: dict) -> dict:
    """The frozen slot per book, in `CorpusState`'s shape.

    Only `chunks` and `lineage` reach the judge's prompt (`format_context`, `format_attempts`); the rest
    travels so `e_record` can be called on the verdict.
    """
    return {
        book: {
            "chunks": record["chunks"][book] or [],
            "lineage": slot.get("lineage") or [],
            "label": slot["label"],
            "reason": slot.get("reason"),
            "narrowed_query": None,
            "silence_cause": slot.get("silence_cause"),
            "P": slot.get("P"),
            "retry_used": slot.get("retry_used", False),
        }
        for book, slot in record["retrieval"].items()
    }


def final_look(corpora: dict) -> str:
    """Which look produced the recorded label: the retry arm judges every book again, so one book
    retrying puts the whole entry on `e_second`."""
    return "e_second" if any(slot["retry_used"] for slot in corpora.values()) else "e_first"


def recorded_labels(records: Iterable[dict]) -> dict[tuple[str, str], str]:
    """(id, book) -> the label the saved run ended on."""
    return {(record["id"], book): slot["label"]
            for record in records for book, slot in record["retrieval"].items()}


def compare(replayed: dict[tuple[str, str], str],
            recorded: dict[tuple[str, str], str]) -> dict:
    """Agreement, the moves that produced it, and `silent` -> `ok` counted apart.

    A false `ok` is not one disagreement among others: it is the defect the judge exists to prevent, so
    it is reported as its own list and never averaged into `agree`.
    """
    moves, false_ok = [], []
    for key, label in sorted(replayed.items()):
        was = recorded.get(key)
        if label == was:
            continue
        move = {"ref": f"{key[0]} {key[1]}", "recorded": was, "replay": label}
        moves.append(move)
        if was == "silent" and label == "ok":
            false_ok.append(move)
    return {"agree": len(replayed) - len(moves), "total": len(replayed),
            "moves": moves, "false_ok": false_ok}


def replay(records: list[dict], judges: dict[str, Callable]) -> dict[tuple[str, str], str]:
    """One pass of E over every record's frozen evidence, returning (id, book) -> label.

    `judges` maps `"e_first"`/`"e_second"` to the callables, so a caller can point them at a different
    client without this module importing `agent`'s module-level one.
    """
    from ParallelProse.agent import _verdicts_for_every_book, e_record, postprocess_e

    labels = {}
    for record in records:
        corpora = corpora_of(record)
        state = {"query": record["query"], "corpora": corpora, "iteration": 0}
        for verdict in _verdicts_for_every_book(state, judges[final_look(corpora)]):
            post = postprocess_e(verdict)
            retry_used = corpora[post.corpus_id]["retry_used"]
            labels[(record["id"], post.corpus_id)] = e_record(post, retry_used)["label"]
    return labels


def main() -> None:
    import argparse

    from langchain_openai import ChatOpenAI

    from ParallelProse import agent
    from ParallelProse.run_record import RoleUsageTracker

    parser = argparse.ArgumentParser(description="Replay E over a saved run's frozen chunks.")
    parser.add_argument("source", type=Path, help="a run JSON under data/eval")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--temperature", type=float, default=0.5)
    parser.add_argument("--reps", type=int, default=3)
    args = parser.parse_args()

    records = json.loads(args.source.read_text())
    recorded = recorded_labels(records)
    results = []
    for rep in range(1, args.reps + 1):
        tracker = RoleUsageTracker()
        # The tracker rides on the client: e_judge_first/second take no config. No tag here — the call
        # sites already tag `role:critique_e`, and a second tag makes the tracker raise, correctly.
        agent.critique_llm = ChatOpenAI(model=args.model, temperature=args.temperature,
                                        callbacks=[tracker])
        judges = {"e_first": agent.e_judge_first, "e_second": agent.e_judge_second}
        report = compare(replay(records, judges), recorded)
        print(f"[{args.model} T={args.temperature}] rep {rep}: "
              f"{report['agree']}/{report['total']} agree | "
              f"false ok: {[m['ref'] for m in report['false_ok']] or 'none'}")
        results.append({"model": args.model, "temperature": args.temperature, "rep": rep,
                        "source": args.source.name, **report,
                        "usage": json.loads(json.dumps(tracker.as_dict(), default=str))})

    out = EVAL_DIR / f"replay_e_{args.model.replace('.', '')}_T{args.temperature}.json"
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
