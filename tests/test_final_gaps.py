"""Final gap-closing tests for small defensive branches."""

import pytest

from agentforce_probe import agent_api, doctor, scorer, sf_internal
from agentforce_probe import config as config_mod


# ── config: has() + env_file_path() ───────────────────────────────────────────
def test_config_has_and_env_file_path(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTPROBE_ENV_FILE", str(tmp_path / "x.env"))
    monkeypatch.setenv("AGENTPROBE_OPENAI_API_KEY", "sk-x")
    cfg = config_mod.Config()
    assert cfg.has("AGENTPROBE_OPENAI_API_KEY") is True
    assert cfg.has("NOT_SET_AT_ALL") is False
    assert cfg.env_file_path().endswith("x.env")


# ── scorer: SpecError branches ────────────────────────────────────────────────
def test_load_spec_not_mapping_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(scorer.SpecError, match="must be a YAML mapping"):
        scorer.load_spec(str(p))


def test_load_spec_no_testcases_raises(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("subjectName: X\n", encoding="utf-8")
    with pytest.raises(scorer.SpecError, match="no testCases"):
        scorer.load_spec(str(p))


def test_load_spec_case_missing_utterance_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("testCases:\n  - expectedOutcome: x\n", encoding="utf-8")
    with pytest.raises(scorer.SpecError, match="missing required 'utterance'"):
        scorer.load_spec(str(p))


def test_load_spec_missing_file_raises():
    with pytest.raises(scorer.SpecError, match="spec not found"):
        scorer.load_spec("/no/such/spec.yaml")


# ── doctor: instanceUrl None warn + ECA query exception warn ──────────────────
def test_doctor_instance_url_none_warns(monkeypatch):
    monkeypatch.setattr(doctor.sfcli, "sf_available", lambda: True)
    monkeypatch.setattr(doctor.sfcli, "get_org_instance_url", lambda org: None)

    class _Cfg:
        def eca_credentials(self):
            return None, None

        def judge_api_key(self, p):
            return None

        def env_file_exists(self):
            return False

        def env_file_path(self):
            return "/tmp/.env"

    checks, ok = doctor.run_doctor("myorg", _Cfg())
    org_check = next(c for c in checks if c["name"] == "org connection")
    assert org_check["status"] == "warn"


def test_doctor_eca_query_exception_warns(monkeypatch):
    monkeypatch.setattr(doctor.sfcli, "sf_available", lambda: True)
    monkeypatch.setattr(doctor.sfcli, "get_org_instance_url", lambda org: "https://x.my.salesforce.com")

    def boom(org, soql, **k):
        raise RuntimeError("no object access")

    monkeypatch.setattr(doctor.sfcli, "query_soql", boom)

    class _Cfg:
        def eca_credentials(self):
            return None, None

        def judge_api_key(self, p):
            return None

        def env_file_exists(self):
            return False

        def env_file_path(self):
            return "/tmp/.env"

    checks, ok = doctor.run_doctor("myorg", _Cfg())
    eca = next(c for c in checks if c["name"] == "External Client Apps")
    assert eca["status"] == "warn"
    assert "could not query" in eca["detail"]


# ── sf_internal: expectedActions filtering + diag callback ────────────────────
def test_score_session_actions_filtering_and_diag():
    spec = {"testCases": [{"utterance": "q", "expectedOutcome": "o", "expectedActions": ["DoX"]}]}
    raw = [{"number": 1, "utterance": "q", "response": "ok", "topic": None, "actions": ["DoX", "DoY"]}]
    diags = []

    def judge_fn(expected_outcome, actual_response, utterance=None):
        return True, "ok", None

    scored = sf_internal.score_session(spec=spec, raw_results=raw, judge_fn=judge_fn, diag=diags.append)
    assert scored[0]["actions"] == "PASS"  # {DoX} subset of {DoX,DoY}
    assert any("scored" in d for d in diags)


def test_score_session_actions_fail_when_missing():
    spec = {"testCases": [{"utterance": "q", "expectedOutcome": "o", "expectedActions": ["DoX", "DoZ"]}]}
    raw = [{"number": 1, "utterance": "q", "response": "ok", "topic": None, "actions": ["DoX"]}]

    def judge_fn(eo, ar, utterance=None):
        return True, "ok", None

    scored = sf_internal.score_session(spec=spec, raw_results=raw, judge_fn=judge_fn)
    assert scored[0]["actions"] == "FAIL"  # DoZ missing


# ── agent_api: close with no session is a no-op; planId topic branch ──────────
def test_session_close_no_session_is_noop():
    s = agent_api.AgentApiSession("https://api", "t", "0Xx")
    s.close()  # session_id is None -> returns immediately, no error
    assert s.session_id is None


def test_parse_agent_response_planid_topic():
    obj = {"messages": [{"message": "hi", "planId": "p1", "topic": "Billing"}]}
    out = agent_api.parse_agent_response(obj)
    assert out["topic"] == "Billing"
