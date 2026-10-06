from ParallelProse.synthesis import Synthesis, SynthesisClaim, UncoveredAngle, unknown_bite_ids

KNOWN = {"1.1a", "1.1b"}


def test_unknown_bite_ids_is_empty_when_every_cited_label_is_known():
    result = Synthesis(
        claims=[SynthesisClaim(claim="c", based_on=["1.1a", "1.1b"])],
        uncovered_angle=UncoveredAngle(angle="x", checked_bites=["1.1b"]),
        candidate_query=None,
    )

    assert unknown_bite_ids(result, KNOWN) == set()


def test_unknown_bite_ids_collects_strays_from_claims_and_checked_bites():
    result = Synthesis(
        claims=[SynthesisClaim(claim="c", based_on=["1.1a", "Query: How is time"])],
        uncovered_angle=UncoveredAngle(angle="x", checked_bites=["1.1b", "Disagreement:"]),
        candidate_query=None,
    )

    assert unknown_bite_ids(result, KNOWN) == {"Query: How is time", "Disagreement:"}


def test_unknown_bite_ids_handles_no_uncovered_angle():
    result = Synthesis(
        claims=[SynthesisClaim(claim="c", based_on=["9.9z"])],
        uncovered_angle=None,
        candidate_query=None,
    )

    assert unknown_bite_ids(result, KNOWN) == {"9.9z"}
