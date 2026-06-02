"""evidence rendering detail branches + write_evidence round-trip."""

from agentforce_probe import evidence
from agentforce_probe.scorer import score_case


def _case(**over):
    base = {
        "number": 1,
        "utterance": "u",
        "topic": "PASS",
        "actions": "PASS",
        "output": "PASS",
        "response": "line one\nline two",
        "expectedTopic": "Orders",
        "expectedActions": ["LookupOrder"],
        "actualTopic": "Orders",
        "actualActions": ["LookupOrder"],
        "judge_reason": "looks good",
    }
    base.update(over)
    return base


def test_render_full_case_with_details():
    md = evidence.render_evidence(
        agent_name="Support",
        org_alias="myorg",
        agent_type="ExternalCopilot",
        path_label="Testing Center",
        results=[_case()],
        judge_label="Testing Center",
    )
    assert "# Agent Probe Evidence — Support" in md
    assert "Overall: 3/3 = 100%" in md
    assert "expected `Orders`, got `Orders`" in md
    assert "expected `LookupOrder`, got `LookupOrder`" in md
    assert "reason: looks good" in md
    assert "> line one" in md and "> line two" in md


def test_render_filtered_dashes():
    c = score_case({"utterance": "u"}, 1, output_pass=True, response="hi")
    md = evidence.render_evidence(agent_name="A", org_alias="o", agent_type="t", path_label="p", results=[c])
    assert "_(no expectedTopic)_" in md
    assert "_(no expectedActions)_" in md


def test_render_no_response_placeholder():
    md = evidence.render_evidence(
        agent_name="A", org_alias="o", agent_type="t", path_label="p", results=[_case(response="")]
    )
    assert "_(no response captured)_" in md


def test_render_topic_no_expectation_returns_blank_detail():
    # topic != "-" but both expected/actual None -> blank detail branch
    c = _case(topic="PASS", expectedTopic=None, actualTopic=None)
    md = evidence.render_evidence(agent_name="A", org_alias="o", agent_type="t", path_label="p", results=[c])
    assert "topic: **PASS**" in md


def test_fmt_actions_empty():
    assert evidence._fmt_actions([]) == "—"
    assert evidence._fmt_actions(None) == "—"


def test_write_evidence_roundtrip(tmp_path):
    p = tmp_path / "ev.md"
    evidence.write_evidence(str(p), "hello evidence")
    assert p.read_text(encoding="utf-8") == "hello evidence"
