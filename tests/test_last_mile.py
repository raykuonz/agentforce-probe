"""Last-mile coverage: retry-sleep ladders, warning paths, fire-and-forget."""

import json
import urllib.error

import pytest

from agentforce_probe import agent_api, cli, judge, sf_external


# ── cli: schema-mismatch WARN + extra-id WARN (lines 301, 303, 316) ───────────
def test_from_verdicts_emits_warnings(monkeypatch, capsys, tmp_path):
    from agentforce_probe import judge as judge_mod
    from agentforce_probe import scorer

    spec = {"subjectName": "Help", "testCases": [{"utterance": "q", "expectedOutcome": "o"}]}
    monkeypatch.setattr(scorer, "load_spec", lambda p: spec)
    raw = [{"number": 1, "utterance": "q", "response": "r", "topic": None, "actions": []}]
    task = judge_mod.build_task_package("Help", "o", spec, raw)
    task["schema"] = "wrong-task-schema@9"  # triggers task-schema WARN (line 301)
    task_path = tmp_path / "Help-judge-task.json"
    judge_mod.write_task_package(str(task_path), task)
    # verdicts: wrong verdicts-schema (load_verdicts warning -> line 303) + extra id 99 (line 316)
    verdicts = {
        "schema": "wrong-verdicts@9",
        "agent": "Help",
        "verdicts": [{"id": 1, "verdict": "PASS", "reason": "ok"}, {"id": 99, "verdict": "PASS", "reason": "stray"}],
    }
    vpath = tmp_path / "Help-judge-verdicts.json"
    vpath.write_text(json.dumps(verdicts), encoding="utf-8")
    out_path = tmp_path / "ev.md"
    rc = cli.main(
        [
            "run",
            "--org",
            "o",
            "--spec",
            "s.yaml",
            "--from-verdicts",
            str(vpath),
            "--judge-task",
            str(task_path),
            "--out",
            str(out_path),
        ]
    )
    err = capsys.readouterr().err
    assert rc == 0
    assert "task package schema" in err  # line 301
    assert "verdicts schema" in err  # line 303 (from load_verdicts warning)
    assert "unknown id" in err  # line 316


# ── agent_api: mint_token retry sleep ladder (lines 144-148) ──────────────────
def test_mint_token_retries_network_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 2:
            raise urllib.error.URLError("dns")

        class _R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(
                    {"access_token": "hdr." + "a" * 900 + ".sig", "api_instance_url": "https://api"}
                ).encode()

        return _R()

    monkeypatch.setattr(agent_api.time, "sleep", lambda *_: None)
    monkeypatch.setattr(agent_api.urllib.request, "urlopen", flaky)
    out = agent_api.mint_token("https://x.my.salesforce.com", "ck", "cs")
    assert out["shape"]["looks_like_jwt"] is True
    assert calls["n"] == 2


def test_mint_token_network_exhausts(monkeypatch):
    monkeypatch.setattr(agent_api.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        agent_api.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("dns"))
    )
    with pytest.raises(agent_api.AgentApiError, match="mint network error"):
        agent_api.mint_token("https://x.my.salesforce.com", "ck", "cs")


# ── agent_api: _http HTTPError body read failure (lines 94-95) ────────────────
def test_http_error_body_unreadable(monkeypatch):
    class _BadErr(urllib.error.HTTPError):
        def __init__(self):
            super().__init__("https://x", 404, "nf", None, None)

        def read(self):
            raise OSError("cannot read body")

    monkeypatch.setattr(agent_api.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(_BadErr()))
    status, body = agent_api._http("GET", "https://x")
    assert status == 404 and body == ""  # body read failed -> empty


# ── judge: _post_json keyword fallback already covered; cover http body read fail (89-90)
def test_post_json_http_error_body_unreadable(monkeypatch):
    class _BadErr(urllib.error.HTTPError):
        def __init__(self):
            super().__init__("https://x", 400, "bad", None, None)

        def read(self):
            raise OSError("nope")

    monkeypatch.setattr(judge.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(_BadErr()))
    with pytest.raises(judge.JudgeError, match="judge HTTP 400"):
        judge._post_json("https://x", {}, {})


# ── sf_external: create_test_definition fire-and-forget (line 45) + never-completes (92)
def test_create_test_definition_runs(monkeypatch):
    seen = {}
    monkeypatch.setattr(sf_external.sfcli, "run_sf", lambda args, **k: seen.update({"args": args}))
    sf_external.create_test_definition("Support", "spec.yaml", "org")
    assert "create" in seen["args"]


def test_fetch_results_raises_when_never_polls(monkeypatch):
    # attempts=0 -> loop body never runs, last stays None -> ExternalPathError (line 92)
    monkeypatch.setattr(sf_external.sfcli, "run_sf_json", lambda *a, **k: {"result": {"status": "IN_PROGRESS"}})
    with pytest.raises(sf_external.ExternalPathError, match="never completed"):
        sf_external.fetch_results("07x", "org", attempts=0)


# ── agent_api: _http with data + headers exercises body-encode + header loop ──
def test_http_with_data_and_headers(monkeypatch):
    captured = {}

    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def getcode(self):
            return 200

        def read(self):
            return b"ok"

    def fake_urlopen(req, timeout=None):
        captured["data"] = req.data
        return _R()

    monkeypatch.setattr(agent_api.urllib.request, "urlopen", fake_urlopen)
    status, body = agent_api._http(
        "POST", "https://x", headers={"Authorization": "Bearer t", "Content-Type": "application/json"}, data={"a": 1}
    )
    assert status == 200 and body == "ok"
    assert captured["data"] == json.dumps({"a": 1}).encode("utf-8")  # body was encoded


def test_mint_token_http_error_body_unreadable(monkeypatch):
    class _BadErr(urllib.error.HTTPError):
        def __init__(self):
            super().__init__("https://x", 400, "bad", None, None)

        def read(self):
            raise OSError("nope")

    monkeypatch.setattr(agent_api.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(_BadErr()))
    with pytest.raises(agent_api.AgentApiError, match="mint failed"):
        agent_api.mint_token("https://x.my.salesforce.com", "ck", "cs")


def test_post_json_sends_headers(monkeypatch):
    captured = {}

    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(req, timeout=None):
        captured["headers"] = dict(req.header_items())
        return _R()

    monkeypatch.setattr(judge.urllib.request, "urlopen", fake_urlopen)
    out = judge._post_json("https://x", {"Authorization": "Bearer k", "Content-Type": "application/json"}, {"p": 1})
    assert out == {"ok": True}
    # header_items lowercases keys; just assert the auth header made it through
    assert any("Bearer k" in v for v in captured["headers"].values())


def test_http_gaierror_exhausts(monkeypatch):
    """socket.gaierror is the DNS-failure transient; after retries it raises (line 108)."""
    import socket

    monkeypatch.setattr(agent_api.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        agent_api.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(socket.gaierror("EAI_AGAIN"))
    )
    with pytest.raises(agent_api.AgentApiError, match="network error"):
        agent_api._http("GET", "https://x", retries=2)


def test_extract_verdict_malformed_brace_then_keyword(monkeypatch):
    """A {...} that is NOT valid JSON forces the except branch (116-117), then the
    keyword scan returns PASS."""
    ok, reason = judge._extract_verdict("verdict {not: valid, json here} but PASS clearly")
    assert ok is True
