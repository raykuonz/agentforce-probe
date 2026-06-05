"""Maintainer-only judge calibration runner.

Reads eval/calibration/cases.jsonl, runs each triple through the live judge,
and reports agreement with the hand-labelled expected verdicts.

Key-gated: if no live judge API key is configured, prints a skip message and
exits 0. This means it runs cleanly in CI without any keys set.

Usage:
    uv run python eval/calibrate.py
    uv run python eval/calibrate.py --cases path/to/cases.jsonl --threshold 0.8
"""

import argparse
import json
import os
import sys

_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src = os.path.join(_repo_root, "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from agentforce_probe.config import JUDGE_KEY_ENV, Config  # noqa: E402
from agentforce_probe.judge import judge_case  # noqa: E402

_DEFAULT_CASES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration", "cases.jsonl")
_DEFAULT_THRESHOLD = 0.8


def _resolve_provider_and_key():
    """Return (provider, api_key) for the first available live judge, or (None, None)."""
    cfg = Config()
    for provider in ("anthropic", "openai"):
        key = cfg.judge_api_key(provider)
        if key:
            return provider, key
    return None, None


def _load_cases(path):
    cases = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def cohens_kappa(tp, tn, fp, fn):
    """Chance-corrected agreement (Cohen's kappa) for the 2x2 PASS/FAIL confusion.

    Raw % agreement is misleading when the label distribution is skewed (Thakur
    et al., "Judging the Judges", 2024 — a judge can score high raw agreement yet
    have poor kappa). Kappa corrects for agreement expected by chance.

    Returns a float in [-1, 1]; 1.0 = perfect, 0.0 = chance-level, <0 = worse
    than chance. Returns 1.0 for the degenerate all-agree single-class case and
    0.0 when the total is zero.
    """
    n = tp + tn + fp + fn
    if n == 0:
        return 0.0
    po = (tp + tn) / n  # observed agreement
    # marginals: judge says PASS = tp+fp, human says PASS = tp+fn, etc.
    p_pass = ((tp + fp) / n) * ((tp + fn) / n)
    p_fail = ((tn + fn) / n) * ((tn + fp) / n)
    pe = p_pass + p_fail  # agreement expected by chance
    if pe >= 1.0:
        # both raters always pick the same single class -> agreement is trivially
        # perfect; kappa is undefined (0/0) so report 1.0 when they fully agree.
        return 1.0 if (fp == 0 and fn == 0) else 0.0
    return (po - pe) / (1.0 - pe)


def run(cases_path=None, threshold=_DEFAULT_THRESHOLD, _judge_fn=None):
    """Core calibration runner. Returns exit code (int).

    _judge_fn: optional override — (provider, model, api_key, utterance, expected, response) -> (bool, str, dict|None).
    Returns 0 on success or clean skip, 1 when agreement is below threshold.
    """
    if cases_path is None:
        cases_path = _DEFAULT_CASES

    provider, api_key = _resolve_provider_and_key()

    if provider is None:
        env_vars = " or ".join(sorted(JUDGE_KEY_ENV.values()))
        print(f"no judge API key found (set {env_vars}); skipping calibration")
        return 0

    cases = _load_cases(cases_path)
    judge_fn = _judge_fn or judge_case

    tp = tn = fp = fn = correct = 0

    print(f"provider: {provider}  cases: {len(cases)}")
    print()

    for case in cases:
        cid = case["id"]
        utterance = case["utterance"]
        expected = case["expectedOutcome"]
        response = case["response"]
        human_label = case["label"]

        judge_passed, reason, _axes = judge_fn(provider, "", api_key, utterance, expected, response)
        judge_label = "PASS" if judge_passed else "FAIL"
        agree = judge_label == human_label

        if agree:
            correct += 1

        if human_label == "PASS" and judge_label == "PASS":
            tp += 1
        elif human_label == "FAIL" and judge_label == "FAIL":
            tn += 1
        elif human_label == "FAIL" and judge_label == "PASS":
            fp += 1
        else:
            fn += 1

        mark = "✓" if agree else "✗"
        print(f"  [{mark}] {str(cid):<20}  human={human_label}  judge={judge_label}  {reason[:80]}")

    total = len(cases)
    agreement = correct / total if total > 0 else 0.0
    kappa = cohens_kappa(tp, tn, fp, fn)

    print()
    print(f"agreement: {correct}/{total} = {agreement:.1%}")
    print(f"confusion:  TP={tp}  TN={tn}  FP={fp}  FN={fn}")
    print(f"cohen's kappa: {kappa:.3f}  (chance-corrected; <0 worse than chance, 1.0 perfect)")
    print()

    if agreement < threshold:
        print(f"FAIL: agreement {agreement:.1%} is below threshold {threshold:.0%}")
        return 1

    print(f"OK: agreement {agreement:.1%} meets threshold {threshold:.0%}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Judge calibration harness (maintainer-only)")
    parser.add_argument("--cases", default=None, help="Path to cases.jsonl (default: eval/calibration/cases.jsonl)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=_DEFAULT_THRESHOLD,
        help=f"Minimum agreement ratio to exit 0 (default {_DEFAULT_THRESHOLD})",
    )
    args = parser.parse_args()
    sys.exit(run(cases_path=args.cases, threshold=args.threshold))


if __name__ == "__main__":
    main()
