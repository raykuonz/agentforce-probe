"""Test-spec loading + the assertion-filtering scorer.

The assertion-filtering rules:

  - topic_assertion   is scored ONLY for cases that declare expectedTopic
  - actions_assertion is scored ONLY for cases that declare expectedActions
  - output_validation (LLM-as-judge) is the primary behavioral signal; scored
    for every case.

A case missing an assertion is rendered as "-" (intentionally not set) and does
NOT count against the score.
"""

import os

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


class SpecError(RuntimeError):
    pass


def load_spec(path):
    """Load a test spec YAML. Returns the parsed dict with validation."""
    if yaml is None:  # pragma: no cover - pyyaml is a hard runtime dependency
        raise SpecError("pyyaml is required to read specs: pip install pyyaml")
    if not os.path.exists(path):
        raise SpecError(f"spec not found: {path}")
    with open(path, encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)
    if not isinstance(spec, dict):
        raise SpecError(f"spec must be a YAML mapping: {path}")
    cases = spec.get("testCases")
    if not isinstance(cases, list) or not cases:
        raise SpecError("spec has no testCases[]")
    for i, c in enumerate(cases):
        if not isinstance(c, dict) or not c.get("utterance"):
            raise SpecError(f"testCases[{i}] missing required 'utterance'")
    return spec


def spec_cases_by_utterance(spec):
    return {c["utterance"]: c for c in spec["testCases"]}


# ── unified case-result model ────────────────────────────────────────────────
# Each scored case is a dict:
#   {
#     "number": int,
#     "utterance": str,
#     "topic": "PASS" | "FAIL" | "-",
#     "actions": "PASS" | "FAIL" | "-",
#     "output": "PASS" | "FAIL" | "-",
#     "response": str,          # agent's actual response text (for evidence)
#     "expectedTopic": str | None,
#     "expectedActions": list | None,
#     "actualTopic": str | None,
#     "actualActions": list | None,
#     "judge_reason": str | None,  # LLM-judge rationale (internal path)
#   }


def _blank_result(number, utterance):
    return {
        "number": number,
        "utterance": utterance,
        "topic": "-",
        "actions": "-",
        "output": "-",
        "response": "",
        "expectedTopic": None,
        "expectedActions": None,
        "actualTopic": None,
        "actualActions": None,
        "judge_reason": None,
        "axes": None,
    }


def score_case(
    spec_case,
    number,
    *,
    topic_pass=None,
    actions_pass=None,
    output_pass=None,
    response="",
    actual_topic=None,
    actual_actions=None,
    judge_reason=None,
    axes=None,
):
    """Apply the filtering rules to produce one unified case result.

    Pass `topic_pass` / `actions_pass` / `output_pass` as booleans, or None to
    mean "not evaluated". Filtering: a dimension is only scored if the spec case
    declares the corresponding expectation.
    """
    r = _blank_result(number, spec_case.get("utterance", ""))
    has_topic = "expectedTopic" in spec_case
    has_actions = "expectedActions" in spec_case
    r["expectedTopic"] = spec_case.get("expectedTopic")
    r["expectedActions"] = spec_case.get("expectedActions")
    r["response"] = response or ""
    r["actualTopic"] = actual_topic
    r["actualActions"] = actual_actions
    r["judge_reason"] = judge_reason
    r["axes"] = axes

    if has_topic and topic_pass is not None:
        r["topic"] = "PASS" if topic_pass else "FAIL"
    if has_actions and actions_pass is not None:
        r["actions"] = "PASS" if actions_pass else "FAIL"
    # output_validation is the primary signal; score it whenever evaluated.
    if output_pass is not None:
        r["output"] = "PASS" if output_pass else "FAIL"
    return r


def aggregate(results):
    """Roll up a list of case results into {'topic':[pass,total], ...} + overall."""
    agg = {"topic": [0, 0], "actions": [0, 0], "output": [0, 0]}
    for r in results:
        for key in ("topic", "actions", "output"):
            v = r[key]
            if v in ("PASS", "FAIL"):
                agg[key][1] += 1
                if v == "PASS":
                    agg[key][0] += 1
    total_pass = sum(v[0] for v in agg.values())
    total = sum(v[1] for v in agg.values())
    return agg, total_pass, total
