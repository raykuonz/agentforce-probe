"""T3b: 6-axis handoff verdicts (@2) + back-compat (@1) + evidence axis rendering."""

import json

import pytest

from agentforce_probe import evidence, scorer
from agentforce_probe import judge as judge_mod


def _axis_entry(cid, val, reason="r"):
    e = {"id": cid, "reason": reason}
    for k in judge_mod.JUDGE_AXES:
        e[k] = val
    return e


def _write(tmp_path, obj):
    p = tmp_path / "verdicts.json"
    p.write_text(json.dumps(obj))
    return str(p)


# ── render_judging_md asks for the 6 axes and the @2 schema ─────────────────────

def test_judging_md_mentions_axes_and_v2_schema():
    md = judge_mod.render_judging_md("Agent", "/x/task.json", "/x/verdicts.json")
    for axis in judge_mod.JUDGE_AXES:
        assert axis in md, f"render_judging_md missing axis {axis}"
    assert "judge-verdicts@2" in md


# ── load_verdicts @2: derive verdict from composite ─────────────────────────────

def test_load_verdicts_v2_high_axes_pass(tmp_path):
    obj = {"schema": judge_mod.VERDICTS_SCHEMA, "agent": "A",
           "verdicts": [_axis_entry(1, 0.9, "good")]}
    by_id, warnings = judge_mod.load_verdicts(_write(tmp_path, obj))
    assert by_id[1]["verdict"] == "PASS"
    assert by_id[1]["axes"] is not None
    assert by_id[1]["composite"] is not None


def test_load_verdicts_v2_low_axes_fail(tmp_path):
    obj = {"schema": judge_mod.VERDICTS_SCHEMA, "agent": "A",
           "verdicts": [_axis_entry(1, 0.15, "bad")]}
    by_id, _ = judge_mod.load_verdicts(_write(tmp_path, obj))
    assert by_id[1]["verdict"] == "FAIL"


# ── load_verdicts @1: legacy still works, axes None, warns ──────────────────────

def test_load_verdicts_v1_legacy_back_compat(tmp_path):
    obj = {"schema": judge_mod.VERDICTS_SCHEMA_V1, "agent": "A",
           "verdicts": [{"id": 1, "verdict": "PASS", "reason": "x"}]}
    by_id, warnings = judge_mod.load_verdicts(_write(tmp_path, obj))
    assert by_id[1]["verdict"] == "PASS"
    assert by_id[1]["axes"] is None
    assert any("@1" in w or "legacy" in w.lower() for w in warnings)


# ── load_verdicts rejects an entry with neither verdict nor axes ────────────────

def test_load_verdicts_rejects_empty_entry(tmp_path):
    obj = {"schema": judge_mod.VERDICTS_SCHEMA, "agent": "A",
           "verdicts": [{"id": 1, "reason": "no verdict, no axes"}]}
    with pytest.raises(judge_mod.HandoffError):
        judge_mod.load_verdicts(_write(tmp_path, obj))


# ── evidence renders the axis breakdown only when axes present ──────────────────

def _result_with_axes(axes):
    return scorer.score_case(
        {"utterance": "q", "expectedOutcome": "o"}, 1,
        output_pass=True, response="resp", judge_reason="ok", axes=axes,
    )


def test_evidence_renders_axes_when_present():
    axes = {k: 0.8 for k in judge_mod.JUDGE_AXES}
    md = evidence.render_evidence(
        agent_name="A", org_alias="o", agent_type="InternalCopilot",
        path_label="p", results=[_result_with_axes(axes)], judge_label="anthropic",
    )
    assert "axes:" in md
    assert "composite" in md
    assert "factualAccuracy" in md


def test_evidence_no_axis_block_when_axes_none():
    md = evidence.render_evidence(
        agent_name="A", org_alias="o", agent_type="InternalCopilot",
        path_label="p", results=[_result_with_axes(None)], judge_label="anthropic",
    )
    assert "axes:" not in md
