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
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from ParallelProse.catalog import CATALOG, DATA_DIR
from ParallelProse.survey import term_pattern
from ParallelProse.textform import (DROPPABLE_CONNECTIVES, _content_terms, match_form,
                                    terms_contained, terms_match)

# Item 48: measured against the 140 hand labels, three repetitions each. The faithfulness seat moves off gpt-4o,
# which false-passed 62 of the 96 `not_covered` pairs against gpt-4.1-mini's 46 -- worse on the class the judge
# exists to catch, at nine times the price. A gpt-5* name here would need reasoning_effort="none" (item 47).
JUDGE_MODEL = os.getenv("PP_JUDGE_MODEL", "gpt-4.1-mini")
# Item 47: measured on the frozen 27, three repetitions each. gpt-4.1-mini scored 27/26/26 against the
# incumbent gpt-4o's 26/26/25 at a ninth of the price, its only repeated error (g05 A) being the one case
# gpt-4o also always misses, and it holds g15 A where gpt-4o flips. gpt-5.6-luna scored 24/25/24 with two
# fixed errors and is out. A gpt-5* name here would need reasoning_effort="none": langchain silently drops
# temperature for that family (chat_models/base.py:1176-1185), leaving the judge at temperature 1.
ATTRIBUTION_JUDGE_MODEL = os.getenv("PP_ATTRIBUTION_JUDGE_MODEL", "gpt-4.1-mini")
EVAL_DIR = DATA_DIR / "eval"


judge_llm = ChatOpenAI(model=JUDGE_MODEL, temperature=0)                      # faithfulness
attribution_llm = ChatOpenAI(model=ATTRIBUTION_JUDGE_MODEL, temperature=0)    # attribution, per judge


# Item 48 v5, arm A (DSH-41): a counterpart is the sentence's own wording of the same content. These never count --
# they refer rather than state, which is exactly the fabrication the agent family would hide behind.
POINTERS = frozenset("it its they them their this that these those he she him her such one ones form".split())
PROMPT_REVISION = "v5b-counterpart-examples"   # the prompt's identity; JUDGE_VERSION is the data era, this is the wording
JUDGE_VERSION = 2  # the instrument's own era: v1 was the single boolean, v2 extracts and lets code decide
SEGMENT_RELATIONS = ("stated", "one_step", "absent")
ADDITION_KINDS = ("agent", "cause_means", "consequence", "quantity_generalization", "modality", "evaluative", "other")
# The producer item's acceptance metric (item 48, DSH-63): the three families that are defects under any reading.
# Excluded, each for a measured reason -- `other` is the dustbin and carries the code-forced absents; `evaluative`
# and `modality` flag the renderings the reference accepts (the tolerance class the acceptance round failed on); and
# `quantity_generalization` is n=3 in the labels. Counted per *pair* (a pair with at least one item of the family),
# never per item: the item-level profile double-counts multi-item segments.
DEFECT_FAMILIES = ("agent", "cause_means", "consequence")


class SegmentAddition(BaseModel):
    """One thing the claim's segment states that the sentence does not have at all. The judge extracts these; the
    relation is then derived from whether any exist (item 48 v4, after the first dry-run found the holistic relation
    field collapsing to `one_step` on 12 of 13 pairs)."""

    text: str = Field(description="The part of the segment, copied word for word, that the sentence does not carry.")
    counterpart: str | None = Field(
        default=None,
        description="The sentence's own words, copied exactly, that state this same content in another way -- null "
                    "only when the sentence has nothing that states it. A pronoun or a pointer (\"it\", \"they\", "
                    "\"this form\") is not a counterpart: it refers, it does not state.")
    kind: Literal["agent", "cause_means", "consequence", "quantity_generalization", "modality",
                  "evaluative", "other"] = Field(description="Which kind of thing it adds, if it is an addition.")


