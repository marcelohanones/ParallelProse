from ParallelProse.agent import ComposerAnswer, format_answer, llm
from pathlib import Path
import json
from pydantic import BaseModel

def save_bite(path: Path, theme: str, thesis: str, query: str, answer: ComposerAnswer, extra: dict | None = None) -> None:
    """Appends one finished bite to the session file at path, creating it with theme/thesis if it doesn't exist yet. `extra` is stored beside the answer, never inside it."""
    if not path.exists():
        session = {"theme": theme, "thesis": thesis, "bites": []}
    else:
        session = json.loads(path.read_text())
    session["bites"].append({"query": query, "answer": answer.model_dump(), **(extra or {})})
    path.write_text(json.dumps(session, indent=2))


def load_bites(path: Path) -> tuple[str, str, list[tuple[str, ComposerAnswer]]]:
    """Reads the session file back as (theme, thesis, list of (query, answer) bites)."""
    session = json.loads(path.read_text())
    bites = [(b["query"], ComposerAnswer.model_validate(b["answer"])) for b in session["bites"]]
    return session["theme"], session["thesis"], bites


def save_synthesis(path: Path, result: "Synthesis") -> None:
    """Stores the latest synthesize() result under the session file's own "synthesis" key, clearing any earlier synthesis_error."""
    session = json.loads(path.read_text())
    session.pop("synthesis_error", None)
    session["synthesis"] = result.model_dump()
    path.write_text(json.dumps(session, indent=2))


def save_synthesis_error(path: Path, message: str) -> None:
    """Records a failed synthesis under "synthesis_error" and drops any earlier "synthesis", so the thesis file never shows a stale result as current."""
    session = json.loads(path.read_text())
    session.pop("synthesis", None)
    session["synthesis_error"] = message
    path.write_text(json.dumps(session, indent=2))


class SynthesisClaim(BaseModel):
    claim: str  # one connective statement toward the thesis
    based_on: list[str]  # the bite label (e.g. "1.1a") of each bite this claim draws on


class UncoveredAngle(BaseModel):
    angle: str  # the part of the theme/thesis no bite's finding addresses
    checked_bites: list[str]  # the bite label of every bite that was actually checked against this angle


class Synthesis(BaseModel):
    claims: list[SynthesisClaim]  # the narrative, decomposed into attributable pieces
    uncovered_angle: UncoveredAngle | None  # a gap, with which bites were checked to confirm it
    candidate_query: str | None  # suggested next query — never executed, only surfaced


class UnknownBiteLabelError(ValueError):
    """synthesize() cited a bite label it was not given."""


def unknown_bite_ids(result: Synthesis, known_labels: set[str]) -> set[str]:
    """Every bite label that result cites in a claim's based_on or in uncovered_angle's checked_bites, but that is not one of known_labels."""
    cited = {label for claim in result.claims for label in claim.based_on}
    if result.uncovered_angle is not None:
        cited |= set(result.uncovered_angle.checked_bites)
    return cited - known_labels


def synthesize(theme: str, thesis: str, bites: list[tuple[str, str, ComposerAnswer]]) -> Synthesis:
    """Weaves finished bites into a connective, attributable narrative toward thesis, and names one gap
    against the theme. `theme` only ever drives uncovered_angle/candidate_query — claims stay grounded
    in thesis + bites alone, never in the theme's own (possibly anachronistic) wording. Each bite is a
    (label, query, answer) triple; the model cites bites by label, and a label it invents raises ValueError."""
    # 1 - render each bite via the existing format_answer, tagged by its label and its own query
    bites_text = "\n\n".join(f"[{label}] Query: {q}\n{format_answer(a)}" for label, q, a in bites)

    # 2 - build the prompt: thesis + rendered bites drive claims; theme only drives the gap-check
    prompt = f"Thesis: {thesis}\n\nBites:\n{bites_text}\n\n" \
             "Instructions for claims: actively look for pairs or groups of bites whose findings " \
             "genuinely relate to each other toward the thesis — in particular, check the thesis's " \
             "own named points of disagreement (e.g. its stated cause vs. its stated remedy) and " \
             "connect whichever bites address each one. Write a claim based on a single bite only " \
             "when no other bite's content genuinely relates to it — do not default to one claim " \
             "per bite. Each claim must name which bite(s) it is based_on, using only the label between " \
             "the square brackets exactly as shown (e.g. 1.1a, never 'Bite 1.1a' or the query text), and must " \
             "never assert something those specific bites don't themselves establish; never invent " \
             "a connection between bites that isn't actually there just to combine them. Every bite " \
             "must appear in at least one claim's based_on — none skipped, even if a bite only ever " \
             "fits on its own.\n\n" \
             f"Theme (for the gap-check only, never for claims): {theme}\n\n" \
             "Instructions for uncovered_angle/candidate_query, in this strict order: " \
             "FIRST, independently of the theme, break the thesis sentence down into its own " \
             "distinct points yourself, in your own words — do not reuse any example terminology " \
             "from these instructions, derive the points fresh from this specific thesis's actual " \
             "wording. Then check each point you derived, one at a time, against the actual " \
             "content of the bites' findings (not just their query wording) to see whether it is " \
             "genuinely addressed. If any point you derived has no bite genuinely addressing it, " \
             "that is the uncovered_angle — use it, and do not let the theme override it. ONLY if " \
             "every point you derived already has a bite genuinely addressing it, THEN check " \
             "whether the theme raises an additional angle no bite addresses, and use that instead. " \
             "Treat any scale or number in the theme (e.g. 'millions') as relative to each book's " \
             "own era, not literal — look for a large, simultaneous, public audience in whatever " \
             "form was large for that era, never for a literal count. Phrase candidate_query around " \
             "that structural role in each book's own language, never around the theme's literal " \
             "modern term.\n\n" \
             "uncovered_angle itself must list checked_bites: every single bite's bracketed label you actually " \
             "looked at before concluding none of them cover this angle - if you cannot name which " \
             "bites you checked, you have not actually verified the gap, and must not set " \
             "uncovered_angle at all. Never attribute specific content to a bite (e.g. 'bite X " \
             "states...') unless that content is genuinely present in that bite's own finding text."

    # 3 - call structured output, return directly
    llm_call = llm.with_structured_output(Synthesis)
    result = llm_call.invoke(prompt)

    # 4 - every cited label must be a bite label this call was given; a stray one fails loudly
    unknown = unknown_bite_ids(result, {label for label, _, _ in bites})
    if unknown:
        raise UnknownBiteLabelError(f"synthesis cited unknown bite labels: {sorted(unknown)}")
    return result
