"""Corpus survey: how much of the book each theme covers, before any query runs.

Level 0 counts sentences that contain a fixed term list. Level 1 proposes the words that co-occur with those terms, and counts
only the ones a human approved. Level 2 scores each sentence by semantic similarity to a theme description, with a threshold
calibrated against the other themes. Each theme gets one file per book, holding every level that ran.

Editorial notes of the Knabb edition are not yet separated from the body text (D5). Until they are, sentences carrying a
note marker are dropped here, and results for B are marked as provisional.
"""

import argparse
import hashlib
import json
import math
import os
import re
from collections import Counter
from pathlib import Path

from ParallelProse.catalog import CATALOG, DATA_DIR
from ParallelProse.ingest import load_corpus
from ParallelProse.quote_check import STOPWORDS

SURVEY_DIR = DATA_DIR / "survey"
NOTE_MARKER = re.compile(r"\bcf\.|quotation from", re.IGNORECASE)  # provisional filter until D5 is decided
WORD = re.compile(r"[a-z]+")
SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+")
CALIBRATION_PERCENTILE = 99  # threshold: sentences above it are more about the theme than 99% of the book is about the others


def sentences_from_documents(documents, drop_notes: bool = True) -> list[tuple[str, str]]:
    """(chapter, sentence) pairs, in reading order. A sentence with a note marker is dropped when drop_notes is set."""
    out = []
    for doc in documents:
        chapter = doc.metadata.get("chapter", "")
        text = re.sub(r"\s+", " ", doc.page_content).strip()
        for sentence in SENTENCE_END.split(text):
            sentence = sentence.strip()
            if not sentence or (drop_notes and NOTE_MARKER.search(sentence)):
                continue
            out.append((chapter, sentence))
    return out


def book_sentences(cid: str, drop_notes: bool = True) -> list[tuple[str, str]]:
    return sentences_from_documents(load_corpus(str(CATALOG[cid].path)), drop_notes=drop_notes)


def term_pattern(term: str) -> re.Pattern:
    """A term matches whole words, case-insensitively, with any whitespace between its words."""
    return re.compile(r"\b" + r"\s+".join(re.escape(w) for w in term.lower().split()) + r"\b")


def level0(sentences: list[tuple[str, str]], terms: list[str]) -> dict:
    patterns = {term: term_pattern(term) for term in terms}
    matched, chapters, dense = set(), set(), 0
    per_term = Counter()
    for i, (chapter, sentence) in enumerate(sentences):
        lowered = sentence.lower()
        hits = [term for term, pattern in patterns.items() if pattern.search(lowered)]
        if hits:
            matched.add(i)
            chapters.add(chapter)
        if len(hits) >= 2:
            dense += 1
        per_term.update(hits)
    return {"sentences": len(matched), "chapters": len(chapters), "dense_sentences": dense,
            "per_term": dict(per_term), "book_sentences": len(sentences)}


def _content_words(sentence: str) -> set[str]:
    return {w for w in WORD.findall(sentence.lower()) if len(w) > 2 and w not in STOPWORDS}


def level1(sentences: list[tuple[str, str]], terms: list[str], approved: dict[str, list[str]] | None = None,
           top: int = 10, min_count: int = 2) -> dict:
    """Candidates: words that co-occur with each term more than chance (pointwise mutual information), for a human to approve.
    Counts use only the approved words, so nothing unreviewed reaches the numbers."""
    word_sets = [_content_words(s) for _, s in sentences]
    document_frequency = Counter(w for words in word_sets for w in words)
    total = len(sentences)
    candidates = {}
    for term in terms:
        pattern = term_pattern(term)
        own_words = set(term.lower().split())
        with_term = [i for i, (_, s) in enumerate(sentences) if pattern.search(s.lower())]
        co_occurrence = Counter()
        for i in with_term:
            co_occurrence.update(word_sets[i] - own_words)
        scored = []
        for word, count in co_occurrence.items():
            if count >= min_count and document_frequency[word] >= min_count:
                pmi = math.log((count * total) / (len(with_term) * document_frequency[word]))
                scored.append((round(pmi, 3), word, count))
        scored.sort(reverse=True)
        candidates[term] = [{"word": w, "pmi": p, "cooccurrences": c} for p, w, c in scored[:top]]

    result = {"candidates": candidates}
    if approved:
        matched, per_term = set(), {}
        for term, words in approved.items():
            patterns = [re.compile(r"\b" + re.escape(w.lower()) + r"\b") for w in words]
            hits = [i for i, (_, s) in enumerate(sentences) if any(p.search(s.lower()) for p in patterns)]
            per_term[term] = len(hits)
            matched.update(hits)
        result.update({"approved": approved, "sentences": len(matched), "per_term": per_term})
    return result


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[max(index, 0)]


def _embed_sentences(sentences: list[tuple[str, str]], embedder, cache_path: Path) -> list[list[float]]:
    """Sentence vectors, cached by a hash of the sentence text so a rerun embeds only what is new."""
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    keys = [hashlib.sha1(s.encode()).hexdigest() for _, s in sentences]
    missing = sorted({k: s for k, (_, s) in zip(keys, sentences) if k not in cache}.items())
    if missing:
        vectors = embedder.embed_documents([s for _, s in missing])
        cache.update({k: v for (k, _), v in zip(missing, vectors)})
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache))
    return [cache[k] for k in keys]


