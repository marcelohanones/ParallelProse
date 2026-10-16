"""Item 50 / Phase 0 -- the attribution replay: the picker against provider citations, on frozen data.

The A/B is a replay, never a re-run: data/eval/afterC2_run1_*.json already holds the picker's own answers
(pairs and unpaired), the claims the composer wrote, and the chunks the picker saw. Each claim goes to the
Anthropic citation mechanism with the picker's *own* candidate list, and the answer is bucketed against what the
picker did.

Request shape (fixed after CC's review, 2026-10-15):
  - ONE document block of type "content" -- custom content, no provider chunking -- with one text block per
    sentence of `_sentences(chunks)`. Plain-text documents would be chunked into sentences by the API and would
    come back with character indices and `document_index`, never with the block indices this code reads (CC-32).
  - `citations: {enabled: True}` on the document, `cache_control` on it, the claim text last.
  - `output_config: {"effort": "low"}`: Haiku 5.5 runs adaptive thinking at effort `medium` by default, which is
    output tokens spent on a one-sentence selection. The citations incompatibility is with
    `output_config.format`, never with `effort` (CC-36).
  - The answer must be either a quoted sentence or the literal `NONE`; an answer with text but no citation is
    *unfounded*, a third outcome, kept out of the arithmetic (CC-35).

The one deliberate coupling: `_sentences` is imported lazily from the picker's own module -- a copy of the regex
would drift and the A/B would stop being an A/B. The price is opening Chroma once, local and free.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from ParallelProse.catalog import CATALOG, DATA_DIR
from ParallelProse.textform import match_form

EVAL_DIR = DATA_DIR / "eval"
DEFAULT_INPUT = EVAL_DIR / "afterC2_run1_2026-10-12_2242.json"
NONE_ANSWER = "NONE"
COPY_PROMPT = (
    "Claim: {claim}\n\n"
    "The document above is a list of single sentences from one book, in order. If one of them states this claim, "
    "quote that sentence exactly as your whole answer. If no single sentence states it, answer exactly: "
    f"{NONE_ANSWER}"
)


# The probe of 2026-10-15: with the copy prompt the model reproduces the sentence from memory and the API
# attaches NO citation (16 of 18 such rows were the picker's exact sentence, uncited); with this prose prompt
# 5 of 5 rows came back cited, with block ranges pointing at the right sentences. The deployable form is prose.
# Without the refusal clause the model hedges ("no single sentence states this, but...") and cites anyway:
# 5 of 5 previously-declining rows came back cited. With the clause, 4 of 5 answer NONE with zero citations
# and the easy control still binds. The deployable prompt is this one.
PROSE_PROMPT = (
    "Claim: {claim}\n\n"
    "The document above lists single sentences from one book, in order. Answer briefly, in your own words. "
    "If one sentence states this claim, say which one and support your answer with the document. If NO "
    "single sentence states the claim, answer exactly NONE and cite nothing at all. Never answer with a "
    "bare index or a number alone."
)
PROMPTS = {"prose": PROSE_PROMPT, "copy": COPY_PROMPT}


def sentences_of(chunks: list[str]) -> list[str]:
    """The picker's own candidate list -- imported from the picker so the units cannot drift."""
    from ParallelProse.agent import _sentences  # lazy, and the single source of truth

    return _sentences(chunks)


def content_document(sentences: list[str], title: str) -> dict:
    """ONE custom-content document: no provider chunking, block i is sentence i, block indices in the citation."""
    # NO cache_control: measured 2026-10-15, custom content + citations + cache_control returns ZERO citations
    # (three probes: with cache 0/0 citations, without cache 1/1, same claim, same document). The caching trick
    # that CC-25 budgeted for is unavailable on this path; the cost stays inside the Phase 0 ceiling anyway.
    return {
        "type": "document",
        "source": {"type": "content", "content": [{"type": "text", "text": s} for s in sentences]},
        "title": title,
        "citations": {"enabled": True},
    }


def make_request(claim: str, sentences: list[str], title: str, model: str, max_tokens: int = 1500,
                 prompt: str = PROSE_PROMPT) -> dict:
    """`max_tokens` must leave room for adaptive thinking: at 512, 27 of 101 answers never emitted text
    (all 27 stopped exactly at the cap) and the empty responses were misread as a different sentence."""
    """Document first (cached), the claim last -- a claim-first prefix never hits the cache."""
    assert sentences, "a request needs at least one candidate sentence"
    return {
        "model": model,
        "max_tokens": max_tokens,
        "output_config": {"effort": "low"},
        "messages": [{"role": "user", "content": [content_document(sentences, title),
                                                   {"type": "text", "text": prompt.format(claim=claim)}]}],
    }


