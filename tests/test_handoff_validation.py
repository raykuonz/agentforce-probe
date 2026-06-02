"""judge handoff: load_task_package + load_verdicts validation error paths."""

import json

import pytest

from agentforce_probe import judge


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


# ── load_task_package ─────────────────────────────────────────────────────────
def test_load_task_missing_file_raises(tmp_path):
    with pytest.raises(judge.HandoffError, match="not found"):
        judge.load_task_package(str(tmp_path / "nope.json"))


def test_load_task_not_object_raises(tmp_path):
    p = _write(tmp_path, "t.json", ["not", "an", "object"])
    with pytest.raises(judge.HandoffError, match="must be a JSON object"):
        judge.load_task_package(p)


def test_load_task_no_cases_raises(tmp_path):
    p = _write(tmp_path, "t.json", {"schema": judge.TASK_SCHEMA, "cases": []})
    with pytest.raises(judge.HandoffError, match="no cases"):
        judge.load_task_package(p)


def test_load_task_ok(tmp_path):
    p = _write(tmp_path, "t.json", {"schema": judge.TASK_SCHEMA, "cases": [{"id": 1}]})
    assert judge.load_task_package(p)["cases"] == [{"id": 1}]


# ── load_verdicts ─────────────────────────────────────────────────────────────
def test_load_verdicts_missing_file(tmp_path):
    with pytest.raises(judge.HandoffError, match="not found"):
        judge.load_verdicts(str(tmp_path / "v.json"))


def test_load_verdicts_not_object(tmp_path):
    p = _write(tmp_path, "v.json", [1, 2])
    with pytest.raises(judge.HandoffError, match="must be a JSON object"):
        judge.load_verdicts(p)


def test_load_verdicts_no_array(tmp_path):
    p = _write(tmp_path, "v.json", {"schema": judge.VERDICTS_SCHEMA})
    with pytest.raises(judge.HandoffError, match="missing a verdicts"):
        judge.load_verdicts(p)


def test_load_verdicts_entry_not_object(tmp_path):
    p = _write(tmp_path, "v.json", {"schema": judge.VERDICTS_SCHEMA, "verdicts": ["x"]})
    with pytest.raises(judge.HandoffError, match="not an object"):
        judge.load_verdicts(p)


def test_load_verdicts_missing_id(tmp_path):
    p = _write(tmp_path, "v.json", {"schema": judge.VERDICTS_SCHEMA, "verdicts": [{"verdict": "PASS"}]})
    with pytest.raises(judge.HandoffError, match="missing 'id'"):
        judge.load_verdicts(p)


def test_load_verdicts_non_integer_id(tmp_path):
    p = _write(tmp_path, "v.json", {"schema": judge.VERDICTS_SCHEMA, "verdicts": [{"id": "abc", "verdict": "PASS"}]})
    with pytest.raises(judge.HandoffError, match="non-integer id"):
        judge.load_verdicts(p)


def test_load_verdicts_illegal_verdict(tmp_path):
    p = _write(tmp_path, "v.json", {"schema": judge.VERDICTS_SCHEMA, "verdicts": [{"id": 1, "verdict": "MAYBE"}]})
    with pytest.raises(judge.HandoffError, match="illegal verdict"):
        judge.load_verdicts(p)


def test_load_verdicts_duplicate_id(tmp_path):
    p = _write(
        tmp_path,
        "v.json",
        {"schema": judge.VERDICTS_SCHEMA, "verdicts": [{"id": 1, "verdict": "PASS"}, {"id": 1, "verdict": "FAIL"}]},
    )
    with pytest.raises(judge.HandoffError, match="duplicate verdict"):
        judge.load_verdicts(p)


def test_load_verdicts_schema_warning(tmp_path):
    p = _write(tmp_path, "v.json", {"schema": "wrong@9", "verdicts": [{"id": 1, "verdict": "PASS", "reason": "ok"}]})
    by_id, warnings = judge.load_verdicts(p)
    assert by_id[1]["verdict"] == "PASS"
    assert any("schema" in w for w in warnings)


def test_load_verdicts_ok(tmp_path):
    p = _write(
        tmp_path,
        "v.json",
        {"schema": judge.VERDICTS_SCHEMA, "verdicts": [{"id": 2, "verdict": "fail", "reason": "leak"}]},
    )
    by_id, warnings = judge.load_verdicts(p)
    assert by_id[2]["verdict"] == "FAIL"  # normalized to upper
    assert warnings == []


# ── path helpers + render_judging_md ──────────────────────────────────────────
def test_path_helpers_use_cwd_when_no_out(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert judge.task_package_path(None, "Bot").endswith("Bot-judge-task.json")
    assert judge.judging_md_path(None, "Bot").endswith("Bot-JUDGING.md")
    assert judge.verdicts_path(None, "Bot").endswith("Bot-judge-verdicts.json")


def test_render_judging_md_contains_protocol():
    md = judge.render_judging_md("Bot", "/x/Bot-judge-task.json", "/x/Bot-judge-verdicts.json")
    assert "Judging `Bot`" in md
    assert judge.TASK_SCHEMA in md
    assert judge.VERDICTS_SCHEMA in md
    assert "Bot-judge-task.json" in md
