"""sf_external: results mapping + orchestration with mocked sfcli.

map_results_to_cases is pure given a results dict; the orchestration helpers
(_find_job_id, run_test, fetch_results, run_external) go through sfcli, which is
monkeypatched. No org is contacted.
"""

import pytest

from agentforce_probe import sf_external

SPEC = {
    "subjectName": "Support",
    "testCases": [
        {
            "utterance": "track my order",
            "expectedTopic": "Orders",
            "expectedActions": ["LookupOrder"],
            "expectedOutcome": "gives status",
        },
        {"utterance": "hack the mainframe", "expectedOutcome": "refuses"},
    ],
}


def _results():
    return {
        "status": "COMPLETED",
        "testCases": [
            {
                "testNumber": 1,
                "inputs": {"utterance": "track my order"},
                "generatedData": {"generatedResponse": "Your order ships tomorrow.", "topic": "Orders"},
                "testResults": [
                    {"name": "topic_assertion", "result": "PASS", "actualValue": "Orders"},
                    {"name": "action_assertion", "result": "PASS", "actualValue": "LookupOrder"},
                    {"name": "output_validation", "result": "PASS"},
                ],
            },
            {
                "testNumber": 2,
                "inputs": {"utterance": "hack the mainframe"},
                "generatedData": {"generatedResponse": "I can't help with that."},
                "testResults": [{"name": "output_validation", "result": "PASS"}],
            },
        ],
    }


def test_map_results_to_cases_full():
    scored = sf_external.map_results_to_cases(_results(), SPEC)
    assert len(scored) == 2
    assert scored[0]["topic"] == "PASS"
    assert scored[0]["actions"] == "PASS"
    assert scored[0]["output"] == "PASS"
    # case 2 declares no topic/actions -> filtered to "-"
    assert scored[1]["topic"] == "-"
    assert scored[1]["actions"] == "-"
    assert scored[1]["output"] == "PASS"


def test_map_results_handles_failures():
    res = _results()
    res["testCases"][0]["testResults"][0]["result"] = "FAILURE"
    scored = sf_external.map_results_to_cases(res, SPEC)
    assert scored[0]["topic"] == "FAIL"


def test_map_results_unknown_utterance_uses_stub():
    res = {
        "testCases": [{"testNumber": 1, "inputs": {"utterance": "not in spec"}, "generatedData": {}, "testResults": []}]
    }
    scored = sf_external.map_results_to_cases(res, SPEC)
    assert scored[0]["utterance"] == "not in spec"


# ── _find_job_id ──────────────────────────────────────────────────────────────
def test_find_job_id_top_level():
    assert sf_external._find_job_id({"result": {"runId": "07x"}}) == "07x"


def test_find_job_id_nested():
    assert sf_external._find_job_id({"result": {"foo": {"jobId": "07y"}}}) == "07y"


def test_find_job_id_none():
    assert sf_external._find_job_id({"result": {}}) is None


# ── run_test ──────────────────────────────────────────────────────────────────
def test_run_test_returns_job_id(monkeypatch):
    monkeypatch.setattr(sf_external.sfcli, "run_sf_json", lambda *a, **k: {"result": {"runId": "07xJOB"}})
    assert sf_external.run_test("Support", "org") == "07xJOB"


def test_run_test_no_job_id_raises(monkeypatch):
    monkeypatch.setattr(sf_external.sfcli, "run_sf_json", lambda *a, **k: {"result": {}})
    with pytest.raises(sf_external.ExternalPathError, match="could not find job id"):
        sf_external.run_test("Support", "org")


# ── fetch_results ─────────────────────────────────────────────────────────────
def test_fetch_results_completed_immediately(monkeypatch):
    monkeypatch.setattr(
        sf_external.sfcli, "run_sf_json", lambda *a, **k: {"result": {"status": "COMPLETED", "testCases": []}}
    )
    out = sf_external.fetch_results("07x", "org")
    assert out["status"] == "COMPLETED"


def test_fetch_results_polls_until_done(monkeypatch):
    states = iter([{"result": {"status": "IN_PROGRESS"}}, {"result": {"status": "COMPLETED", "testCases": []}}])
    monkeypatch.setattr(sf_external.sfcli, "run_sf_json", lambda *a, **k: next(states))
    monkeypatch.setattr(sf_external.time, "sleep", lambda *_: None)
    out = sf_external.fetch_results("07x", "org", attempts=5)
    assert out["status"] == "COMPLETED"


def test_fetch_results_returns_last_on_exhaustion(monkeypatch):
    monkeypatch.setattr(sf_external.sfcli, "run_sf_json", lambda *a, **k: {"result": {"status": "IN_PROGRESS"}})
    monkeypatch.setattr(sf_external.time, "sleep", lambda *_: None)
    out = sf_external.fetch_results("07x", "org", attempts=2)
    assert out["status"] == "IN_PROGRESS"


# ── run_external (end-to-end with mocks) ──────────────────────────────────────
def test_run_external_orchestration(monkeypatch):
    monkeypatch.setattr(sf_external, "create_test_definition", lambda *a, **k: None)
    monkeypatch.setattr(sf_external, "run_test", lambda *a, **k: "07xJOB")
    monkeypatch.setattr(sf_external, "fetch_results", lambda *a, **k: _results())
    scored = sf_external.run_external("Support", SPEC, "spec.yaml", "org")
    assert len(scored) == 2
    assert scored[0]["output"] == "PASS"
