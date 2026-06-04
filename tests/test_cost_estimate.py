"""Tests for estimate_calls helper and the pre-run cost estimate print."""

import pytest

from agentforce_probe import judge as judge_mod


# ── estimate_calls unit tests ─────────────────────────────────────────────────

def test_estimate_calls_anthropic():
    est = judge_mod.estimate_calls(50, "anthropic")
    assert est == {
        "n_cases": 50,
        "agent_api_calls": 50,
        "judge_llm_calls": 50,
        "live_judge": True,
    }


def test_estimate_calls_openai():
    est = judge_mod.estimate_calls(10, "openai")
    assert est["judge_llm_calls"] == 10
    assert est["live_judge"] is True
    assert est["agent_api_calls"] == 10


def test_estimate_calls_mock():
    est = judge_mod.estimate_calls(50, "mock")
    assert est["judge_llm_calls"] == 0
    assert est["live_judge"] is False
    assert est["n_cases"] == 50
    assert est["agent_api_calls"] == 50


def test_estimate_calls_handoff():
    est = judge_mod.estimate_calls(10, "handoff")
    assert est["judge_llm_calls"] == 0
    assert est["live_judge"] is False
    assert est["n_cases"] == 10


# ── integration: estimate line printed on mock run ────────────────────────────

def _wire_internal_mock(monkeypatch, scored):
    from agentforce_probe import agent_meta, scorer as scorer_mod, sf_internal, sfcli
    from agentforce_probe import config as config_mod

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


def test_estimate_line_printed_for_mock_run(monkeypatch, capsys, tmp_path):
    from agentforce_probe import cli

    _wire_internal_mock(monkeypatch, _SCORED_ONE_PASS)
    rc = cli.main(
        ["run", "--org", "o", "--spec", "s.yaml", "--judge", "mock",
         "--out", str(tmp_path / "ev.md"), "--allow-mock-evidence"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Estimated calls:" in out
    assert "0 judge LLM" in out
    assert "no paid judge cost" in out


def test_estimate_line_printed_for_live_judge_run(monkeypatch, capsys, tmp_path):
    from agentforce_probe import agent_meta, scorer as scorer_mod, sf_internal, sfcli
    from agentforce_probe import cli, config as config_mod

    spec = {"subjectName": "Help", "testCases": [
        {"utterance": "q1", "expectedOutcome": "o1"},
        {"utterance": "q2", "expectedOutcome": "o2"},
        {"utterance": "q3", "expectedOutcome": "o3"},
    ]}
    scored = [
        {
            "number": i,
            "utterance": f"q{i}",
            "topic": "-",
            "actions": "-",
            "output": "PASS",
            "response": "ok",
            "expectedTopic": None,
            "expectedActions": None,
            "actualTopic": None,
            "actualActions": None,
            "judge_reason": "looks good",
        }
        for i in range(1, 4)
    ]
    monkeypatch.setattr(scorer_mod, "load_spec", lambda p: spec)
    monkeypatch.setattr(
        agent_meta,
        "resolve_agent",
        lambda org, name: {"id": "0XxBOT", "type": "InternalCopilot", "is_internal": True},
    )
    monkeypatch.setattr(config_mod.Config, "eca_credentials", lambda self: ("ck", "cs"))
    monkeypatch.setattr(config_mod.Config, "judge_api_key", lambda self, p: "fake-key")
    monkeypatch.setattr(sfcli, "get_org_instance_url", lambda org: "https://x.my.salesforce.com")
    monkeypatch.setattr(sf_internal, "run_internal", lambda **k: scored)

    rc = cli.main(["run", "--org", "o", "--spec", "s.yaml", "--judge", "anthropic:claude-3-5-sonnet-latest"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Estimated calls:" in out
    assert "3 Agent API" in out
    assert "3 judge LLM" in out
    assert "live anthropic judge" in out
    assert "billed per call" in out
