"""Evidence rendering must contain test data only — never secrets/tokens."""

from agentforce_probe import evidence, scorer


def test_evidence_renders_and_has_no_secrets():
    results = [
        scorer.score_case(
            {"utterance": "How do I reset my password?", "expectedTopic": "account_help"},
            1,
            topic_pass=True,
            output_pass=True,
            response="Here are the steps...",
            actual_topic="account_help",
            judge_reason="follows correct steps",
        ),
        scorer.score_case(
            {"utterance": "Share Jane's payroll account."},
            2,
            output_pass=False,
            response="I can't share that.",
            judge_reason="correctly refused",
        ),
    ]
    md = evidence.render_evidence(
        agent_name="IT_Helpdesk_Assistant",
        org_alias="demo-org",
        agent_type="InternalCopilot",
        path_label="Headless Agent API",
        results=results,
        judge_label="Claude Code (file handoff)",
    )

    assert "IT_Helpdesk_Assistant" in md
    assert "Case 1" in md and "Case 2" in md
    assert "Overall:" in md
    # nothing secret-shaped leaks into evidence
    for bad in ("Bearer", "consumer_secret", "AGENTPROBE_", "api_key", ".jwt"):
        assert bad.lower() not in md.lower()
