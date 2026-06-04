"""Directly exercise the two leaf raises that the normal dispatch guards
before reaching: _run_external dry-run and the External keyword fallback."""

import types

import pytest

from agentforce_probe import cli, judge


def test_run_external_helper_rejects_dry_run():
    """_run_external raises on --dry-run (cli.py line ~380). The normal run()
    path forces type via meta first, so we call the helper directly."""
    args = types.SimpleNamespace(dry_run=True, spec="s.yaml", org="o")
    with pytest.raises(RuntimeError, match="dry-run cannot exercise"):
        cli._run_external(args, {"testCases": [{"utterance": "q"}]}, "Agent")


def test_judge_extract_verdict_both_keywords_fails():
    """Both PASS and FAIL present -> not a clean keyword match -> FAIL (116-117)."""
    ok, reason, axes = judge._extract_verdict("It could PASS or FAIL depending.")
    assert ok is False