def read_answer(response: Any, sentences: list[str]) -> dict:
    """Declined (the literal NONE, no citation) / unfounded (text but no citation) / cited, with block indices."""
    cited_texts, starts, ends, bad, answer_text = [], [], [], False, ""
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) != "text":
            continue
        answer_text += getattr(block, "text", "") or ""
        for citation in getattr(block, "citations", None) or []:
            cited_texts.append(getattr(citation, "cited_text", None))
            start = getattr(citation, "start_block_index", None)
            end = getattr(citation, "end_block_index", None)
            if start is not None and not (0 <= start < len(sentences)):
                bad = True
            starts.append(start)
            ends.append(end)
    blocks: list[int] = []
    for start, end in zip(starts, ends):          # end_block_index is EXCLUSIVE: (0, 1) is block 0 alone
        if start is None:
            continue
        stop = end if isinstance(end, int) and end > start else start + 1
        blocks.extend(range(start, stop))
    said_none = answer_text.strip().rstrip(".").upper() == NONE_ANSWER
    return {"empty": not answer_text.strip() and not cited_texts,
            "stop_reason": getattr(response, "stop_reason", None),
            "declined": said_none and not cited_texts,
            "unfounded": bool(answer_text.strip()) and not said_none and not cited_texts,
            "cited_texts": cited_texts, "start_blocks": starts, "end_blocks": ends,
            "cited_blocks": sorted(set(blocks)),
            "invalid_block_index": bad, "text": answer_text.strip()}


def picker_index(sentence: str, sentences: list[str]) -> int | None:
    """Where the picker's sentence sits in the same list (1-based, like the picker's own numbering)."""
    target = match_form(sentence, is_quote=True)
    for i, candidate in enumerate(sentences):
        if match_form(candidate, is_quote=True) == target:
            return i + 1
    return None


def same_sentence(answer: dict, picker: str | None, sentences: list[str], view: str = "lenient") -> bool:
    """CC-43: the mechanism returns a SET of blocks, the picker returns one index, so the rule must be stated.

    strict  = exactly one block is cited, and it is the picker's sentence;
    lenient = the picker's sentence is somewhere inside the cited set.
    A mechanism that cites five sentences and happens to contain the right one is not selecting the right one,
    which is why the strict view is the headline and the cited-block count is reported beside both.
    There is no text fallback: with exclusive-end ranges the block set IS the answer.
    """
    if picker is None or answer["declined"] or answer["invalid_block_index"]:
        return False
    picker_at = picker_index(picker, sentences)
    if picker_at is None:
        return False
    cited = set(answer.get("cited_blocks") or [])
    if view == "strict":
        return len(cited) == 1 and (picker_at - 1) in cited
    return (picker_at - 1) in cited


def bucket_of(picker: str | None, answer: dict, sentences: list[str], view: str = "lenient") -> str:
    """1a agreement / 1b both declined / 2 both chose, differently / 3 picker only / 4 citation only;
    empty, unfounded and invalid are reported outside the arithmetic."""
    if answer.get("empty"):
        return "empty"          # no text emitted: truncated or a protocol failure, never a selection
    if answer["unfounded"]:
        return "unfounded"
    if answer["invalid_block_index"] and not answer["declined"]:
        return "invalid"
    if picker is None and answer["declined"]:
        return "1b"
    if picker is None:
        return "4"
    if answer["declined"]:
        return "3"
    return "1a" if same_sentence(answer, picker, sentences, view) else "2"


def unpaired_cause(choice_index: int | None, n_sentences: int, used: set[int]) -> str:
    """4a the picker judged that no sentence states it (order-independent) / 4b already used / 4c malformed /
    4d valid and free. 4b against 4d cannot be settled from the frozen record: the interleaving of pairs and
    unpaired claims is not stored, so `used` at the picker's own moment is not recoverable -- the two are
    reported together and only 4a enters the gate (CC-29)."""
    if choice_index is None:
        return "4a"
    if not (1 <= choice_index <= n_sentences):
        return "4c"
    return "4b" if choice_index in used else "4d"


