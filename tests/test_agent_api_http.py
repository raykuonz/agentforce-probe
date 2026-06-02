"""agent_api HTTP paths via a monkeypatched urllib.request.urlopen.

Covers mint_token (opaque-token rejection, missing fields), the AgentApiSession
lifecycle (start 404/400/412/success, send, close), the _http retry ladder, and
parse_agent_response. No real network and no real secrets.
"""

import io
import json
import urllib.error

import pytest

from agentforce_probe import agent_api


def _jwt(n=1700):
    """A fake but JWT-shaped token: 3 dot-segments, > 800 chars."""
    body = "a" * (n - 8)
    return f"hdr.{body}.sig"


class _FakeResp:
    """Context-manager stand-in for the object urlopen returns."""

    def __init__(self, code=200, body=""):
        self._code = code
        self._body = body.encode("utf-8") if isinstance(body, str) else body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def getcode(self):
        return self._code

    def read(self):
        return self._body


def _http_error(code, body=""):
    return urllib.error.HTTPError(url="https://x", code=code, msg="err", hdrs=None, fp=io.BytesIO(body.encode("utf-8")))


# ── token_shape (pure) ────────────────────────────────────────────────────────
def test_token_shape_jwt():
    s = agent_api.token_shape(_jwt())
    assert s["segments"] == 3 and s["looks_like_jwt"] is True


# ── mint_token ────────────────────────────────────────────────────────────────
def test_mint_token_success(monkeypatch):
    payload = {"access_token": _jwt(), "api_instance_url": "https://test.api.salesforce.com/"}
    monkeypatch.setattr(agent_api.urllib.request, "urlopen", lambda *a, **k: _FakeResp(200, json.dumps(payload)))
    out = agent_api.mint_token("https://x.my.salesforce.com", "ck", "cs")
    assert out["api_instance_url"] == "https://test.api.salesforce.com"  # trailing slash stripped
    assert out["shape"]["looks_like_jwt"] is True


def test_mint_token_opaque_rejected(monkeypatch):
    payload = {"access_token": "short-opaque", "api_instance_url": "https://test.api.salesforce.com"}
    monkeypatch.setattr(agent_api.urllib.request, "urlopen", lambda *a, **k: _FakeResp(200, json.dumps(payload)))
    with pytest.raises(agent_api.AgentApiError, match="OPAQUE"):
        agent_api.mint_token("https://x.my.salesforce.com", "ck", "cs")


def test_mint_token_missing_access_token(monkeypatch):
    payload = {"api_instance_url": "https://test.api.salesforce.com"}
    monkeypatch.setattr(agent_api.urllib.request, "urlopen", lambda *a, **k: _FakeResp(200, json.dumps(payload)))
    with pytest.raises(agent_api.AgentApiError, match="no access_token"):
        agent_api.mint_token("https://x.my.salesforce.com", "ck", "cs")


def test_mint_token_missing_api_instance_url(monkeypatch):
    payload = {"access_token": _jwt()}
    monkeypatch.setattr(agent_api.urllib.request, "urlopen", lambda *a, **k: _FakeResp(200, json.dumps(payload)))
    with pytest.raises(agent_api.AgentApiError, match="no api_instance_url"):
        agent_api.mint_token("https://x.my.salesforce.com", "ck", "cs")


def test_mint_token_http_error(monkeypatch):
    def boom(*a, **k):
        raise _http_error(400, '{"error":"invalid_client"}')

    monkeypatch.setattr(agent_api.urllib.request, "urlopen", boom)
    with pytest.raises(agent_api.AgentApiError, match="mint failed"):
        agent_api.mint_token("https://x.my.salesforce.com", "ck", "cs")


# ── _http retry ladder ────────────────────────────────────────────────────────
def test_http_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _http_error(503, "try again")
        return _FakeResp(200, "ok")

    monkeypatch.setattr(agent_api.time, "sleep", lambda *_: None)
    monkeypatch.setattr(agent_api.urllib.request, "urlopen", flaky)
    status, body = agent_api._http("GET", "https://x")
    assert status == 200 and body == "ok"
    assert calls["n"] == 2


