"""Per-book vocabulary lookup, decoupled from any theme or query round (survey.py's concern is different: whether
a theme is covered, not whether one word exists). Built once per book, straight from `load_corpus`, with no
embedding and no LLM call, so it carries no lag: it can be handed over before the first query of a batch is
written, let alone run. Answers one question: does this word (or something close to it) appear in the book?
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from difflib import get_close_matches

from ParallelProse.catalog import CATALOG, DATA_DIR
from ParallelProse.ingest import load_corpus

VOCABULARY_DIR = DATA_DIR / "vocabulary"
WORD = re.compile(r"[a-z]+")


def build_vocabulary(cid: str) -> Counter:
    """Lowercased word -> how many times it occurs in the book's own text."""
    text = " ".join(doc.page_content for doc in load_corpus(str(CATALOG[cid].path)))
    return Counter(WORD.findall(text.lower()))


def save_vocabulary(cid: str, counts: Counter, output_dir: Path = VOCABULARY_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{cid}.json"
    path.write_text(json.dumps(dict(sorted(counts.items())), indent=2, ensure_ascii=False))
    return path


def load_vocabulary(cid: str, input_dir: Path = VOCABULARY_DIR) -> Counter:
    return Counter(json.loads((input_dir / f"{cid}.json").read_text()))


def lookup(term: str, vocabulary: Counter, max_suggestions: int = 3) -> dict:
    """exists/count for the exact word (case folded). When absent, `nearest` lists the closest words the book
    actually has, by spelling, not by a dictionary — so a found "nearest" is always something the book supports."""
    word = term.strip().lower()
    if word in vocabulary:
        return {"term": term, "exists": True, "count": vocabulary[word], "nearest": []}
    close = get_close_matches(word, vocabulary.keys(), n=max_suggestions, cutoff=0.6)
    return {"term": term, "exists": False, "count": 0,
            "nearest": [{"word": w, "count": vocabulary[w]} for w in close]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Per-book vocabulary: build the index, or look up terms in it.")
    parser.add_argument("book", choices=sorted(CATALOG))
    parser.add_argument("terms", nargs="*", help="words to look up; with none, (re)builds and saves the index")
    args = parser.parse_args()
    if not args.terms:
        path = save_vocabulary(args.book, build_vocabulary(args.book))
        print(path)
        return
    vocabulary = load_vocabulary(args.book)
    for term in args.terms:
        print(json.dumps(lookup(term, vocabulary), ensure_ascii=False))


if __name__ == "__main__":
    main()
