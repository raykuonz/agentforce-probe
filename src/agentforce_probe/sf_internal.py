"""InternalCopilot path orchestration: Agent API session -> judge -> scored cases.

Ties together agent_api (mint + headless session), judge (LLM-as-judge), and
scorer (filtering). Topic/actions are checked directly from the live Agent API
response; output_validation is delegated to the configured judge.

The "run the session" step and the "judge the output" step are DECOUPLED:

  * run_session(...)   mints a token, opens one headless Agent API session, and
                       returns the raw per-case results
                       ({number, utterance, response, topic, actions}). No LLM
                       is contacted. This is what the `handoff` (Claude Code
                       file-handoff) judge mode and the live API-key judge both
                       build on.
  * score_session(...) takes those raw results + a callable judge and applies the
                       assertion-filtering scorer to produce scored cases.
  * run_internal(...)  is the original end-to-end convenience: run_session then
                       score_session with the LLM judge (API-key path, unchanged
                       behavior).
"""

from . import agent_api
from . import judge as judge_mod
from .scorer import score_case


class InternalPathError(RuntimeError):
    pass


def run_session(
    *, spec, instance_url, bot_definition_id, consumer_key, consumer_secret, diag=None, session_factory=None
):
    """Mint + open one headless Agent API session and replay every spec case.

    Returns a list of RAW per-case results (no scoring, no LLM):

        {"number": int, "utterance": str, "response": str,
         "topic": str|None, "actions": list[str]}

    `diag` (optional callable) receives short non-secret diagnostic strings.
    `session_factory` (optional callable) lets tests inject a fake session; it is
    called as session_factory(instance_url, bot_definition_id, consumer_key,
    consumer_secret, diag) and must return an object exposing .start(), .send(),
    and .close() like agent_api.AgentApiSession. When omitted, a real minted
    Agent API session is used.
    """

    def _diag(msg):
        if diag:
            diag(msg)

    if session_factory is not None:
        session = session_factory(instance_url, bot_definition_id, consumer_key, consumer_secret, _diag)
    else:
        minted = agent_api.mint_token(instance_url, consumer_key, consumer_secret)
        shape = minted["shape"]
        _diag(f"minted token: segments={shape['segments']} len={shape['len']} (JWT ok)")
        _diag(f"agent api host: {minted['api_instance_url']}")
        session = agent_api.AgentApiSession(
            minted["api_instance_url"], minted["token"], bot_definition_id, my_domain_url=instance_url
        )

    sid = session.start()
    _diag(f"session started: {sid}")

    raw = []
    try:
        for i, c in enumerate(spec["testCases"], start=1):
            utt = c["utterance"]
            reply = session.send(utt)
            raw.append(
                {
                    "number": i,
                    "utterance": utt,
                    "response": reply.get("response", "") or "",
                    "topic": reply.get("topic"),
                    "actions": reply.get("invokedActions") or [],
                }
            )
            _diag(f"case {i} replayed (response len={len(raw[-1]['response'])})")
    finally:
        session.close()

    return raw


def _topic_actions_for_case(spec_case, actual_topic, actual_actions):
    """Compute topic_pass / actions_pass against the spec case (no LLM)."""
    topic_pass = None
    if "expectedTopic" in spec_case and actual_topic is not None:
        topic_pass = str(actual_topic) == str(spec_case["expectedTopic"])
    actions_pass = None
    if "expectedActions" in spec_case:
        exp = set(spec_case.get("expectedActions") or [])
        got = set(actual_actions or [])
        actions_pass = exp.issubset(got)
    return topic_pass, actions_pass


def score_session(*, spec, raw_results, judge_fn, diag=None):
    """Score raw session results (from run_session) into filtered case results.

    `judge_fn(utterance, expected_outcome, actual_response) -> (passed, reason)`
    is the output_validation signal. topic/actions come straight from the raw
    live response. Returns the scored case list (scorer.score_case shape).
    """

    def _diag(msg):
        if diag:
            diag(msg)

    cases = spec["testCases"]
    scored = []
    for raw in raw_results:
        i = raw["number"]
        c = cases[i - 1]
        topic_pass, actions_pass = _topic_actions_for_case(c, raw.get("topic"), raw.get("actions"))
        passed, reason = judge_fn(c.get("expectedOutcome"), raw.get("response"), utterance=raw.get("utterance"))
        scored.append(
            score_case(
                c,
                i,
                topic_pass=topic_pass,
                actions_pass=actions_pass,
                output_pass=passed,
                response=raw.get("response", ""),
                actual_topic=raw.get("topic"),
                actual_actions=raw.get("actions"),
                judge_reason=reason,
            )
        )
        _diag(f"case {i} scored (output={'PASS' if passed else 'FAIL'})")
    return scored


def run_internal(
    *,
    spec,
    instance_url,
    bot_definition_id,
    consumer_key,
    consumer_secret,
    judge_provider,
    judge_model,
    judge_api_key,
    diag=None,
):
    """Run every spec case through one Agent API session, judging each (API-key
    path). Unchanged end-to-end behavior; now built on run_session +
    score_session. Returns scored case list.
    """
    raw = run_session(
        spec=spec,
        instance_url=instance_url,
        bot_definition_id=bot_definition_id,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        diag=diag,
    )

    def _judge(expected_outcome, actual_response, utterance=None):
        return judge_mod.judge_case(
            judge_provider, judge_model, judge_api_key, utterance, expected_outcome, actual_response
        )

    return score_session(spec=spec, raw_results=raw, judge_fn=_judge, diag=diag)
