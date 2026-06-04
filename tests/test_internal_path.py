"""End-to-end InternalCopilot orchestration using an injected fake session.

Proves the run_session -> score_session flow without any network/secret. The
fake session returns canned responses; the mock judge scores them.
"""

from agentforce_probe import scorer, sf_internal


class _FakeSession:
    """Stand-in for agent_api.AgentApiSession — no network."""

    def __init__(self, replies):
        self._replies = replies
        self._i = 0
        self.started = False
        self.closed = False

    def start(self):
        self.started = True
        return "fake-session-id"

    def send(self, text):
        reply = self._replies[self._i]
        self._i += 1
        return reply

    def close(self):
        self.closed = True


def test_run_session_replays_all_cases_via_injected_session():
    spec = {
        "testCases": [
            {"utterance": "q1", "expectedOutcome": "a1"},
            {"utterance": "q2", "expectedOutcome": "a2", "expectedTopic": "t2"},
        ]
    }
    replies = [
        {"response": "r1", "topic": None, "invokedActions": []},
        {"response": "r2", "topic": "t2", "invokedActions": []},
    ]
    holder = {}

    def factory(instance_url, bot_id, ck, cs, diag):
        s = _FakeSession(replies)
        holder["session"] = s
        return s

    raw = sf_internal.run_session(
        spec=spec,
        instance_url="https://x",
        bot_definition_id="0Xx",
        consumer_key="ck",
        consumer_secret="cs",
        session_factory=factory,
    )

    assert len(raw) == 2
    assert raw[0]["response"] == "r1"
    assert raw[1]["topic"] == "t2"
    assert holder["session"].started is True
    assert holder["session"].closed is True


def test_score_session_with_mock_judge_applies_filtering():
    spec = {
        "testCases": [
            {"utterance": "q1", "expectedOutcome": "a1"},
            {"utterance": "q2", "expectedOutcome": "a2", "expectedTopic": "t2"},
        ]
    }
    raw = [
        {"number": 1, "utterance": "q1", "response": "non-empty", "topic": None, "actions": []},
        {"number": 2, "utterance": "q2", "response": "", "topic": "wrong", "actions": []},
    ]

    def judge_fn(expected_outcome, actual_response, utterance=None):
        ok = bool((actual_response or "").strip())
        return ok, "mock"

    scored = sf_internal.score_session(spec=spec, raw_results=raw, judge_fn=judge_fn)
    assert scored[0]["output"] == "PASS"  # non-empty response
    assert scored[1]["output"] == "FAIL"  # empty response
    assert scored[1]["topic"] == "FAIL"  # expectedTopic t2 != "wrong"
    assert scored[0]["topic"] == "-"  # no expectedTopic declared

    agg, total_pass, total = scorer.aggregate(scored)
    assert agg["output"] == [1, 2]
    assert agg["topic"] == [0, 1]


def test_score_session_skips_judge_when_no_expected_outcome():
    spec = {
        "testCases": [
            {"utterance": "q1", "expectedOutcome": "grounded expectation"},
            {"utterance": "q2"},  # no expectedOutcome
        ]
    }
    raw = [
        {"number": 1, "utterance": "q1", "response": "response one", "topic": None, "actions": []},
        {"number": 2, "utterance": "q2", "response": "response two", "topic": None, "actions": []},
    ]

    judge_calls = []

    def judge_fn(expected_outcome, actual_response, utterance=None):
        judge_calls.append(expected_outcome)
        return True, "graded"

    diag_msgs = []
    scored = sf_internal.score_session(spec=spec, raw_results=raw, judge_fn=judge_fn, diag=diag_msgs.append)

    # judge invoked only for the case with expectedOutcome
    assert len(judge_calls) == 1
    assert judge_calls[0] == "grounded expectation"

    # case with expectedOutcome is scored
    assert scored[0]["output"] == "PASS"
    # case without expectedOutcome stays unscored
    assert scored[1]["output"] == "-"

    # output denominator counts only the grounded case
    agg, _tp, _t = scorer.aggregate(scored)
    assert agg["output"] == [1, 1]

    # diag emits a skip message for the unscored case
    assert any("output not scored" in m for m in diag_msgs)
