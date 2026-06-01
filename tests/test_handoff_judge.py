"""Tests for the Claude Code file-handoff judge protocol (schema + validation)."""

import json

import pytest

from agentforce_probe import judge


def _spec():
    return {
        "subjectName": "Demo",
        "testCases": [
            {"utterance": "q1", "expectedOutcome": "answer 1"},
            {"utterance": "q2", "expectedOutcome": "answer 2", "expectedTopic": "t2"},
        ],
    }


def _raw_results():
    return [
        {"number": 1, "utterance": "q1", "response": "r1", "topic": None, "actions": []},
        {"number": 2, "utterance": "q2", "response": "r2", "topic": "t2", "actions": []},
    ]


def test_build_task_package_shape_and_no_secrets():
    task = judge.build_task_package("Demo", "myorg", _spec(), _raw_results())
    assert task["schema"] == judge.TASK_SCHEMA
    assert task["agent"] == "Demo"
    assert len(task["cases"]) == 2
    assert task["cases"][0]["expected_outcome"] == "answer 1"
    # serialized task package must not contain anything secret-shaped.
    blob = json.dumps(task)
    for bad in ("consumer", "secret", "Bearer", "api_key", "AGENTPROBE_"):
        assert bad.lower() not in blob.lower()


def test_load_verdicts_roundtrip(tmp_path):
    p = tmp_path / "v.json"
    p.write_text(
        json.dumps(
            {
                "schema": judge.VERDICTS_SCHEMA,
                "agent": "Demo",
                "verdicts": [
                    {"id": 1, "verdict": "PASS", "reason": "ok"},
                    {"id": 2, "verdict": "FAIL", "reason": "leaked"},
                ],
            }
        )
    )
    by_id, warnings = judge.load_verdicts(str(p))
    assert warnings == []
    assert by_id[1]["verdict"] == "PASS"
    assert by_id[2]["verdict"] == "FAIL"


def test_load_verdicts_rejects_illegal_verdict(tmp_path):
    p = tmp_path / "v.json"
    p.write_text(
        json.dumps(
            {
                "schema": judge.VERDICTS_SCHEMA,
                "verdicts": [{"id": 1, "verdict": "MAYBE", "reason": "?"}],
            }
        )
    )
    with pytest.raises(judge.HandoffError):
        judge.load_verdicts(str(p))


def test_load_verdicts_rejects_duplicate_id(tmp_path):
    p = tmp_path / "v.json"
    p.write_text(
        json.dumps(
            {
                "schema": judge.VERDICTS_SCHEMA,
                "verdicts": [
                    {"id": 1, "verdict": "PASS", "reason": "a"},
                    {"id": 1, "verdict": "FAIL", "reason": "b"},
                ],
            }
        )
    )
    with pytest.raises(judge.HandoffError):
        judge.load_verdicts(str(p))


def test_load_verdicts_schema_mismatch_warns(tmp_path):
    p = tmp_path / "v.json"
    p.write_text(
        json.dumps(
            {
                "schema": "wrong/schema@9",
                "verdicts": [{"id": 1, "verdict": "PASS", "reason": "a"}],
            }
        )
    )
    by_id, warnings = judge.load_verdicts(str(p))
    assert by_id[1]["verdict"] == "PASS"
    assert any("schema" in w for w in warnings)


def test_render_judging_md_mentions_files():
    md = judge.render_judging_md("Demo", "/x/Demo-judge-task.json", "/x/Demo-judge-verdicts.json")
    assert "Demo-judge-task.json" in md
    assert "Demo-judge-verdicts.json" in md
    assert "PASS" in md and "FAIL" in md
