"""Tests for eval/calibrate.py — no live LLM calls, no network."""

import importlib.util
import json
import os

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CALIBRATE_PATH = os.path.join(_REPO_ROOT, "eval", "calibrate.py")
_CASES_PATH = os.path.join(_REPO_ROOT, "eval", "calibration", "cases.jsonl")

# Load eval/calibrate.py by file path — it lives outside src/ and is not installed.
_spec = importlib.util.spec_from_file_location("eval_calibrate", _CALIBRATE_PATH)
_cal = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cal)

_REQUIRED_FIELDS = {"id", "utterance", "expectedOutcome", "response", "label", "rationale"}

_FIXTURE_CASES = [
    {"id": "t1", "utterance": "u1", "expectedOutcome": "e1", "response": "r1", "label": "PASS", "rationale": ""},
    {"id": "t2", "utterance": "u2", "expectedOutcome": "e2", "response": "r2", "label": "PASS", "rationale": ""},
    {"id": "t3", "utterance": "u3", "expectedOutcome": "e3", "response": "r3", "label": "FAIL", "rationale": ""},
    {"id": "t4", "utterance": "u4", "expectedOutcome": "e4", "response": "r4", "label": "FAIL", "rationale": ""},
]


def _write_cases(cases, path):
    with open(path, "w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c) + "\n")


# ── no-key clean skip ─────────────────────────────────────────────────────────

def test_no_key_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(_cal, "_resolve_provider_and_key", lambda: (None, None))
    code = _cal.run()
    assert code == 0
    out = capsys.readouterr().out
    assert "skipping calibration" in out
    assert "AGENTPROBE" in out


# ── scoring math via fake judge ───────────────────────────────────────────────

def _fake_judge_agree(provider, model, api_key, utterance, expected, response):
    """PASS for r1/r2, FAIL for r3/r4 — agrees with fixture labels exactly."""
    return response in ("r1", "r2"), "fake", None


def _fake_judge_always_pass(provider, model, api_key, utterance, expected, response):
    """Always PASS — disagrees with the two FAIL-labelled fixture cases."""
    return True, "fake always pass", None


def test_scoring_full_agreement(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "cases.jsonl")
    _write_cases(_FIXTURE_CASES, path)
    monkeypatch.setattr(_cal, "_resolve_provider_and_key", lambda: ("openai", "fake-key"))
    code = _cal.run(cases_path=path, threshold=0.8, _judge_fn=_fake_judge_agree)
    assert code == 0
    out = capsys.readouterr().out
    assert "4/4" in out


def test_scoring_below_threshold_exits_nonzero(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "cases.jsonl")
    _write_cases(_FIXTURE_CASES, path)
    monkeypatch.setattr(_cal, "_resolve_provider_and_key", lambda: ("openai", "fake-key"))
    # t3 and t4 are FAIL-labelled but judge returns PASS → 2/4 = 50 % < 80 %
    code = _cal.run(cases_path=path, threshold=0.8, _judge_fn=_fake_judge_always_pass)
    assert code != 0
    out = capsys.readouterr().out
    assert "below threshold" in out


# ── cases.jsonl schema validity ───────────────────────────────────────────────

def test_cases_jsonl_parses():
    cases = []
    with open(_CASES_PATH, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as exc:
                pytest.fail(f"cases.jsonl line {i} is invalid JSON: {exc}")
    assert len(cases) >= 10, f"expected at least 10 cases, got {len(cases)}"


def test_cases_jsonl_required_fields():
    with open(_CASES_PATH, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            missing = _REQUIRED_FIELDS - set(obj.keys())
            assert not missing, f"cases.jsonl line {i} missing fields: {missing}"


def test_cases_jsonl_valid_labels():
    with open(_CASES_PATH, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            assert obj["label"] in ("PASS", "FAIL"), f"cases.jsonl line {i} has invalid label: {obj['label']!r}"