class ClaimSegment(BaseModel):
    """One consecutive slice of the claim, and how the sentence covers it. Field order is the bias control: the
    segment and its reading are committed first, then the evidence quoted from the sentence, then what the sentence
    lacks -- and only last, and only when nothing is lacking, the wording relation."""

    segment: str = Field(description="A consecutive slice of the claim, copied word for word. The segments, joined "
                                     "in order, reproduce the claim exactly: no word added, none left out, none repeated.")
    read_as: str = Field(description="This segment as a complete proposition, using only words from the claim -- "
                                     "borrow the subject from elsewhere in the claim when the segment lacks one. "
                                     "Never a word taken from the sentence.")
    evidence_span: str | None = Field(description="The part of the sentence, copied exactly, that carries this "
                                                  "segment; null when the sentence carries nothing of it.")
    adds: list[SegmentAddition] = Field(
        default_factory=list,
        description="Everything in this segment that the sentence does not have at all: a different word for "
                    "something the sentence already states is NOT an addition. Empty when the sentence carries the "
                    "whole segment.")
    relation: Literal["stated", "one_step"] = Field(
        description="Read only when `adds` is empty. stated: the sentence states it in words at the same level. "
                    "one_step: the same content, moved to another level or another concept.")


class PairJudgement(BaseModel):
    """The whole claim, segmented. No verdict field: the relation is derived from `adds`, in code (postprocess_pair)."""

    segments: list[ClaimSegment] = Field(description="The claim's segments, in the claim's own order.")


@dataclass(frozen=True)
class PairOutcome:
    """What one judged pair yields after the deterministic checks. `strict` and `lenient` are the two views, both
    derived from the same single call; `raw_relations` keeps what the model said before any code repair, because a
    repair on a positive pair is an instrument bug and must never read as a judgement (item 48, DSH-35)."""

    strict: bool
    lenient: bool
    relations: tuple[str, ...]
    raw_relations: tuple[str, ...]
    model_relations: tuple[str, ...]
    additions: tuple[str, ...]
    addition_texts: tuple[str, ...]
    renames: tuple[str, ...]
    invalid_span: bool
    invalid_add: bool
    invalid_counterpart: bool
    rename_suspects: tuple[str, ...]
    exempted_terms: tuple[str, ...]
    c2_repairs: int
    pair_error: str | None
    singleton: bool
    rewrites: tuple[str, ...]

    @property
    def repaired_absent(self) -> bool:
        """Did code, not the model, put an `absent` in this pair?"""
        return any(final == "absent" != raw for final, raw in zip(self.relations, self.raw_relations))

    def as_row(self) -> dict:
        """The compact per-pair record -- counts and flags, never the claim's or the sentence's text, which would
        bloat the LangSmith comment column. Raw and final are both here, and never conflated."""
        return {"strict": self.strict, "lenient": self.lenient, "relations": list(self.relations),
                "raw_relations": list(self.raw_relations), "model_relations": list(self.model_relations),
                "additions": list(self.additions), "addition_texts": list(self.addition_texts)[:8],
                "renames": list(self.renames)[:8], "invalid_span": self.invalid_span,
                "invalid_add": self.invalid_add, "invalid_counterpart": self.invalid_counterpart,
                "rename_suspects": list(self.rename_suspects), "c2_repairs": self.c2_repairs,
                "repaired_absent": self.repaired_absent, "pair_error": self.pair_error,
                "singleton": self.singleton}


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


