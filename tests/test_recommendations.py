"""recommendations.analyze / render: actionable suggestions from scored cases."""

from agentforce_probe import recommendations as rec
from agentforce_probe.scorer import score_case


def _scored(spec_case, number, **kw):
    return score_case(spec_case, number, **kw)


def test_empty_results_flags_no_cases():
    pct, recs = rec.analyze([])
    assert pct == 0
    assert recs[0]["severity"] == "high"
    assert "No cases" in recs[0]["title"]


def test_healthy_run_gives_info():
    cases = [_scored({"utterance": "u", "expectedOutcome": "o"}, 1, output_pass=True, response="hi")]
    pct, recs = rec.analyze(cases)
    assert pct == 100
    assert len(recs) == 1 and recs[0]["severity"] == "info"
    assert "healthy" in recs[0]["title"]


def test_empty_response_is_high_severity():
    cases = [_scored({"utterance": "u", "expectedOutcome": "o"}, 1, output_pass=False, response="")]
    pct, recs = rec.analyze(cases)
    titles = [r["title"] for r in recs]
    assert any("empty agent response" in t for t in titles)
    assert recs[0]["severity"] == "high"  # empty-response listed first


def test_output_fail_lists_cases_and_reasons():
    cases = [
        _scored({"utterance": "a", "expectedOutcome": "x"}, 1, output_pass=True, response="ok"),
        _scored(
            {"utterance": "b", "expectedOutcome": "y"}, 2, output_pass=False, response="bad", judge_reason="leaked PII"
        ),
    ]
    pct, recs = rec.analyze(cases)
    out = next(r for r in recs if "Output assertions" in r["title"])
    assert "#2" in out["detail"]
    assert "leaked PII" in out["detail"]


def test_topic_mismatch_medium():
    cases = [
        _scored(
            {"utterance": "u", "expectedOutcome": "o", "expectedTopic": "Orders"},
            1,
            output_pass=True,
            topic_pass=False,
            response="r",
            actual_topic="General",
        )
    ]
    pct, recs = rec.analyze(cases)
    t = next(r for r in recs if "Topic routing" in r["title"])
    assert t["severity"] == "medium"
    assert "expected `Orders`, got `General`" in t["detail"]


def test_actions_mismatch_medium():
    cases = [
        _scored(
            {"utterance": "u", "expectedOutcome": "o", "expectedActions": ["DoX"]},
            1,
            output_pass=True,
            actions_pass=False,
            response="r",
            actual_actions=["DoY"],
        )
    ]
    pct, recs = rec.analyze(cases)
    a = next(r for r in recs if "Expected actions" in r["title"])
    assert a["severity"] == "medium"
    assert "DoX" in a["detail"]


def test_total_wipeout_flags_environment():
    cases = [
        _scored({"utterance": "a", "expectedOutcome": "x"}, 1, output_pass=False, response="r"),
        _scored({"utterance": "b", "expectedOutcome": "y"}, 2, output_pass=False, response="r"),
    ]
    pct, recs = rec.analyze(cases)
    assert pct == 0
    assert any("Everything failed" in r["title"] for r in recs)


def test_render_contains_icons_and_arrows():
    cases = [_scored({"utterance": "u", "expectedOutcome": "o"}, 1, output_pass=False, response="")]
    out = rec.render(cases)
    assert "Recommendations:" in out
    assert "🔴" in out
    assert "→" in out


def test_render_healthy():
    cases = [_scored({"utterance": "u", "expectedOutcome": "o"}, 1, output_pass=True, response="hi")]
    out = rec.render(cases)
    assert "🟢" in out
