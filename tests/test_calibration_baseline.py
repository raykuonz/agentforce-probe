"""Offline calibration regression — runs in CI with NO judge key and NO network.

The live calibration harness (eval/calibrate.py) calls a real LLM judge, so it
clean-skips in CI (no key). To still GATE on judge quality every commit, we
freeze a known-good set of judge axis scores (eval/calibration/judge-baseline.json,
produced by a Claude Code judge over eval/calibration/cases.jsonl) and assert two
things offline:

  1. Running those axis scores through the REAL axes_to_verdict() (hybrid veto +
     compensatory mean) reproduces the human PASS/FAIL labels exactly.
  2. Cohen's kappa between the derived verdicts and the human labels stays at or
     above a floor.

If someone changes the veto floor, the threshold, or the composite math in a way
that breaks alignment with the human-labelled calibration set, this test goes red
— without needing any API key or network call.
"""

import importlib.util
import json
import os

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CASES = os.path.join(_REPO_ROOT, "eval", "calibration", "cases.jsonl")
_BASELINE = os.path.join(_REPO_ROOT, "eval", "calibration", "judge-baseline.json")
_CALIBRATE = os.path.join(_REPO_ROOT, "eval", "calibrate.py")

from agentforce_probe.judge import JUDGE_AXES, axes_to_verdict  # noqa: E402

# load cohens_kappa from eval/calibrate.py (not an installed module)
_spec = importlib.util.spec_from_file_location("eval_calibrate", _CALIBRATE)
_cal = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cal)

KAPPA_FLOOR = 0.8  # chance-corrected agreement must stay strong


def _load_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _labels_by_id():
    return {c["id"]: c["label"] for c in _load_jsonl(_CASES)}


def _baseline():
    with open(_BASELINE, encoding="utf-8") as fh:
        return json.load(fh)


def test_baseline_covers_every_case():
    labels = _labels_by_id()
    base_ids = {v["id"] for v in _baseline()["verdicts"]}
    assert base_ids == set(labels), f"baseline/case id mismatch: {base_ids ^ set(labels)}"


def test_baseline_axis_scores_reproduce_human_labels():
    """The frozen judge scores, run through the hybrid verdict, must match humans."""
    labels = _labels_by_id()
    mismatches = []
    for v in _baseline()["verdicts"]:
        axes = {k: float(v[k]) for k in JUDGE_AXES if k in v}
        derived = "PASS" if axes_to_verdict(axes) else "FAIL"
        if derived != labels[v["id"]]:
            mismatches.append((v["id"], labels[v["id"]], derived))
    assert not mismatches, f"verdict != human label for: {mismatches}"


def test_calibration_kappa_above_floor():
    labels = _labels_by_id()
    tp = tn = fp = fn = 0
    for v in _baseline()["verdicts"]:
        axes = {k: float(v[k]) for k in JUDGE_AXES if k in v}
        derived = "PASS" if axes_to_verdict(axes) else "FAIL"
        human = labels[v["id"]]
        if human == "PASS" and derived == "PASS":
            tp += 1
        elif human == "FAIL" and derived == "FAIL":
            tn += 1
        elif human == "FAIL" and derived == "PASS":
            fp += 1
        else:
            fn += 1
    kappa = _cal.cohens_kappa(tp, tn, fp, fn)
    assert kappa >= KAPPA_FLOOR, f"calibration kappa {kappa:.3f} below floor {KAPPA_FLOOR}"


def test_calibration_set_is_reasonably_sized():
    # research floor for a smoke-level calibration set is ~30 cases
    assert len(_load_jsonl(_CASES)) >= 30
