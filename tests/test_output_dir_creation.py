"""Regression: writers must create missing parent dirs before writing.

Bug (2026-06): running `run --out docs/evidence/...` against a real org
replayed all N Agent API sessions (spending Einstein credits) and only then
crashed with FileNotFoundError because `docs/evidence/` did not exist. The
write helpers now `os.makedirs(parent, exist_ok=True)` so a nested --out path
works on the first run, after the costly replay has already happened.
"""

import json
import os

from agentforce_probe import evidence, judge


def test_write_evidence_creates_missing_parent(tmp_path):
    nested = tmp_path / "docs" / "evidence" / "out.md"
    assert not nested.parent.exists()
    evidence.write_evidence(str(nested), "# hello\n")
    assert nested.exists()
    assert nested.read_text(encoding="utf-8") == "# hello\n"


def test_write_task_package_creates_missing_parent(tmp_path):
    nested = tmp_path / "a" / "b" / "c" / "Agent-judge-task.json"
    assert not nested.parent.exists()
    judge.write_task_package(str(nested), {"schema": "x", "cases": []})
    assert nested.exists()
    data = json.loads(nested.read_text(encoding="utf-8"))
    assert data["schema"] == "x"


def test_write_judging_md_creates_missing_parent(tmp_path):
    nested = tmp_path / "deep" / "dir" / "Agent-JUDGING.md"
    assert not nested.parent.exists()
    judge.write_judging_md(str(nested), "instructions\n")
    assert nested.exists()
    assert nested.read_text(encoding="utf-8") == "instructions\n"


def test_writers_still_work_for_bare_filename(tmp_path, monkeypatch):
    """A bare filename (no dir component) must not blow up on makedirs."""
    monkeypatch.chdir(tmp_path)
    evidence.write_evidence("bare.md", "x")
    assert (tmp_path / "bare.md").exists()
