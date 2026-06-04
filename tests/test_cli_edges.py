"""Remaining cli + agent_api branch coverage."""

import json

import pytest

from agentforce_probe import agent_api, cli


# ── cli: internal path with API-key judge (mock provider, no real key) ────────
def test_run_internal_mock_judge_scores_live(monkeypatch, capsys, tmp_path):
    from agentforce_probe import agent_meta, scorer, sf_internal, sfcli
    from agentforce_probe import config as config_mod

    spec = {"subjectName": "Help", "testCases": [{"utterance": "reset pw", "expectedOutcome": "guides"}]}
    monkeypatch.setattr(scorer, "load_spec", lambda p: spec)
    monkeypatch.setattr(
        agent_meta, "resolve_agent", lambda org, name: {"id": "0XxBOT", "type": "InternalCopilot", "is_internal": True}
    )
    monkeypatch.setattr(config_mod.Config, "eca_credentials", lambda self: ("ck", "cs"))
    monkeypatch.setattr(sfcli, "get_org_instance_url", lambda org: "https://x.my.salesforce.com")
    # run_internal returns scored cases directly (we mock it; the mock-judge
    # branch in cli still resolves provider=mock without needing an API key).
    scored = [
        {
            "number": 1,
            "utterance": "reset pw",
            "topic": "-",
            "actions": "-",
            "output": "PASS",
            "response": "do x",
            "expectedTopic": None,
            "expectedActions": None,
            "actualTopic": None,
            "actualActions": None,
            "judge_reason": "mock",
        }
    ]
    monkeypatch.setattr(sf_internal, "run_internal", lambda **k: scored)
    out_path = tmp_path / "ev.md"
    rc = cli.main(
        ["run", "--org", "o", "--spec", "s.yaml", "--judge", "mock", "--out", str(out_path), "--allow-mock-evidence"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Score: 1/1 = 100%" in out
    assert "MOCK JUDGE" in out
    assert out_path.exists()


def test_run_internal_api_key_judge_needs_key(monkeypatch, capsys):
    from agentforce_probe import agent_meta, scorer, sfcli
    from agentforce_probe import config as config_mod

    spec = {"subjectName": "Help", "testCases": [{"utterance": "q", "expectedOutcome": "o"}]}
    monkeypatch.setattr(scorer, "load_spec", lambda p: spec)
    monkeypatch.setattr(
        agent_meta, "resolve_agent", lambda org, name: {"id": "0XxBOT", "type": "InternalCopilot", "is_internal": True}
    )
    monkeypatch.setattr(config_mod.Config, "eca_credentials", lambda self: ("ck", "cs"))
    monkeypatch.setattr(config_mod.Config, "judge_api_key", lambda self, provider: None)
    monkeypatch.setattr(sfcli, "get_org_instance_url", lambda org: "https://x.my.salesforce.com")
    rc = cli.main(["run", "--org", "o", "--spec", "s.yaml", "--judge", "openai:gpt-4o"])
    assert rc == 4  # run failed: no API key for judge provider
    assert "no API key" in capsys.readouterr().err


def test_run_internal_no_eca_creds_fails(monkeypatch, capsys):
    from agentforce_probe import agent_meta, scorer
    from agentforce_probe import config as config_mod

    spec = {"subjectName": "Help", "testCases": [{"utterance": "q", "expectedOutcome": "o"}]}
    monkeypatch.setattr(scorer, "load_spec", lambda p: spec)
    monkeypatch.setattr(
        agent_meta, "resolve_agent", lambda org, name: {"id": "0XxBOT", "type": "InternalCopilot", "is_internal": True}
    )
    monkeypatch.setattr(config_mod.Config, "eca_credentials", lambda self: (None, None))
    rc = cli.main(["run", "--org", "o", "--spec", "s.yaml"])
    assert rc == 4
    assert "ECA consumer key" in capsys.readouterr().err


def test_run_from_verdicts_handoff_error(monkeypatch, capsys, tmp_path):
    from agentforce_probe import scorer

    spec = {"subjectName": "Help", "testCases": [{"utterance": "q", "expectedOutcome": "o"}]}
    monkeypatch.setattr(scorer, "load_spec", lambda p: spec)
    # point --from-verdicts at a missing file and no task package -> HandoffError -> rc 2
    rc = cli.main(["run", "--org", "o", "--spec", "s.yaml", "--from-verdicts", str(tmp_path / "missing.json")])
    assert rc == 2
    assert "handoff error" in capsys.readouterr().err


# ── agent_api: send returns non-JSON body ─────────────────────────────────────
def test_session_send_non_json_raises(monkeypatch):
    seq = iter([(200, json.dumps({"sessionId": "s1"})), (200, "<<<not json>>>")])
    monkeypatch.setattr(agent_api, "_http", lambda *a, **k: next(seq))
    s = agent_api.AgentApiSession("https://api", "hdr." + "a" * 900 + ".sig", "0Xx")
    s.start()
    with pytest.raises(agent_api.AgentApiError, match="non-JSON"):
        s.send("hi")


def test_session_start_non_json_raises(monkeypatch):
    monkeypatch.setattr(agent_api, "_http", lambda *a, **k: (200, "not json"))
    s = agent_api.AgentApiSession("https://api", "hdr." + "a" * 900 + ".sig", "0Xx")
    with pytest.raises(agent_api.AgentApiError, match="non-JSON"):
        s.start()