def test_http_4xx_not_retried(monkeypatch):
    calls = {"n": 0}

    def fail(*a, **k):
        calls["n"] += 1
        raise _http_error(404, "nope")

    monkeypatch.setattr(agent_api.urllib.request, "urlopen", fail)
    status, body = agent_api._http("GET", "https://x")
    assert status == 404 and calls["n"] == 1  # 404 returned, not retried


def test_http_network_error_exhausts(monkeypatch):
    monkeypatch.setattr(agent_api.time, "sleep", lambda *_: None)

    def neterr(*a, **k):
        raise urllib.error.URLError("EAI_AGAIN")

    monkeypatch.setattr(agent_api.urllib.request, "urlopen", neterr)
    with pytest.raises(agent_api.AgentApiError, match="network error"):
        agent_api._http("GET", "https://x", retries=2)


# ── AgentApiSession lifecycle ─────────────────────────────────────────────────
def _session():
    return agent_api.AgentApiSession("https://test.api.salesforce.com", _jwt(), "0XxABC")


def test_session_start_success(monkeypatch):
    monkeypatch.setattr(agent_api, "_http", lambda *a, **k: (200, json.dumps({"sessionId": "sess-1"})))
    s = _session()
    assert s.start() == "sess-1"


def test_session_start_404(monkeypatch):
    monkeypatch.setattr(agent_api, "_http", lambda *a, **k: (404, ""))
    with pytest.raises(agent_api.AgentApiError, match="404"):
        _session().start()


def test_session_start_400_invalid_user(monkeypatch):
    monkeypatch.setattr(agent_api, "_http", lambda *a, **k: (400, "Invalid user ID provided"))
    with pytest.raises(agent_api.AgentApiError, match="Invalid user ID"):
        _session().start()


def test_session_start_412_config(monkeypatch):
    monkeypatch.setattr(agent_api, "_http", lambda *a, **k: (412, "Invalid Config"))
    with pytest.raises(agent_api.AgentApiError, match="412"):
        _session().start()


def test_session_start_other_status(monkeypatch):
    monkeypatch.setattr(agent_api, "_http", lambda *a, **k: (500, "server boom"))
    with pytest.raises(agent_api.AgentApiError, match="session create failed"):
        _session().start()


def test_session_start_no_session_id(monkeypatch):
    monkeypatch.setattr(agent_api, "_http", lambda *a, **k: (200, json.dumps({"foo": "bar"})))
    with pytest.raises(agent_api.AgentApiError, match="no sessionId"):
        _session().start()


def test_session_send_requires_start():
    with pytest.raises(agent_api.AgentApiError, match="no active session"):
        _session().send("hi")


def test_session_send_success(monkeypatch):
    reply = {"messages": [{"message": "hello back", "invokedActions": [{"name": "LookupOrder"}], "topic": "Orders"}]}
    seq = iter([(200, json.dumps({"sessionId": "s1"})), (200, json.dumps(reply))])
    monkeypatch.setattr(agent_api, "_http", lambda *a, **k: next(seq))
    s = _session()
    s.start()
    out = s.send("where is my order")
    assert out["response"] == "hello back"
    assert out["invokedActions"] == ["LookupOrder"]
    assert out["topic"] == "Orders"


def test_session_send_bad_status(monkeypatch):
    seq = iter([(200, json.dumps({"sessionId": "s1"})), (500, "boom")])
    monkeypatch.setattr(agent_api, "_http", lambda *a, **k: next(seq))
    s = _session()
    s.start()
    with pytest.raises(agent_api.AgentApiError, match="send message failed"):
        s.send("hi")


def test_session_close_best_effort(monkeypatch):
    seq = iter([(200, json.dumps({"sessionId": "s1"}))])
    monkeypatch.setattr(agent_api, "_http", lambda *a, **k: next(seq, (200, "")))
    s = _session()
    s.start()
    s.close()  # must not raise even though _http iterator is exhausted -> handled
    assert s.session_id is None


# ── parse_agent_response (pure) ───────────────────────────────────────────────
def test_parse_agent_response_nested_result():
    obj = {"result": {"messages": [{"message": "hi", "actions": [{"function": {"name": "DoThing"}}]}]}}
    out = agent_api.parse_agent_response(obj)
    assert out["response"] == "hi"
    assert out["invokedActions"] == ["DoThing"]


def test_parse_agent_response_empty():
    out = agent_api.parse_agent_response({})
    assert out["response"] == "" and out["invokedActions"] == [] and out["topic"] is None