PAIR_INSTRUCTIONS = (
    "You compare one claim against one sentence and report what the claim says that the sentence does not. "
    "Judge only against the sentence's words: not the rest of the book, not what you know about the author.\n\n"
    "1. Split the claim into consecutive segments, copied from it word for word. Joined in order they must reproduce "
    "the claim exactly: nothing added, nothing dropped, nothing repeated. Split where the claim states a separate "
    "thing -- a second action, a cause, a means, a consequence, a qualifier. A claim that states one single thing is "
    "one segment.\n"
    "2. For each segment write `read_as`: that segment as a complete proposition, using only words from the claim. "
    "Borrow the subject from elsewhere in the claim when the segment lacks one, and inflect a verb to agree with it "
    "if you must. Never bring in a word from the sentence.\n"
    "3. For each segment quote in `evidence_span` the part of the sentence, copied exactly, that carries it -- or "
    "null when the sentence carries nothing of it.\n"
    "4. For each segment list in `adds` everything the sentence does not have **at all**, each one copied word for "
    "word from the segment, with the kind of thing it adds:\n"
    "   - agent: an entity the sentence does not name -- it says \"It\", \"They\", \"this form\", or names someone "
    "else;\n"
    "   - cause_means: a cause or a means (\"by\", \"through\", \"leading to\");\n"
    "   - consequence: an outcome or effect;\n"
    "   - quantity_generalization: a quantity, or a scope wider than the sentence's;\n"
    "   - modality: the sentence asks, supposes or reports, and the claim asserts;\n"
    "   - evaluative: a qualifier that grades (\"genuine\", \"mere\", \"true\");\n"
    "   - other: anything else the sentence lacks.\n"
    "   **For every item you list, first look for its `counterpart`: the sentence's own words, copied exactly, that "
    "state that same content in another way.** If you find one, quote it -- the item is then a rewording, not an "
    "addition, and it will be recorded as such. Only when the sentence has nothing that states it is `counterpart` "
    "null. A pronoun or a pointer (\"it\", \"they\", \"this form\") is never a counterpart: it refers, it does not "
    "state.\n"
    "   List an addition even when the rest of the segment matches the sentence perfectly: a good rewording in one "
    "part says nothing about the others.\n"
    "5. Give `relation` for every segment, but it is read only when that segment's `adds` is empty: stated when the "
    "sentence states it in words at the same level, one_step when the same content moved to another level or another "
    "concept.\n\n"
    # Five worked pairs, authored by the dsh harness outside the 140-pair reference (item 48, DSH-50). The two
    # load-bearing contrasts: (a) against (e) -- a grading word the sentence carries is not an addition, one it does
    # not is; (b) against (d) -- the agent the sentence names is not an addition, the agent it only points at is.
    "Worked examples. Each is a claim and the sentence it was paired with; the answer shows what belongs in "
    "`adds`.\n\n"
    "(a) Claim: \"The mill was the town's principal employer.\" / Sentence: \"The mill was the town's chief source "
    "of work.\"\n"
    "    adds: [] -- \"principal employer\" is the sentence's \"chief source of work\" in other words "
    "(counterpart: \"chief source of work\"). A reworded phrase is not an addition, even when it carries a grading "
    "word.\n"
    "(b) Claim: \"The canal company paid the navvies by the week.\" / Sentence: \"The navvies were paid by the week "
    "by the canal company.\"\n"
    "    adds: [] -- the agent the sentence names in its closing phrase is the claim's subject (counterpart: \"by "
    "the canal company\"). A change of voice adds nothing.\n"
    "(c) Claim: \"The lock-keeper is considered the last authority on the water levels.\" / Sentence: \"The "
    "lock-keeper is the last authority on the water levels.\"\n"
    "    adds: [] -- \"is considered\" reports the sentence's own statement as received opinion; it carries no "
    "content of its own. Only content the sentence lacks is an addition.\n"
    "(d) Claim: \"The bargemen unloaded the coal at dawn.\" / Sentence: \"They unloaded the coal at dawn.\"\n"
    "    adds: [{\"text\": \"The bargemen\", \"kind\": \"agent\", \"counterpart\": null}] -- \"They\" refers; it "
    "does not state who unloaded the coal. No counterpart can be quoted, because a pronoun is not a statement of "
    "the entity.\n"
    "(e) Claim: \"The mill's profit rested on a genuinely fair wage.\" / Sentence: \"The mill's profit rested on a "
    "fair wage.\"\n"
    "    adds: [{\"text\": \"genuinely\", \"kind\": \"evaluative\", \"counterpart\": null}] -- the sentence states "
    "the wage was fair; \"genuinely\" grades it further, and the sentence has no words that state that grading."
)


