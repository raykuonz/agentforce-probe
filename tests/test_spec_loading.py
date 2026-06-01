"""Tests for spec loading + validation."""

import pytest

from agentforce_probe import scorer

EXAMPLES = "examples/specs"


def test_load_example_external_spec():
    spec = scorer.load_spec(f"{EXAMPLES}/Support_Concierge-testSpec.yaml")
    assert spec["subjectName"] == "Support_Concierge"
    assert len(spec["testCases"]) == 4
    # first case declares topic + actions
    c0 = spec["testCases"][0]
    assert c0["expectedTopic"] == "order_status"
    assert c0["expectedActions"] == ["LookupOrderStatus"]


def test_load_example_internal_spec():
    spec = scorer.load_spec(f"{EXAMPLES}/IT_Helpdesk_Assistant-testSpec.yaml")
    assert spec["subjectName"] == "IT_Helpdesk_Assistant"
    assert len(spec["testCases"]) == 4


def test_missing_spec_raises():
    with pytest.raises(scorer.SpecError):
        scorer.load_spec("does/not/exist.yaml")


def test_spec_without_testcases_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("name: nope\n")
    with pytest.raises(scorer.SpecError):
        scorer.load_spec(str(p))


def test_case_missing_utterance_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("name: x\ntestCases:\n  - expectedTopic: t\n")
    with pytest.raises(scorer.SpecError):
        scorer.load_spec(str(p))
