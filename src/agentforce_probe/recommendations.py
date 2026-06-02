"""Actionable recommendations from a scored run.

Pure logic: given the list of scored case dicts (the unified model from
scorer.py) plus the aggregate, produce human-readable, prioritized suggestions
for *why* a run scored low and *what to do next*. No I/O, no secrets.

The goal is that a developer (or a Claude Code session driving this CLI) gets a
concrete next step instead of a bare percentage.
"""

from .scorer import aggregate

# Threshold below which the overall run is considered "needs attention".
LOW_SCORE_PCT = 80


def _pct(part, whole):
    return round(100 * part / whole) if whole else 0


def analyze(results):
    """Return (overall_pct, recommendations) for a list of scored case dicts.

    `recommendations` is a list of {severity, title, detail} dicts, ordered most
    severe first. severity ∈ {"high", "medium", "info"}.
    """
    agg, total_pass, total = aggregate(results)
    pct = _pct(total_pass, total)
    recs = []

    n_cases = len(results)
    if n_cases == 0:
        recs.append(
            {
                "severity": "high",
                "title": "No cases were scored",
                "detail": "The spec produced zero scored cases. Check that testCases[] is non-empty "
                "and that the agent returned responses.",
            }
        )
        return pct, recs

    # Empty / missing responses → the agent isn't answering (session, auth, or
    # wrong agent). This dominates everything else.
    empty = [r for r in results if not (r.get("response") or "").strip()]
    if empty:
        nums = ", ".join(f"#{r['number']}" for r in empty)
        recs.append(
            {
                "severity": "high",
                "title": f"{len(empty)} case(s) had an empty agent response ({nums})",
                "detail": "An empty response usually means the session never produced output: "
                "check the agent is active & connected, the BotDefinition Id is correct, "
                "and (Internal path) the Agent API session minted a real JWT. Run `doctor`.",
            }
        )

    # Output (LLM-as-judge) is the primary behavioral signal.
    out_pass, out_total = agg["output"]
    if out_total and out_pass < out_total:
        failed = [r for r in results if r.get("output") == "FAIL"]
        nums = ", ".join(f"#{r['number']}" for r in failed)
        reasons = [r.get("judge_reason") for r in failed if r.get("judge_reason")]
        detail = (
            f"output (judge) passed {out_pass}/{out_total}. Failing: {nums}. "
            "Inspect each case's expectedOutcome wording — vague or over-strict expectations "
            "cause false FAILs. If using the handoff judge, re-read the agent responses in the "
            "evidence file before trusting the verdict."
        )
        if reasons:
            detail += " Judge reasons: " + " | ".join(reasons[:3])
        recs.append({"severity": "high", "title": "Output assertions failing", "detail": detail})

    # Topic mismatches → routing problem, list expected vs actual.
    topic_pass, topic_total = agg["topic"]
    if topic_total and topic_pass < topic_total:
        mism = [r for r in results if r.get("topic") == "FAIL"]
        lines = [f"#{r['number']}: expected `{r.get('expectedTopic')}`, got `{r.get('actualTopic')}`" for r in mism]
        recs.append(
            {
                "severity": "medium",
                "title": f"Topic routing mismatch in {len(mism)} case(s)",
                "detail": "The agent routed to a different topic than expected. Either the topic "
                "classifier needs tuning or the spec's expectedTopic is wrong. " + "; ".join(lines[:5]),
            }
        )

    # Action mismatches → missing tool/flow invocation.
    act_pass, act_total = agg["actions"]
    if act_total and act_pass < act_total:
        mism = [r for r in results if r.get("actions") == "FAIL"]
        lines = [f"#{r['number']}: expected {r.get('expectedActions')}, got {r.get('actualActions')}" for r in mism]
        recs.append(
            {
                "severity": "medium",
                "title": f"Expected actions not invoked in {len(mism)} case(s)",
                "detail": "The agent did not invoke the expected action(s)/flow(s). Check the topic's "
                "action wiring and that the utterance actually triggers the intent. " + "; ".join(lines[:5]),
            }
        )

    # Whole-run collapse → very likely an environment/auth problem, not content.
    if pct == 0 and total > 0:
        recs.append(
            {
                "severity": "high",
                "title": "Everything failed (0%)",
                "detail": "A total wipeout is more often an environment problem than a content one: "
                "wrong org alias, wrong agent type (External vs Internal), expired creds, or a judge "
                "misconfiguration. Run `doctor` and verify one case manually before re-running.",
            }
        )

    if not recs and pct >= LOW_SCORE_PCT:
        recs.append(
            {
                "severity": "info",
                "title": f"Looks healthy ({pct}%)",
                "detail": "No failing assertions detected. Consider adding edge-case utterances "
                "(adversarial, out-of-scope, multi-turn) to harden coverage.",
            }
        )

    return pct, recs


def render(results):
    """Render recommendations as a plain-text block for the CLI."""
    pct, recs = analyze(results)
    icons = {"high": "🔴", "medium": "🟡", "info": "🟢"}
    lines = ["", "Recommendations:"]
    if not recs:  # pragma: no cover - analyze() always returns at least one rec
        lines.append("  (none)")
        return "\n".join(lines)
    for r in recs:
        lines.append(f"  {icons.get(r['severity'], '•')} {r['title']}")
        lines.append(f"     → {r['detail']}")
    return "\n".join(lines)