def pair_prompt(claim: str, sentence: str) -> str:
    """The judge's whole task. It lives here, and not inside the loop below, so that a calibration run scores the
    prompt production uses rather than a copy of it (item 47). The instruction block comes first and the pair last:
    the static prefix is then a cache candidate across a run's calls (item 48, section 5)."""
    return f"{PAIR_INSTRUCTIONS}\n\nClaim: {claim}\n\nSentence: {sentence}"


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", match_form(text))


def _tiling_problem(claim: str, segments: list[ClaimSegment]) -> str | None:
    """C1 -- do the segments partition the claim? Compared on the claim's own characters, separators ignored, so a
    comma the model drops between two segments is fine and a dropped rider is not: its words would go unaccounted."""
    if not segments:
        return "no segments"
    joined, whole = _alnum("".join(s.segment for s in segments)), _alnum(claim)
    if joined == whole:
        return None
    missing = sorted(_content_terms(claim) - _content_terms(" ".join(s.segment for s in segments)))
    added = sorted(_content_terms(" ".join(s.segment for s in segments)) - _content_terms(claim))
    return (f"the segments do not reproduce the claim (missing: {missing or 'none'}; "
            f"not in the claim: {added or 'none'})")


def _span_holds(span: str | None, sentence: str) -> bool:
    """C3 -- is the span text the sentence actually contains? A fabricated or absent span never grounds anything."""
    return bool(span) and match_form(span, is_quote=True) in match_form(sentence)


