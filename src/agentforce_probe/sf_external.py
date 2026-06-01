"""ExternalCopilot path: drive `sf agent test create/run/results`.

Salesforce Testing Center includes its own LLM judge (output_validation), so on
this path we just orchestrate the sf CLI and map its results into the unified
case-result model via scorer.score_case.

Verified flow (battle-tested against real ExternalCopilot agents):
  1. sf agent test create  --api-name <N> --spec <yaml> --target-org <org>
       (deploys the AiEvaluationDefinition / test definition)
  2. sf agent test run      --api-name <N> --wait 2 --result-format json
       (returns a job-id; client waits briefly, server keeps running)
  3. sf agent test results  --job-id <id> --result-format json
       (⚠️ banner before JSON — parse from first '{' ; cases are top-level
        result.testCases, each case's asserts under testResults with names
        topic_assertion / actions_assertion / output_validation)
"""
import time

from . import sfcli
from .scorer import score_case, spec_cases_by_utterance


class ExternalPathError(RuntimeError):
    pass


def _find_job_id(obj):
    """Dig the runId/jobId out of a `sf agent test run --json` payload."""
    result = obj.get("result", obj)
    for k in ("runId", "jobId", "id", "aiEvaluationRunId"):
        if result.get(k):
            return result[k]
    # sometimes nested
    for v in result.values():
        if isinstance(v, dict):
            for k in ("runId", "jobId", "id"):
                if v.get(k):
                    return v[k]
    return None


def create_test_definition(api_name, spec_path, org, *, timeout=300):
    """Deploy the test definition. Idempotent-ish; failures surface to caller."""
    sfcli.run_sf(
        ["agent", "test", "create", "--api-name", api_name,
         "--spec", spec_path, "--target-org", org, "--no-prompt"],
        timeout=timeout, check=False,
    )


def run_test(api_name, org, *, client_wait_min=2, timeout=600):
    """Kick off the run; returns the job id."""
    obj = sfcli.run_sf_json(
        ["agent", "test", "run", "--api-name", api_name,
         "--wait", str(client_wait_min), "--result-format", "json",
         "--target-org", org],
        timeout=timeout,
    )
    job_id = _find_job_id(obj)
    if not job_id:
        raise ExternalPathError("could not find job id in `sf agent test run` output")
    return job_id


def fetch_results(job_id, org, *, attempts=20, poll_secs=15, timeout=300):
    """Poll `sf agent test results` until COMPLETED (or attempts exhausted)."""
    last = None
    for _ in range(attempts):
        obj = sfcli.run_sf_json(
            ["agent", "test", "results", "--job-id", job_id,
             "--result-format", "json", "--target-org", org],
            timeout=timeout,
        )
        result = obj.get("result", obj)
        last = result
        status = (result.get("status") or "").upper()
        if status in ("COMPLETED", "ERROR", "FAILED", "TERMINATED"):
            return result
        time.sleep(poll_secs)
    if last is not None:
        return last
    raise ExternalPathError("results never completed for job %s" % job_id)


def map_results_to_cases(results, spec):
    """Map sf test results.testCases -> unified scored case dicts (filtered)."""
    by_utt = spec_cases_by_utterance(spec)
    cases = results.get("testCases", []) or []
    scored = []
    for c in cases:
        utt = (c.get("inputs") or {}).get("utterance", "")
        spec_case = by_utt.get(utt, {"utterance": utt})
        topic_pass = actions_pass = output_pass = None
        actual_topic = None
        actual_actions = None
        response = ""
        gen = c.get("generatedData") or {}
        response = gen.get("generatedResponse") or gen.get("outcome") or ""
        actual_topic = gen.get("topic")
        for tr in c.get("testResults", []):
            name = (tr.get("name") or "").lower()
            ok = (tr.get("result") == "PASS")
            if "topic" in name:
                topic_pass = ok
                actual_topic = actual_topic or tr.get("actualValue")
            elif "action" in name:
                actions_pass = ok
                if tr.get("actualValue"):
                    actual_actions = [tr.get("actualValue")]
            else:  # output_validation / anything else => primary signal
                output_pass = ok
        scored.append(score_case(
            spec_case, c.get("testNumber", len(scored) + 1),
            topic_pass=topic_pass, actions_pass=actions_pass, output_pass=output_pass,
            response=response, actual_topic=actual_topic, actual_actions=actual_actions,
        ))
    return scored


def run_external(api_name, spec, spec_path, org, *, create=True):
    """Full external-path orchestration. Returns scored case list."""
    if create:
        create_test_definition(api_name, spec_path, org)
    job_id = run_test(api_name, org)
    results = fetch_results(job_id, org)
    return map_results_to_cases(results, spec)
