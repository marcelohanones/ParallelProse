from ParallelProse import replay_e


def record(retry_a=False, retry_b=False, label_a="ok", label_b="silent"):
    return {
        "id": "g01", "query": "what keeps people sunk in sleep?",
        "chunks": {"A": ["the a passage"], "B": None},
        "retrieval": {
            "A": {"label": label_a, "reason": "p_answers=yes", "silence_cause": None, "P": "pa",
                  "retry_used": retry_a,
                  "lineage": [{"iteration": 0, "tool": "call_parent_retriever",
                               "args": {"query": "q"}, "forced_retriever": False}]},
            "B": {"label": label_b, "reason": "p_answers=no", "silence_cause": "absence", "P": None,
                  "retry_used": retry_b, "lineage": []},
        },
    }


def test_corpora_of_carries_the_slot_and_never_a_missing_chunk_list():
    corpora = replay_e.corpora_of(record())

    assert corpora["A"]["chunks"] == ["the a passage"]
    assert corpora["B"]["chunks"] == []            # None in the file, never None to format_context
    assert corpora["A"]["narrowed_query"] is None  # frozen evidence: no new query to try
    assert corpora["B"]["silence_cause"] == "absence"
    assert set(corpora) == {"A", "B"}


def test_one_book_retrying_puts_the_whole_entry_on_the_second_look():
    assert replay_e.final_look(replay_e.corpora_of(record())) == "e_first"
    assert replay_e.final_look(replay_e.corpora_of(record(retry_b=True))) == "e_second"


def test_recorded_labels_reads_every_book_of_every_record():
    assert replay_e.recorded_labels([record()]) == {("g01", "A"): "ok", ("g01", "B"): "silent"}


def test_a_false_ok_is_reported_apart_from_the_agreement_count():
    recorded = {("g01", "A"): "ok", ("g01", "B"): "silent", ("g02", "A"): "ok"}
    replayed = {("g01", "A"): "ok", ("g01", "B"): "ok", ("g02", "A"): "silent"}

    report = replay_e.compare(replayed, recorded)

    assert report["agree"] == 1 and report["total"] == 3
    assert [m["ref"] for m in report["moves"]] == ["g01 B", "g02 A"]
    assert [m["ref"] for m in report["false_ok"]] == ["g01 B"]  # silent -> ok only, never the reverse


def test_replay_judges_each_record_with_the_look_the_graph_would_have_used(monkeypatch):
    seen = []

    class Verdict:
        def __init__(self, corpus_id):
            self.corpus_id, self.p_adjacent, self.p_answers, self.P = corpus_id, "yes", "yes", "p"

    def judge(name):
        def run(query, corpora):
            seen.append((name, query, sorted(corpora)))
            return type("Batch", (), {"verdicts": [Verdict(c) for c in corpora]})()
        return run

    labels = replay_e.replay([record(), record(retry_a=True) | {"id": "g02"}],
                             {"e_first": judge("e_first"), "e_second": judge("e_second")})

    assert [name for name, _, _ in seen] == ["e_first", "e_second"]
    assert labels == {("g01", "A"): "ok", ("g01", "B"): "ok",
                      ("g02", "A"): "ok", ("g02", "B"): "ok"}