def postprocess_pair(judgement: PairJudgement, claim: str, sentence: str) -> PairOutcome:
    """The deterministic checks and the derivation -- outside the LLM, every repair logged, never silent (item 48,
    section 4, v4). The model extracts; code decides. What code can guarantee: the segments tile the claim (C1), the
    reading neither drops the segment nor imports the sentence's words (C2), a quoted span is text of the sentence
    (C3), a claimed addition is text of the segment (C4). What it cannot: tell a rename from an addition -- C5 only
    flags a claimed addition whose every word is already in the sentence, because a subject swap looks exactly like
    that and is a real addition."""
    rewrites: list[str] = []
    problem = _tiling_problem(claim, judgement.segments)
    relations, raw_relations, additions, addition_texts = [], [], [], []
    invalid_span = invalid_add = invalid_counterpart = False
    rename_suspects, renames, exempted, c2_repairs = [], [], [], 0
    model_relations: list[str] = []
    sentence_terms = _content_terms(sentence)

    for i, segment in enumerate(judgement.segments, 1):
        model_relations.append(segment.relation)     # kept even when `adds` decided, so a diagnosis never infers it
        relation = "absent" if segment.adds else segment.relation

        # C2, both ways: the reading may not drop the segment (a structural connective aside), nor import the
        # sentence's vocabulary.
        dropped_all = terms_contained(segment.segment, segment.read_as)
        dropped = [term for term in dropped_all if term not in DROPPABLE_CONNECTIVES]
        exempted += [term for term in dropped_all if term in DROPPABLE_CONNECTIVES]
        # Only vocabulary taken from the *sentence* counts as imported: `read_as` restates a fragment as a
        # proposition, so a verb the claim does not contain ("occurs", "includes") is grammar, not smuggling. The
        # first arm-A run failed d12, a positive pair, on exactly that -- an instrument bug, not a judgement.
        imported = [term for term in terms_contained(segment.read_as, claim)
                    if terms_match(term, sentence_terms)]
        for problem_terms, what in ((dropped, "drops"), (imported, "imports")):
            if problem_terms:
                rewrites.append(f"segment {i}: read_as {what} {problem_terms} -> absent")
                relation, c2_repairs = "absent", c2_repairs + 1

        # C3: a segment the sentence is said to carry stands on a span the sentence contains.
        if relation != "absent" and not _span_holds(segment.evidence_span, sentence):
            rewrites.append(f"segment {i}: span is not text of the sentence -> absent")
            relation, invalid_span = "absent", True

        # C4, C5 and C6. C4: a claimed addition must be text of its own segment. C5: an addition whose every word is
        # already in the sentence is flagged, never dropped -- p11's subject swap is exactly that shape and is a real
        # addition. C6 (arm A): an addition that quotes a real counterpart from the sentence is a *rename*, not an
        # addition, and stops deciding the relation -- the comparison the model already makes for `evidence_span` and
        # never applied to the fragment it flagged.
        kept = []
        for addition in segment.adds:
            if _alnum(addition.text) and _alnum(addition.text) not in _alnum(segment.segment):
                # Unverifiable: the model attributed the fragment to a segment that does not contain it. Dropped,
                # never kept -- keeping it failed p43, a `covered` pair, on an item nothing could check (DSH-46).
                # It is an extraction-health signal, not a verdict.
                rewrites.append(f"segment {i}: addition {addition.text!r} is not text of the segment -> dropped")
                invalid_add = True
                addition_texts.append(f"invalid:{addition.text}")
                continue
            if _content_terms(addition.text) and _content_terms(addition.text) <= DROPPABLE_CONNECTIVES:
                # A structural connective carries no content, so it cannot be content the sentence lacks
                # (DSH-47 iii). p07's `other:while` was costing a positive pair.
                rewrites.append(f"segment {i}: addition {addition.text!r} is only a connective -> dropped")
                addition_texts.append(f"connective:{addition.text}")
                continue
            if not terms_contained(addition.text, sentence):
                rename_suspects.append(f"{addition.kind}:{addition.text}")
            counterpart = addition.counterpart
            if counterpart:
                if not _span_holds(counterpart, sentence):
                    rewrites.append(f"segment {i}: counterpart {counterpart!r} is not text of the sentence")
                    invalid_counterpart, counterpart = True, None
                else:
                    cp_terms = _content_terms(counterpart)
                    # A pointer is refused because it refers instead of stating. A counterpart with no content word
                    # at all is kept: "is" for "serves as" is a rename, and refusing it failed c14, a `covered` pair.
                    if (cp_terms and cp_terms <= POINTERS) or (not cp_terms and match_form(counterpart) in POINTERS):
                        rewrites.append(f"segment {i}: counterpart {counterpart!r} only points, it does not state")
                        invalid_counterpart, counterpart = True, None
            if counterpart:
                renames.append(f"{addition.kind}:{addition.text}->{counterpart}")
            else:
                kept.append(addition)
                additions.append(addition.kind)
            addition_texts.append(f"{addition.kind}:{addition.text}")

        # `raw` is the model's verdict *after* the counterpart pass -- an addition it quoted a counterpart for was
        # never a claim of addition. Taking it before hid C2 repairs on pairs whose adds all became renames.
        raw = "absent" if kept else segment.relation
        raw_relations.append(raw)
        if not kept and segment.adds and relation == "absent" and not (dropped or imported) and segment.evidence_span:
            relation = segment.relation         # nothing was added after all: the model's own wording relation stands
            rewrites.append(f"segment {i}: all {len(segment.adds)} addition(s) have counterparts -> {relation}")
        elif kept:
            relation = "absent"

        if relation == "absent" and not kept and not segment.adds:
            additions.append("other")          # a code-forced absent still carries a kind, and says it is not the model's
        relations.append(relation)

    strict = bool(relations) and all(r == "stated" for r in relations) and problem is None
    lenient = bool(relations) and "absent" not in relations and problem is None
    assert not (strict and not lenient), "a pair cannot pass strict and fail lenient"
    return PairOutcome(strict=strict, lenient=lenient, relations=tuple(relations),
                       raw_relations=tuple(raw_relations), model_relations=tuple(model_relations),
                       additions=tuple(additions), addition_texts=tuple(addition_texts),
                       renames=tuple(renames), invalid_span=invalid_span, invalid_add=invalid_add,
                       invalid_counterpart=invalid_counterpart,
                       rename_suspects=tuple(rename_suspects), exempted_terms=tuple(exempted),
                       c2_repairs=c2_repairs, pair_error=problem,
                       singleton=len(judgement.segments) == 1, rewrites=tuple(rewrites))


