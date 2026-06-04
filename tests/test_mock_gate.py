"""Anti-mock / anti-ungrounded gate tests.

Covers:
- is_ungrounded_provider helper
- render_evidence ungrounded banner + judge label stamp
- cmd_run score line carries ⚠️ suffix for mock judge
- --out + mock + no --allow-mock-evidence does NOT create the file
"""

from agentforce_probe import evidence, scorer
from agentforce_probe import judge as judge_mod

# ── is_ungrounded_provider ─────────────────────────────────────────────────────


def test_mock_is_ungrounded():
    assert judge_mod.is_ungrounded_provider("mock") is True


def test_handoff_is_not_ungrounded():
    assert judge_mod.is_ungrounded_provider("handoff") is False


def test_openai_is_not_ungrounded():
    assert judge_mod.is_ungrounded_provider("openai") is False


def test_anthropic_is_not_ungrounded():
    assert judge_mod.is_ungrounded_provider("anthropic") is False


# ── render_evidence: ungrounded banner and judge label stamp ───────────────────


def _make_results():
    return [
        scorer.score_case(
            {"utterance": "Hello?", "expectedOutcome": "Greets user"},
            1,
            output_pass=True,
            response="Hi there!",
            judge_reason="mock judge: response present",
        )
    ]


def test_render_evidence_ungrounded_has_banner():
    md = evidence.render_evidence(
        agent_name="TestAgent",
        org_alias="dev",
        agent_type="InternalCopilot",
        path_label="Agent API",
        results=_make_results(),
        judge_label="mock",
        ungrounded=True,
    )
    assert "MOCK JUDGE — NOT A REAL PASS RATE" in md
    assert "UNGROUNDED — not a real pass rate" in md


def test_render_evidence_ungrounded_false_has_no_banner():
    md = evidence.render_evidence(
        agent_name="TestAgent",
        org_alias="dev",
        agent_type="InternalCopilot",
        path_label="Agent API",
        results=_make_results(),
        judge_label="openai:gpt-4o",
        ungrounded=False,
    )
    assert "MOCK JUDGE" not in md
    assert "UNGROUNDED" not in md


def test_render_evidence_default_ungrounded_false():
    # ungrounded defaults to False — no banner without the flag
    md = evidence.render_evidence(
        agent_name="TestAgent",
        org_alias="dev",
        agent_type="InternalCopilot",
        path_label="Agent API",
        results=_make_results(),
        judge_label="mock",
    )
    assert "MOCK JUDGE" not in md
    assert "UNGROUNDED" not in md


# ── cmd_run: score line carries ⚠️ suffix for mock judge ──────────────────────


def _wire_internal_mock(monkeypatch, scored):
    """Patch all I/O dependencies for the internal mock path."""
    from agentforce_probe import agent_meta, sf_internal, sfcli
    from agentforce_probe import config as config_mod
    from agentforce_probe import scorer as scorer_mod

    spec = {"subjectName": "Help", "testCases": [{"utterance": "q", "expectedOutcome": "o"}]}
    monkeypatch.setattr(scorer_mod, "load_spec", lambda p: spec)
    monkeypatch.setattr(
        agent_meta,
        "resolve_agent",
        lambda org, name: {"id": "0XxBOT", "type": "InternalCopilot", "is_internal": True},
    )
    monkeypatch.setattr(config_mod.Config, "eca_credentials", lambda self: ("ck", "cs"))
    monkeypatch.setattr(sfcli, "get_org_instance_url", lambda org: "https://x.my.salesforce.com")
    monkeypatch.setattr(sf_internal, "run_internal", lambda **k: scored)


_SCORED_ONE_PASS = [
    {
        "number": 1,
        "utterance": "q",
        "topic": "-",
        "actions": "-",
        "output": "PASS",
        "response": "sure",
        "expectedTopic": None,
        "expectedActions": None,
        "actualTopic": None,
        "actualActions": None,
        "judge_reason": "mock judge: response present",
    }
]


def test_score_line_carries_mock_warning(monkeypatch, capsys, tmp_path):
    from agentforce_probe import cli

    _wire_internal_mock(monkeypatch, _SCORED_ONE_PASS)
    out_path = tmp_path / "ev.md"
    rc = cli.main(
        ["run", "--org", "o", "--spec", "s.yaml", "--judge", "mock", "--out", str(out_path), "--allow-mock-evidence"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "⚠️ MOCK JUDGE — NOT A REAL PASS RATE" in out


def test_out_plus_mock_no_flag_refuses_file(monkeypatch, capsys, tmp_path):
    """--out + mock without --allow-mock-evidence must NOT create the file."""
    from agentforce_probe import cli

    _wire_internal_mock(monkeypatch, _SCORED_ONE_PASS)
    out_path = tmp_path / "ev.md"
    rc = cli.main(["run", "--org", "o", "--spec", "s.yaml", "--judge", "mock", "--out", str(out_path)])
    err = capsys.readouterr().err
    assert rc == 0
    assert not out_path.exists(), "evidence file must NOT be written for mock judge without --allow-mock-evidence"
    assert "Refusing" in err
    assert "--allow-mock-evidence" in err


def test_out_plus_mock_with_flag_writes_file(monkeypatch, capsys, tmp_path):
    """--out + mock + --allow-mock-evidence writes the file with the banner."""
    from agentforce_probe import cli

    _wire_internal_mock(monkeypatch, _SCORED_ONE_PASS)
    out_path = tmp_path / "ev.md"
    rc = cli.main(
        ["run", "--org", "o", "--spec", "s.yaml", "--judge", "mock", "--out", str(out_path), "--allow-mock-evidence"]
    )
    assert rc == 0
    assert out_path.exists()
    content = out_path.read_text()
    assert "MOCK JUDGE — NOT A REAL PASS RATE" in content
    assert "UNGROUNDED — not a real pass rate" in content


def test_mock_no_out_writes_autonamed_file(monkeypatch, capsys, tmp_path):
    """Without --out, even a mock run writes the auto-named evidence file."""
    import os

    from agentforce_probe import cli

    _wire_internal_mock(monkeypatch, _SCORED_ONE_PASS)
    orig_dir = os.getcwd()
    os.chdir(tmp_path)
    try:
        rc = cli.main(["run", "--org", "o", "--spec", "s.yaml", "--judge", "mock"])
        assert rc == 0
        auto_file = tmp_path / "Help-evidence.md"
        assert auto_file.exists(), "auto-named evidence file should be written when --out is not given"
        content = auto_file.read_text()
        assert "MOCK JUDGE — NOT A REAL PASS RATE" in content
    finally:
        os.chdir(orig_dir)
