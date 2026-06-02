"""judge: API-key provider paths (openai/anthropic) + verdict extraction.

_post_json is monkeypatched so no LLM is contacted. Covers parse_judge, the
mock provider, the openai + anthropic response shapes, the no-key error, the
unknown-provider error, and _extract_verdict's fenced/keyword fallbacks.
"""

import pytest

from agentforce_probe import judge


# ── parse_judge ───────────────────────────────────────────────────────────────
def test_parse_judge_provider_model():
    assert judge.parse_judge("openai:gpt-4o") == ("openai", "gpt-4o")


def test_parse_judge_provider_only():
    assert judge.parse_judge("anthropic") == ("anthropic", "")


def test_parse_judge_empty_raises():
    with pytest.raises(judge.JudgeError):
        judge.parse_judge("")


# ── mock provider ─────────────────────────────────────────────────────────────
def test_judge_mock_pass():
    ok, reason = judge.judge_case("mock", "", None, "u", "exp", "a non-empty response")
    assert ok is True


def test_judge_mock_fail_on_empty():
    ok, reason = judge.judge_case("mock", "", None, "u", "exp", "")
    assert ok is False


# ── no key / unknown provider ─────────────────────────────────────────────────
def test_judge_no_api_key_raises():
    with pytest.raises(judge.JudgeError, match="no API key"):
        judge.judge_case("openai", "gpt-4o", None, "u", "exp", "resp")


def test_judge_unknown_provider_raises():
    with pytest.raises(judge.JudgeError, match="unknown judge provider"):
        judge.judge_case("gemini", "x", "key", "u", "exp", "resp")


# ── openai path ───────────────────────────────────────────────────────────────
def test_judge_openai_pass(monkeypatch):
    monkeypatch.setattr(
        judge,
        "_post_json",
        lambda *a, **k: {"choices": [{"message": {"content": '{"verdict":"PASS","reason":"good"}'}}]},
    )
    ok, reason = judge.judge_case("openai", "", "sk-x", "u", "exp", "resp")
    assert ok is True and reason == "good"


def test_judge_openai_fail(monkeypatch):
    monkeypatch.setattr(
        judge,
        "_post_json",
        lambda *a, **k: {"choices": [{"message": {"content": '{"verdict":"FAIL","reason":"leaked data"}'}}]},
    )
    ok, reason = judge.judge_case("openai", "gpt-4o", "sk-x", "u", "exp", "resp")
    assert ok is False and "leaked" in reason


# ── anthropic path ────────────────────────────────────────────────────────────
def test_judge_anthropic_pass(monkeypatch):
    monkeypatch.setattr(
        judge,
        "_post_json",
        lambda *a, **k: {"content": [{"type": "text", "text": '{"verdict":"PASS","reason":"ok"}'}]},
    )
    ok, reason = judge.judge_case("anthropic", "", "sk-ant", "u", "exp", "resp")
    assert ok is True and reason == "ok"


# ── _extract_verdict branches ─────────────────────────────────────────────────
def test_extract_verdict_fenced_json():
    ok, reason = judge._extract_verdict('```json\n{"verdict":"PASS","reason":"fine"}\n```')
    assert ok is True and reason == "fine"


def test_extract_verdict_keyword_fallback_pass():
    ok, reason = judge._extract_verdict("The answer is PASS overall.")
    assert ok is True


def test_extract_verdict_keyword_fallback_fail():
    ok, reason = judge._extract_verdict("This is a FAIL because of leakage.")
    assert ok is False


def test_extract_verdict_empty():
    ok, reason = judge._extract_verdict("")
    assert ok is False and "empty" in reason


def test_extract_verdict_no_reason_defaults():
    ok, reason = judge._extract_verdict('{"verdict":"PASS"}')
    assert ok is True and reason == "(no reason given)"