def judge_pair_detail(claim: str, sentence: str, client=None, callbacks=None, retries: int = 1) -> PairOutcome:
    """One call, one pair: the claim segmented and each segment placed against the sentence, then the deterministic
    checks. A tiling failure buys one bounded retry that names the problem; after that the pair fails with the
    problem recorded, never silently repaired."""
    prompt = pair_prompt(claim, sentence)
    for attempt in range(retries + 1):
        judgement = _judge(client or judge_llm, "judge_faithfulness", PairJudgement, prompt, callbacks=callbacks)
        outcome = postprocess_pair(judgement, claim, sentence)
        if outcome.pair_error is None or attempt == retries:
            return outcome
        prompt = (f"{pair_prompt(claim, sentence)}\n\nYour previous answer failed the segmentation rule: "
                  f"{outcome.pair_error}. Split the claim again so the segments, joined in order, reproduce it exactly.")
    raise AssertionError("unreachable")


def judge_pair(claim: str, sentence: str, client=None, callbacks=None) -> bool:
    """Does this sentence alone state this claim? The strict view of one pair -- the headline reading (D2), and the
    boolean the per-book loop and `judge_records` keep."""
    return judge_pair_detail(claim, sentence, client=client, callbacks=callbacks).strict


def faithfulness(record: dict, callbacks=None) -> dict[str, dict]:
    """Per book: does any pair's claim say more than its own sentence states? Each pair is judged on its own, so the
    question is well-posed -- an atomic claim against the sentence it came from. `passed` stays the strict reading
    (every pair strict), and the numbers actually read are the pair-level rates, the addition profile and the
    coverage beside them: a book's unpaired claims are judged by nothing, so the rate alone could be raised by
    routing hard claims out of the pairs (item 48, section 8)."""
    results = {}
    for cid, finding in _judged_books(record):
        pairs = finding.get("pairs") or []
        unpaired = len(finding.get("unpaired") or [])
        outcomes = [judge_pair_detail(pair["claim"], pair["sentence"], callbacks=callbacks) for pair in pairs]
        # M7 (2026-10-14): the headline view is lenient -- the strict `stated`/`one_step` boundary is below the
        # reproducibility of the people who drew it (the sheet's own definition of one_step says "reworded", while
        # four of the 14 gate pairs are `covered` on rewording notes; the labellers split 7/12 there). Strict stays
        # reported, never dropped, and `stated_typings` says whether that column means anything at all this round.
        unsupported = [pair["claim"] for pair, outcome in zip(pairs, outcomes) if not outcome.lenient]
        profile = Counter(kind for outcome in outcomes for kind in outcome.additions)
        results[cid] = {
            "pairs": len(pairs),
            "unsupported": unsupported,
            "passed": bool(pairs) and not unsupported,
            "rate": (sum(o.lenient for o in outcomes) / len(pairs)) if pairs else None,
            "rate_strict": (sum(o.strict for o in outcomes) / len(pairs)) if pairs else None,
            "stated_typings": sum(r == "stated" for o in outcomes for r in o.relations),
            "unpaired": unpaired,
            "coverage": (len(pairs) / (len(pairs) + unpaired)) if (pairs or unpaired) else None,
            "addition_profile": dict(sorted(profile.items())),          # per item, every family: diagnostic
            "defect_family_pairs": {family: sum(1 for o in outcomes if family in o.additions)
                                    for family in DEFECT_FAMILIES},     # per pair, three families: the metric
            "invalid_span": sum(o.invalid_span for o in outcomes),
            "invalid_add": sum(o.invalid_add for o in outcomes),
            "c2_repairs": sum(o.c2_repairs for o in outcomes),
            "repaired_absent": sum(o.repaired_absent for o in outcomes),
            "rename_suspects": sum(len(o.rename_suspects) for o in outcomes),
            "pair_error": sum(o.pair_error is not None for o in outcomes),
            "singletons": sum(o.singleton for o in outcomes),
            "pair_results": [o.as_row() for o in outcomes],
            "judge_version": JUDGE_VERSION,
        }
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
    """Runs both judges over a list of target records and writes one row per (claim, sentence) pair, with empty human
    fields to fill by hand: human_faithful (true/false, the strict reading), human_lenient (true/false, filled only on
    a false human_faithful -- the second column D2 keeps, which otherwise lives in the label sheets alone) and
    human_source ("A", "B", "both" or "neither"). Each row carries its `pair` index: the per-pair verdict is read by
    position, never by matching claim text, so two pairs sharing a claim inside one finding cannot label each other."""
    rows = []
    for record in records:
        judged = faithfulness(record, callbacks=callbacks)
        attributed = attribution(record, callbacks=callbacks)
        for cid, finding in _judged_books(record):
            outcomes = judged[cid]["pair_results"]
            for index, pair in enumerate(finding.get("pairs") or []):
                outcome = outcomes[index]
                rows.append({"id": record["id"], "book": cid, "pair": index, "query": record["query"],
                             "claim": pair["claim"], "sentence": pair["sentence"],
                             "faithfulness": {"passed": outcome["lenient"], "strict": outcome["strict"],
                                              "relations": outcome["relations"], "additions": outcome["additions"],
                                              "repaired_absent": outcome["repaired_absent"],
                                              "judge_version": JUDGE_VERSION},
                             "attribution": attributed.get(cid),
                             "human_faithful": None, "human_lenient": None, "human_source": None})
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"calibration_{datetime.now():%Y-%m-%d_%H%M}.json"
    path.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    return path


