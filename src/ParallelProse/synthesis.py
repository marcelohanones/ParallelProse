from ParallelProse.catalog import CATALOG, REPO_ROOT, DATA_DIR
from ParallelProse.agent import ComposerAnswer
from pathlib import Path
import json
from pydantic import BaseModel


def save_bite(path: Path, objective: str, query: str, answer: ComposerAnswer) -> None:
    """Appends one finished bite to the session file at path, creating it with objective if it doesn't exist yet."""
    if not path.exists():
        session = {"objective": objective, "bites": []}
    else:
        session = json.loads(path.read_text())
    session["bites"].append({"query": query, "answer": answer.model_dump()})
    path.write_text(json.dumps(session, indent=2))


def load_bites(path: Path) -> tuple[str, list[tuple[str, ComposerAnswer]]]:
    """Reads the session file back as (objective, list of (query, answer) bites)."""
    session = json.loads(path.read_text())
    bites = [(b["query"], ComposerAnswer.model_validate(b["answer"])) for b in session["bites"]]
    return session["objective"], bites


class SynthesisClaim(BaseModel):
    claim: str  # one connective statement toward the objective
    based_on: list[str]  # the query text of each bite this claim draws on


class Synthesis(BaseModel):
    claims: list[SynthesisClaim]  # the narrative, decomposed into attributable pieces
    uncovered_angle: str | None  # a facet of the objective no bite's query/finding touches
    candidate_query: str | None  # suggested next query — never executed, only surfaced


def synthesize(objective: str, bites: list[tuple[str, ComposerAnswer]]) -> Synthesis:
    """Weaves finished bites into a connective, attributable narrative toward objective, and names one gap."""
    # 1 - render each bite via the existing format_answer, tagged by its own query
    bites_text = "\n\n".join(f"Query: {q}\n{format_answer(a)}" for q, a in bites)

    # 2 - build the prompt: objective + rendered bites + the grounding rule
    prompt = f"Objective: {objective}\n\nBites:\n{bites_text}\n\n" \
        #                     "Instructions: each claim must name which bite(s) (by query) it is based_on; " \
    #                     "never assert something those specific bites don't themselves establish. " \
    #                     "Only set uncovered_angle/candidate_query after checking every bite's query " \
    #                     "and finding for it, not before."

    # 3 - call structured output, return directly
    llm_call = llm.with_structured_output(Synthesis)
    return llm_call.invoke(prompt)
