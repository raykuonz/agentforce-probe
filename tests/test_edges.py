"""Cover the remaining edge lines: __main__ entrypoint, config parsing, the
judge _post_json network layer, sf_internal real-mint + run_internal, and a few
agent_api/cli branches. Everything is mocked — no network, org, or secret.
"""

import runpy
import sys
import urllib.error

import pytest

from agentforce_probe import agent_api, judge, sf_internal
from agentforce_probe import config as config_mod


# ── __main__ entrypoint ───────────────────────────────────────────────────────
def test_main_module_runs_help(monkeypatch):
    # `python -m agentforce_probe` with --help exits 0 via argparse SystemExit.
    monkeypatch.setattr(sys, "argv", ["agentforce_probe", "--help"])
    with pytest.raises(SystemExit) as ei:
        runpy.run_module("agentforce_probe", run_name="__main__")
    assert ei.value.code == 0


# ── config: .env parsing + priority ───────────────────────────────────────────
def test_config_env_file_parsing(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "export AGENTPROBE_SF_CONSUMER_KEY='quoted-key'\n"
        'AGENTPROBE_SF_CONSUMER_SECRET="dq-secret"\n'
        "BLANKLINE_BELOW=\n"
        "\n"
        "no_equals_line\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPROBE_ENV_FILE", str(env))
    # ensure no env-var override of the keys
    monkeypatch.delenv("AGENTPROBE_SF_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("AGENTPROBE_SF_CONSUMER_SECRET", raising=False)
    cfg = config_mod.Config()
    ck, cs = cfg.eca_credentials()
    assert ck == "quoted-key"  # single quotes stripped
    assert cs == "dq-secret"  # double quotes stripped
    assert cfg.env_file_exists() is True


def test_config_env_var_wins_over_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("AGENTPROBE_SF_CONSUMER_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("AGENTPROBE_ENV_FILE", str(env))
    monkeypatch.setenv("AGENTPROBE_SF_CONSUMER_KEY", "from-env")
    cfg = config_mod.Config()
    assert cfg.get("AGENTPROBE_SF_CONSUMER_KEY") == "from-env"


def test_config_judge_api_key_unknown_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTPROBE_ENV_FILE", str(tmp_path / "nope.env"))
    cfg = config_mod.Config()
    assert cfg.judge_api_key("gemini") is None


# ── judge _post_json network layer ────────────────────────────────────────────
class _Resp:
    def __init__(self, body):
        self._b = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


def test_post_json_success(monkeypatch):
    monkeypatch.setattr(judge.urllib.request, "urlopen", lambda *a, **k: _Resp('{"ok": true}'))
    out = judge._post_json("https://x", {}, {"p": 1})
    assert out == {"ok": True}


def test_post_json_http_error_raises(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.HTTPError("https://x", 401, "unauth", None, None)

    monkeypatch.setattr(judge.urllib.request, "urlopen", boom)
    with pytest.raises(judge.JudgeError, match="judge HTTP 401"):
        judge._post_json("https://x", {}, {})


def test_post_json_retries_5xx(monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 2:
            raise urllib.error.HTTPError("https://x", 503, "busy", None, None)
        return _Resp('{"ok": 1}')

    monkeypatch.setattr(judge.time, "sleep", lambda *_: None)
    monkeypatch.setattr(judge.urllib.request, "urlopen", flaky)
    out = judge._post_json("https://x", {}, {})
    assert out == {"ok": 1} and calls["n"] == 2


def test_post_json_network_error_exhausts(monkeypatch):
    monkeypatch.setattr(judge.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        judge.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("dns"))
    )
    with pytest.raises(judge.JudgeError, match="network error"):
        judge._post_json("https://x", {}, {}, retries=2)


# ── sf_internal: real-mint path + run_internal end-to-end (mocked agent_api) ──
def test_run_session_real_mint_path(monkeypatch):
    """No session_factory -> exercises the mint_token + AgentApiSession branch."""
    monkeypatch.setattr(
        sf_internal.agent_api,
        "mint_token",
        lambda url, ck, cs: {"token": "t", "api_instance_url": "https://api", "shape": {"segments": 3, "len": 1700}},
    )

    class _S:
        def __init__(self, *a):
            pass

        def start(self):
            return "sid"

        def send(self, text):
            return {"response": "resp-" + text, "topic": None, "invokedActions": []}

        def close(self):
            pass

    monkeypatch.setattr(sf_internal.agent_api, "AgentApiSession", _S)
    spec = {"testCases": [{"utterance": "hi", "expectedOutcome": "o"}]}
    diags = []
    raw = sf_internal.run_session(
        spec=spec,
        instance_url="https://x",
        bot_definition_id="0Xx",
        consumer_key="ck",
        consumer_secret="cs",
        diag=diags.append,
    )
    assert raw[0]["response"] == "resp-hi"
    assert any("minted token" in d for d in diags)


def test_run_internal_with_mock_judge(monkeypatch):
    monkeypatch.setattr(
        sf_internal.agent_api,
        "mint_token",
        lambda url, ck, cs: {"token": "t", "api_instance_url": "https://api", "shape": {"segments": 3, "len": 1700}},
    )

    class _S:
        def __init__(self, *a):
            pass

        def start(self):
            return "sid"

        def send(self, text):
            return {"response": "non-empty", "topic": None, "invokedActions": []}

        def close(self):
            pass

    monkeypatch.setattr(sf_internal.agent_api, "AgentApiSession", _S)
    spec = {"testCases": [{"utterance": "hi", "expectedOutcome": "o"}]}
    scored = sf_internal.run_internal(
        spec=spec,
        instance_url="https://x",
        bot_definition_id="0Xx",
        consumer_key="ck",
        consumer_secret="cs",
        judge_provider="mock",
        judge_model="",
        judge_api_key=None,
    )
    assert scored[0]["output"] == "PASS"


# ── agent_api close swallows errors ───────────────────────────────────────────
def test_session_close_swallows_http_error(monkeypatch):
    s = agent_api.AgentApiSession("https://api", "hdr." + "a" * 900 + ".sig", "0Xx")
    s.session_id = "sid"
    monkeypatch.setattr(agent_api, "_http", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    s.close()  # must not raise
    assert s.session_id is None
