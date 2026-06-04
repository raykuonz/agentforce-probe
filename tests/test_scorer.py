"""Tests for the assertion-filtering scorer."""

from agentforce_probe import scorer


def test_topic_scored_only_when_expected():
    # No expectedTopic -> topic dimension is "-" and not counted.
    case = {"utterance": "hi"}
    r = scorer.score_case(case, 1, topic_pass=True, output_pass=True)
    assert r["topic"] == "-"
    assert r["output"] == "PASS"

    # expectedTopic present -> topic is scored.
    case2 = {"utterance": "hi", "expectedTopic": "greetings"}
    r2 = scorer.score_case(case2, 1, topic_pass=False, output_pass=True)
    assert r2["topic"] == "FAIL"


def test_actions_scored_only_when_expected():
    case = {"utterance": "x", "expectedActions": ["DoThing"]}
    r = scorer.score_case(case, 1, actions_pass=True, output_pass=True)
    assert r["actions"] == "PASS"

    case2 = {"utterance": "x"}
    r2 = scorer.score_case(case2, 1, actions_pass=True, output_pass=True)
    assert r2["actions"] == "-"


def test_output_always_scored_when_evaluated():
    case = {"utterance": "x"}
    r = scorer.score_case(case, 1, output_pass=False)
    assert r["output"] == "FAIL"


def test_aggregate_ignores_dash_dimensions():
    results = [
        scorer.score_case({"utterance": "a", "expectedTopic": "t"}, 1, topic_pass=True, output_pass=True),
        scorer.score_case({"utterance": "b"}, 2, output_pass=False),
    ]
    agg, total_pass, total = scorer.aggregate(results)
    # topic: only case 1 declared it -> 1/1; output: 2 cases -> 1/2; actions: 0/0
    assert agg["topic"] == [1, 1]
    assert agg["output"] == [1, 2]
    assert agg["actions"] == [0, 0]
    assert total_pass == 2
    assert total == 3


def test_output_not_scored_when_output_pass_none():
    r = scorer.score_case({"utterance": "x"}, 1, output_pass=None)
    assert r["output"] == "-"


def test_aggregate_excludes_case_with_no_output():
    r = scorer.score_case({"utterance": "x"}, 1, output_pass=None)
    agg, total_pass, total = scorer.aggregate([r])
    assert agg["output"] == [0, 0]
    assert total == 0