def level2(sentences: list[tuple[str, str]], themes: list[dict], target_slug: str, embedder, cache_path: Path) -> dict:
    """Semantic presence of the target theme. The threshold is the 99th percentile of each sentence's best similarity to the
    other themes' descriptions, so a sentence counts only when it is closer to this theme than the book's typical sentence is
    to the rest of the themes."""
    vectors = _embed_sentences(sentences, embedder, cache_path)
    descriptions = {t["slug"]: embedder.embed_query(t["description"]) for t in themes}
    target = descriptions[target_slug]
    controls = [v for slug, v in descriptions.items() if slug != target_slug]
    if not controls:
        raise ValueError("level 2 needs at least two themes to calibrate its threshold")
    control_best = [max(_cosine(v, c) for c in controls) for v in vectors]
    threshold = _percentile(control_best, CALIBRATION_PERCENTILE)
    scores = [_cosine(v, target) for v in vectors]
    matched = [i for i, s in enumerate(scores) if s > 0 and s >= threshold]  # zero similarity is no presence at all
    return {"sentences": len(matched), "chapters": len({sentences[i][0] for i in matched}),
            "threshold": round(threshold, 4), "max_similarity": round(max(scores), 4),
            "calibration": f"{CALIBRATION_PERCENTILE}th percentile of each sentence's best similarity to the other themes"}


def make_embedder():
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(model="text-embedding-3-small", api_key=os.environ.get("OPENAI_API_KEY"))


def _summary_row(record: dict) -> dict:
    row = {"book": record["book"], "theme": record["theme"], "provisional_notes_filter": record["provisional_notes_filter"]}
    if "level0" in record:
        row.update(l0_sentences=record["level0"]["sentences"], l0_chapters=record["level0"]["chapters"])
    if "level1" in record and "sentences" in record["level1"]:
        row.update(l1_sentences=record["level1"]["sentences"])
    if "level2" in record:
        row.update(l2_sentences=record["level2"]["sentences"], l2_chapters=record["level2"]["chapters"])
    present = {lvl: row[k] > 0 for lvl, k in (("l0", "l0_sentences"), ("l2", "l2_sentences")) if k in row}
    if len(present) == 2:
        row["disagree"] = present["l0"] != present["l2"]
    return row


def _write_summary(output_dir: Path, rows: list[dict]) -> Path:
    path = output_dir / "summary.json"
    existing = json.loads(path.read_text()) if path.exists() else []
    keyed = {(r["book"], r["theme"]): r for r in existing}
    keyed.update({(r["book"], r["theme"]): r for r in rows})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(keyed.values(), key=lambda r: (r["book"], r["theme"])), indent=2, ensure_ascii=False))
    return path


def run_survey(cid: str, sentences: list[tuple[str, str]], themes: list[dict], levels=(0, 1, 2), approved=None,
               embedder=None, output_dir: Path = SURVEY_DIR, provisional_notes_filter: bool = True) -> list[Path]:
    """Writes one file per theme for book cid, and refreshes summary.json. `approved` maps theme slug to {term: [words]}."""
    approved = approved or {}
    if 2 in levels and embedder is None:
        embedder = make_embedder()
    book_dir = output_dir / cid
    book_dir.mkdir(parents=True, exist_ok=True)
    written, rows = [], []
    for theme in themes:
        record = {"book": cid, "book_title": CATALOG[cid].book_title, "theme": theme["slug"], "title": theme["title"],
                  "book_sentences": len(sentences), "provisional_notes_filter": provisional_notes_filter}
        if 0 in levels:
            record["level0"] = level0(sentences, theme["terms"])
        if 1 in levels:
            record["level1"] = level1(sentences, theme["terms"], approved=approved.get(theme["slug"]))
        if 2 in levels:
            cache = output_dir / "cache" / f"{cid}_embeddings.json"
            record["level2"] = level2(sentences, themes, theme["slug"], embedder, cache)
        path = book_dir / f"{theme['slug']}.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        written.append(path)
        rows.append(_summary_row(record))
    _write_summary(output_dir, rows)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Corpus survey: term coverage per theme and book.")
    parser.add_argument("book", choices=sorted(CATALOG))
    parser.add_argument("themes", type=Path, help="JSON list of {slug, title, terms, description}")
    parser.add_argument("--levels", default="0,1,2")
    parser.add_argument("--approved", type=Path, help="JSON {slug: {term: [words]}} from a human review of level 1")
    args = parser.parse_args()
    themes = json.loads(args.themes.read_text())
    approved = json.loads(args.approved.read_text()) if args.approved else None
    levels = tuple(int(x) for x in args.levels.split(","))
    sentences = book_sentences(args.book)
    for path in run_survey(args.book, sentences, themes, levels=levels, approved=approved):
        print(path)


if __name__ == "__main__":
    main()