def _human_lenient(row: dict) -> bool | None:
    """The lenient label of a row. The sheets only fill `lenient` on a pair whose strict label is false, so a strict
    `true` implies lenient `true` -- without this rule the lenient reader would score only the negative rows and
    report false disagreement on every positive one."""
    if row.get("human_faithful") is True:
        return True
    return row.get("human_lenient")


def judge_agreement(rows: list[dict]) -> dict[str, dict]:
    """How often each judge agrees with the hand labels, over the rows that have one, and where it does not.
    `faithfulness` is the headline, lenient view (M7); `faithfulness_strict` is the second column, which is only
    meaningful in a round where the judge used `stated` at all."""
    readers = (("faithfulness", _human_lenient, lambda r: r["faithfulness"]["passed"]),
               ("faithfulness_strict", lambda r: r.get("human_faithful"),
                lambda r: r["faithfulness"].get("strict")),
               ("attribution", lambda r: r.get("human_source"), lambda r: r["attribution"]["judged"]))
    report = {}
    for judge, human, judged in readers:
        labelled = [r for r in rows if human(r) is not None]
        disagree = [f"{r['id']} {r['book']} {r.get('pair', '')}".strip()
                    for r in labelled if judged(r) != human(r)]
        report[judge] = {"labelled": len(labelled), "agree": len(labelled) - len(disagree), "disagree": disagree}
    return report


if __name__ == "__main__":
    import sys

    rows = json.loads(Path(sys.argv[1]).read_text())
    print(json.dumps(judge_agreement(rows), indent=1))