def slots(record: dict) -> list[dict]:
    """Every judged book slot of one frozen entry: its claims, the picker's answers, and the chunks it saw."""
    out = []
    for finding in record["answer"]["unique_findings"]:
        cid = finding["corpus_id"]
        if record["retrieval"][cid]["label"] == "silent":
            continue
        chunks = record["chunks"][cid]
        out.append({"record": record["id"], "query": record["query"], "corpus_id": cid,
                    "chunks": chunks, "sentences": sentences_of(chunks),
                    "pairs": [{"claim": p["claim"], "sentence": p["sentence"]} for p in finding.get("pairs") or []],
                    "unpaired": list(finding.get("unpaired") or [])})
    return out


def load_frozen(path: Path = DEFAULT_INPUT) -> list[dict]:
    return json.loads(Path(path).read_text())


def claims_of(slot: dict) -> list[dict]:
    """The claim list in the picker's stored order (pairs then unpaired -- the interleaving is not recorded)."""
    claims = [{"claim": pair["claim"], "picker": pair["sentence"]} for pair in slot["pairs"]]
    claims += [{"claim": claim, "picker": None} for claim in slot["unpaired"]]
    return claims


def dry_run(entries: list[dict], model: str) -> dict:
    """Free: what the run would send, without touching the network."""
    total_sentences = total_claims = total_chars = 0
    per_slot = []
    for entry in entries:
        for slot in slots(entry):
            claims = claims_of(slot)
            chars = sum(len(s) for s in slot["sentences"])
            total_sentences += len(slot["sentences"])
            total_claims += len(claims)
            total_chars += chars * max(1, len(claims))
            per_slot.append({"record": slot["record"], "corpus_id": slot["corpus_id"],
                             "sentences": len(slot["sentences"]), "claims": len(claims)})
    return {"model": model, "slots": len(per_slot), "claims": total_claims, "candidate_sentences": total_sentences,
            "estimated_input_tokens": total_chars // 4, "per_slot": per_slot[:5]}


def run(entries: list[dict], model: str, client: Any, prompt: str = PROSE_PROMPT) -> dict:
    """The paid half: one request per claim, buckets against the frozen picker."""
    results, cache_flags = [], []
    for entry in entries:
        for slot in slots(entry):
            title = f"{slot['corpus_id']} -- {CATALOG[slot['corpus_id']].book_title}"
            for n, item in enumerate(claims_of(slot), 1):
                response = client.messages.create(
                    **make_request(item["claim"], slot["sentences"], title, model, prompt=prompt))
                answer = read_answer(response, slot["sentences"])
                usage = getattr(response, "usage", None)
                cache_flags.append({"slot": f"{slot['record']}-{slot['corpus_id']}", "claim_n": n,
                                    "cache_read": getattr(usage, "cache_read_input_tokens", None) if usage else None,
                                    "input": getattr(usage, "input_tokens", None) if usage else None,
                                    "output": getattr(usage, "output_tokens", None) if usage else None})
                results.append({"record": slot["record"], "corpus_id": slot["corpus_id"], "claim": item["claim"],
                                "picker": item["picker"],
                                "bucket": bucket_of(item["picker"], answer, slot["sentences"], "strict"),
                                "bucket_lenient": bucket_of(item["picker"], answer, slot["sentences"], "lenient"),
                                "cited_block_count": len(answer["cited_blocks"]),
                                "cited_blocks": answer["cited_blocks"],
                                "declined": answer["declined"], "unfounded": answer["unfounded"],
                                "cited_texts": answer["cited_texts"], "start_blocks": answer["start_blocks"],
                                "invalid_block_index": answer["invalid_block_index"], "answer_text": answer["text"],
                                "stop_reason": answer.get("stop_reason")})
    return {"claims": results, "cache": cache_flags, "buckets": count_buckets(results),
            "buckets_lenient": count_buckets(results, key="bucket_lenient")}


def count_buckets(results: list[dict], key: str = "bucket") -> dict:
    names = ("1a", "1b", "2", "3", "4", "unfounded", "empty", "invalid")
    counts = {name: 0 for name in names}
    for row in results:
        counts[row[key]] = counts.get(row[key], 0) + 1
    return counts



QUESTION = (
    "For each candidate, answer one question: does this sentence AFFIRM the claim above? AFFIRM means the "
    "sentence states the claim; a shared topic, a shared word or a nearby idea is NOT affirmation. This is "
    "item 48's criterion on purpose: a witness span must affirm the claim, not be its nearest neighbour. "
    "Answer every candidate, yes or no. If every candidate is no, that is a complete answer -- it is how a "
    "claim with no witness is recorded."
)


def _overlap(claim: str, sentence: str) -> float:
    """Term overlap between claim and sentence, over the same content terms the picker's guards use."""
    from ParallelProse.textform import _content_terms

    a, b = _content_terms(claim), _content_terms(sentence)
    return len(a & b) / max(1, len(a | b))


def sheet_candidates(row: dict, sentences: list[str], size: int = 3) -> list[str]:
    """Exactly `size` distinct candidates: what each side picked, then the nearest the sides passed over.

    Uniform shape is part of the blinding (CC-52): a row with one option -- or with three -- would tell the
    labeller which bucket it came from before a single label exists. The passed-over candidates are also what
    make a shared refusal falsifiable: with only the refusal on offer, "both declined" can only be agreed with.
    """
    texts: list[str] = []

    def add(text: str | None) -> None:
        if not text:
            return
        if any(match_form(text, is_quote=True) == match_form(t, is_quote=True) for t in texts):
            return
        texts.append(text)

    add(row.get("picker"))
    for text in row.get("cited_texts") or []:
        add(text)
    for sentence in sorted(sentences, key=lambda sentence: -_overlap(row["claim"], sentence)):
        if len(texts) >= size:
            break
        add(sentence)
    return texts[:size]


def blind_sheet(results: list[dict], sentences_by_slot: dict, bucket3_sample: int = 25, agree_sample: int = 15,
                seed: int = 20261015) -> tuple[list[dict], dict, dict]:
    """The blind sitting: every row shows exactly three candidates, in a per-row random order, no origin.

    The question is stated once, per CC-54: does the sentence AFFIRM the claim (item 48's criterion)? The
    consequence was pre-declared before the first label: under it the likely finding is that the CLAIMS are
    wrong, not the selector -- which is item 49 reopening, not item 49 answered.
    """
    rng = random.Random(seed)
    # CC-47: the sitting is capped before any label exists. Buckets 2 and 4 are small by construction and go
    # in whole; bucket 3 -- the audit of the incumbent -- goes in as a random sample with the seed recorded, so
    # its result is read as an estimate with an interval, never as a count; the agreement slice stays sampled.
    two = [r for r in results if r["bucket"] == "2"]
    three = [r for r in results if r["bucket"] == "3"]
    four = [r for r in results if r["bucket"] == "4"]
    other = [r for r in results if r["bucket"] in ("unfounded", "invalid", "empty")]
    agree = [r for r in results if r["bucket"] in ("1a", "1b")]
    three_kept = rng.sample(three, min(bucket3_sample, len(three)))
    agree_kept = rng.sample(agree, min(agree_sample, len(agree)))
    sampling = {"seed": seed, "bucket2": len(two), "bucket3_total": len(three),
                "bucket3_sampled": len(three_kept), "bucket3_rate": round(len(three_kept) / max(1, len(three)), 3),
                "bucket4": len(four), "other": len(other), "agreement_total": len(agree),
                "agreement_sampled": len(agree_kept),
                "rows_in_the_sitting": len(two) + len(three_kept) + len(four) + len(other) + len(agree_kept)}
    chosen = two + three_kept + four + other + agree_kept
    rng.shuffle(chosen)
    rows, key = [], {}
    for n, row in enumerate(chosen, 1):
        sid = f"a{n:03d}"
        slot_sentences = sentences_by_slot.get((row["record"], row["corpus_id"])) or []
        candidates = sheet_candidates(row, slot_sentences)
        rng.shuffle(candidates)
        picker_form = match_form(row["picker"], is_quote=True) if row["picker"] else None
        cited_forms = {match_form(t, is_quote=True) for t in (row["cited_texts"] or []) if t}
        rows.append({"id": sid, "claim": row["claim"], "candidates": candidates})
        key[sid] = {"bucket": row["bucket"], "bucket_lenient": row.get("bucket_lenient"),
                    "picker": row["picker"], "citation": row["cited_texts"],
                    "cited_block_count": row.get("cited_block_count"),
                    "candidate_origin": [("picker" if match_form(c, is_quote=True) == picker_form else
                                          "citation" if match_form(c, is_quote=True) in cited_forms else "distractor")
                                         for c in candidates]}
    return rows, key, sampling


class _Attr:
    """Attribute access over the API's JSON, so the call sites read like the SDK's objects."""

    def __init__(self, data: Any):
        object.__setattr__(self, "_d", data)

    def __getattr__(self, name: str) -> Any:
        if not isinstance(self._d, dict):
            return None
        value = self._d.get(name)
        if isinstance(value, dict):
            return _Attr(value)
        if isinstance(value, list):
            return [_Attr(v) if isinstance(v, dict) else v for v in value]
        return value


class AnthropicHttp:
    """A minimal Messages client over httpx.

    The official SDK is not declared while this is a spike: `uv add` needs the uv cache outside the workspace,
    and the request is one POST. If 1a wins, the SDK replaces this class and the call sites do not change.
    """

    URL = "https://api.anthropic.com/v1/messages"
    VERSION = "2023-06-01"

    def __init__(self, api_key: str | None = None, url: str | None = None, version: str | None = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or ""
        self.url = url or self.URL
        self.version = version or self.VERSION
        self.messages = self

    def create(self, **payload: Any) -> _Attr:
        import httpx

        headers = {"x-api-key": self.api_key, "anthropic-version": self.version,
                   "content-type": "application/json"}
        # A key that is not scoped to a workspace must name one: HTTP 400 says so verbatim.
        workspace = os.getenv("ANTHROPIC_WORKSPACE_ID")
        if workspace:
            headers["anthropic-workspace-id"] = workspace
        response = httpx.post(self.url, json=payload, timeout=180.0, headers=headers)
        if response.status_code >= 400:
            raise SystemExit(f"Anthropic API error {response.status_code}: {response.text[:500]}")
        return _Attr(response.json())


def make_client() -> Any:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set.")
    return AnthropicHttp()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Item 50 Phase 0: the attribution replay (dry by default).")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--model", default=os.getenv("PP_CITATION_MODEL", ""))
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--limit", type=int, default=0, help="0 = every entry in the frozen record")
    parser.add_argument("--prompt", choices=sorted(PROMPTS), default="prose",
                        help="prose (deployable: the model answers in its own words) or copy (verbatim)")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--sheet", type=Path, default=None,
                        help="emit the blind adjudication sheet from a finished run record, then stop")
    parser.add_argument("--tsv", type=Path, default=None,
                        help="emit the labelling TSV from the sheet rows (3 candidates per row) and stop")
    args = parser.parse_args(argv)

    if args.tsv:
        sheet_rows = json.loads(args.tsv.read_text())
        out = args.tsv.with_name(args.tsv.stem + "_answers.tsv")
        with out.open("w", newline="") as fh:
            writer = csv.writer(fh, delimiter="\t")
            writer.writerow(["row_id", "cand", "claim", "candidate", "affirms", "boundary", "note"])
            for row in sheet_rows:
                for n, candidate in enumerate(row["candidates"], 1):
                    writer.writerow([row["id"], n, row["claim"], candidate, "", "", ""])
        print(f"wrote {out} ({len(sheet_rows)} rows x 3 candidates = {len(sheet_rows) * 3} judgements)")
        return 0

    if args.sheet:
        results = json.loads(args.sheet.read_text())["claims"]
        frozen = load_frozen(args.input)
        sentences_by_slot = {(slot["record"], slot["corpus_id"]): slot["sentences"]
                             for entry in frozen for slot in slots(entry)}
        rows, key, sampling = blind_sheet(results, sentences_by_slot)
        rows_path = args.sheet.with_name(args.sheet.stem + "_rows.json")
        key_path = args.sheet.with_name(args.sheet.stem + "_key.json")
        sampling_path = args.sheet.with_name(args.sheet.stem + "_sampling.json")
        question_path = args.sheet.with_name(args.sheet.stem + "_question.md")
        rows_path.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
        key_path.write_text(json.dumps(key, indent=1, ensure_ascii=False))
        sampling_path.write_text(json.dumps(sampling, indent=1, ensure_ascii=False))
        question_path.write_text(QUESTION + "\n")
        print(f"wrote {rows_path}, {key_path}, {sampling_path} and {question_path}")
        print(json.dumps(sampling))
        return 0

    entries = load_frozen(args.input)
    if args.limit:
        entries = entries[: args.limit]
    stamp = f"{datetime.now():%Y-%m-%d_%H%M}"
    record: dict[str, Any] = {"what": "item50_phase0_replay", "ran_at": stamp, "model": args.model,
                              "input": str(args.input), "entries": len(entries)}
    if args.run:
        if not args.model:
            raise SystemExit("--model (or PP_CITATION_MODEL) is required: no model id is assumed.")
        record.update(run(entries, args.model, make_client(), prompt=PROMPTS[args.prompt]))
        record["prompt"] = args.prompt
    else:
        record["dry_run"] = dry_run(entries, args.model or "<model>")
    out = args.out or EVAL_DIR / f"item50_replay_{stamp}.json"
    out.write_text(json.dumps(record, indent=1, ensure_ascii=False))
    print(f"wrote {out}")
    print(json.dumps({k: v for k, v in record.items() if k != "claims"}, indent=1, ensure_ascii=False)[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
