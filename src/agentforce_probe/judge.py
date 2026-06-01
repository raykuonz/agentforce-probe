"""Configurable LLM-as-judge for the InternalCopilot path.

The judge receives (utterance, expectedOutcome, actual response) and returns
PASS/FAIL + a short reason. This mirrors the output_validation signal that
Salesforce Testing Center provides for free on the ExternalCopilot path.

Privacy: the judge is the ONLY non-Salesforce network endpoint this tool ever
contacts, and only when the Internal path is exercised. The judge prompt
contains test utterances + agent responses (test data, not production PII), and
the API key is read from config and sent only in the Authorization header — it
is never logged or written to evidence.

Providers supported: openai, anthropic. `--judge provider:model`.
A `mock` provider is provided for offline/dry-run scoring (no network).

A fourth provider, `handoff`, contacts NO LLM at all. Instead it implements a
three-step "Claude Code file handoff" protocol for teams that have Claude Code
open in their editor but no raw API key:

  ① the tool replays the Agent API session and writes a judge TASK PACKAGE
     (<agent>-judge-task.json) plus a human instruction file (<agent>-JUDGING.md);
  ② a developer pastes the instructions into Claude Code, which reads the task
     package and writes a VERDICTS file (<agent>-judge-verdicts.json) per a fixed
     schema;
  ③ the tool reads the verdicts back (`run --from-verdicts ...`), applies the
     existing filtering rules, and emits the same unified evidence markdown.

Privacy: the task package and verdicts files contain ONLY test data (utterances,
expected outcomes, agent responses) — never secrets or tokens.
"""
import json
import os
import socket
import time
import urllib.error
import urllib.request


class JudgeError(RuntimeError):
    pass


SYSTEM_PROMPT = (
    "You are a strict QA grader for an enterprise AI agent. Given a user "
    "utterance, the expected outcome, and the agent's actual response, decide "
    "whether the actual response satisfies the expected outcome. Be conservative: "
    "if the agent leaks protected data, fails a security gate, fabricates figures, "
    "or does not do what the expected outcome requires, return FAIL. "
    "Respond with STRICT JSON only: {\"verdict\":\"PASS\"|\"FAIL\",\"reason\":\"...\"}."
)


def build_user_prompt(utterance, expected_outcome, actual_response):
    return (
        "UTTERANCE:\n%s\n\nEXPECTED OUTCOME:\n%s\n\nACTUAL AGENT RESPONSE:\n%s\n\n"
        "Return the JSON verdict now." % (
            utterance, expected_outcome or "(none provided)", actual_response or "(empty)")
    )


def parse_judge(provider_model):
    """'provider:model' -> (provider, model). Defaults model per provider."""
    if not provider_model:
        raise JudgeError("no judge specified")
    if ":" in provider_model:
        provider, model = provider_model.split(":", 1)
    else:
        provider, model = provider_model, ""
    provider = provider.strip().lower()
    model = model.strip()
    return provider, model


def _post_json(url, headers, payload, timeout=60, retries=3):
    body = json.dumps(payload).encode("utf-8")
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, method="POST")
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise JudgeError("judge HTTP %s: %s" % (e.code, detail[:300]))
        except (urllib.error.URLError, socket.timeout, socket.gaierror) as e:
            last = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise JudgeError("judge network error after %d attempts: %s" % (retries, e))
    raise JudgeError("judge request failed: %s" % last)


def _extract_verdict(text):
    """Pull {"verdict","reason"} out of model text (tolerant of code fences)."""
    if not text:
        return False, "judge returned empty output"
    s = text.find("{")
    e = text.rfind("}")
    if s != -1 and e != -1 and e > s:
        try:
            obj = json.loads(text[s:e + 1])
            verdict = str(obj.get("verdict", "")).upper().strip()
            reason = str(obj.get("reason", "")).strip()
            return verdict == "PASS", reason or "(no reason given)"
        except Exception:
            pass
    # Fallback: keyword scan
    up = text.upper()
    if "PASS" in up and "FAIL" not in up:
        return True, text.strip()[:300]
    return False, text.strip()[:300]


def judge_case(provider, model, api_key, utterance, expected_outcome, actual_response):
    """Return (passed: bool, reason: str). Routes to provider implementation."""
    if provider == "mock":
        # Offline heuristic for dry runs / tests: non-empty response with no
        # obvious refusal-of-everything => PASS. Never used against a real org.
        ok = bool((actual_response or "").strip())
        return ok, "mock judge: response present" if ok else "mock judge: empty response"

    if not api_key:
        raise JudgeError(
            "no API key for judge provider '%s' (set the matching AGENTPROBE_*_API_KEY)"
            % provider)

    user = build_user_prompt(utterance, expected_outcome, actual_response)

    if provider == "openai":
        model = model or "gpt-4o-mini"
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        }
        resp = _post_json(url, headers, payload)
        text = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        return _extract_verdict(text)

    if provider == "anthropic":
        model = model or "claude-3-5-sonnet-latest"
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 512,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user}],
        }
        resp = _post_json(url, headers, payload)
        parts = resp.get("content", [])
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        return _extract_verdict(text)

    raise JudgeError(
        "unknown judge provider: %s (supported: openai, anthropic, mock, handoff)"
        % provider)


# ── handoff (Claude Code file-handoff) protocol ───────────────────────────────
# Schema version tags. Bump these if the on-disk shapes change.
TASK_SCHEMA = "agentforce-probe/judge-task@1"
VERDICTS_SCHEMA = "agentforce-probe/judge-verdicts@1"

# The rubric handed to Claude Code reuses SYSTEM_PROMPT's wording verbatim so the
# file-handoff judge grades by the same standard as the API-key judge.
HANDOFF_RUBRIC = SYSTEM_PROMPT

HANDOFF_INSTRUCTIONS = (
    "For each case, decide if actual_response satisfies expected_outcome. "
    "Write {id,verdict,reason} for every case into the verdicts file. "
    "Do not skip any case."
)


def task_package_path(out_path, agent_name):
    """Path for <agent>-judge-task.json next to --out (or cwd if no --out)."""
    d = os.path.dirname(os.path.abspath(out_path)) if out_path else os.getcwd()
    return os.path.join(d, "%s-judge-task.json" % agent_name)


def judging_md_path(out_path, agent_name):
    d = os.path.dirname(os.path.abspath(out_path)) if out_path else os.getcwd()
    return os.path.join(d, "%s-JUDGING.md" % agent_name)


def verdicts_path(out_path, agent_name):
    d = os.path.dirname(os.path.abspath(out_path)) if out_path else os.getcwd()
    return os.path.join(d, "%s-judge-verdicts.json" % agent_name)


def build_task_package(agent_name, org_alias, spec, raw_results):
    """Build the judge-task.json dict from spec + raw session results.

    raw_results: list of {number, utterance, response, topic, actions} (from
    sf_internal.run_session). expected_outcome is read from the matching spec
    case by 1-based number. Contains ONLY test data — never secrets.
    """
    cases_by_num = {i: c for i, c in enumerate(spec["testCases"], start=1)}
    cases = []
    for raw in raw_results:
        i = raw["number"]
        spec_case = cases_by_num.get(i, {})
        cases.append({
            "id": i,
            "utterance": raw.get("utterance", ""),
            "expected_outcome": spec_case.get("expectedOutcome") or "",
            "actual_response": raw.get("response", "") or "",
            "actual_topic": raw.get("topic"),
            "actual_actions": list(raw.get("actions") or []),
        })
    return {
        "schema": TASK_SCHEMA,
        "agent": agent_name,
        "org": org_alias,
        "rubric": HANDOFF_RUBRIC,
        "instructions": HANDOFF_INSTRUCTIONS,
        "cases": cases,
    }


def write_task_package(path, task):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(task, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def render_judging_md(agent_name, task_path, verdicts_path_str):
    """Human instruction file: a block to paste into Claude Code + the protocol."""
    task_base = os.path.basename(task_path)
    verdicts_base = os.path.basename(verdicts_path_str)
    lines = []
    lines.append("# Judging `%s` with Claude Code" % agent_name)
    lines.append("")
    lines.append("This agent runs on the **InternalCopilot** path, which needs an "
                 "LLM to grade each response (PASS/FAIL). Instead of a raw API key, "
                 "you can use **Claude Code** as the judge.")
    lines.append("")
    lines.append("`agentforce-probe` already replayed the agent and wrote the judging "
                 "materials. **No secrets are in any of these files** — only test "
                 "utterances, expected outcomes, and the agent's responses.")
    lines.append("")
    lines.append("## Step 1 — paste this to Claude Code (open in this repo)")
    lines.append("")
    lines.append("> You are a strict QA grader. Read the file `%s` in this "
                 "repository. It is JSON of schema `%s` with a `rubric` and a list "
                 "of `cases`, each having `id`, `utterance`, `expected_outcome`, "
                 "`actual_response`, `actual_topic`, and `actual_actions`."
                 % (task_base, TASK_SCHEMA))
    lines.append("> ")
    lines.append("> For **every** case, apply the rubric in the file and decide "
                 "whether `actual_response` satisfies `expected_outcome`. The "
                 "verdict must be exactly `PASS` or `FAIL` (uppercase, nothing "
                 "else). Be conservative: if the agent leaks protected data, fails "
                 "a security gate, fabricates figures, or does not do what the "
                 "expected outcome requires, the verdict is `FAIL`.")
    lines.append("> ")
    lines.append("> Write the results to a new file `%s` in this repository, "
                 "using exactly this JSON schema:" % verdicts_base)
    lines.append("> ")
    lines.append("> ```json")
    lines.append("> {")
    lines.append('>   "schema": "%s",' % VERDICTS_SCHEMA)
    lines.append('>   "agent": "%s",' % agent_name)
    lines.append('>   "verdicts": [')
    lines.append('>     {"id": 1, "verdict": "PASS", "reason": "..."},')
    lines.append('>     {"id": 2, "verdict": "FAIL", "reason": "..."}')
    lines.append(">   ]")
    lines.append("> }")
    lines.append("> ```")
    lines.append("> ")
    lines.append("> Rules: include exactly one entry per case `id` (do not skip "
                 "any), `verdict` is only `PASS` or `FAIL`, keep `reason` short. "
                 "Do not add or remove fields.")
    lines.append("")
    lines.append("## Step 2 — collect the verdicts into evidence")
    lines.append("")
    lines.append("Once Claude Code has written `%s`, run:" % verdicts_base)
    lines.append("")
    lines.append("```bash")
    lines.append("python3 -m agentforce_probe run --org <alias> --agent %s \\" % agent_name)
    lines.append("  --spec <spec.yaml> --from-verdicts %s" % verdicts_base)
    lines.append("```")
    lines.append("")
    lines.append("That reads the verdicts back, applies the assertion-filtering "
                 "rules, and writes the unified evidence markdown. It validates "
                 "that every case id has a verdict and that each verdict is "
                 "PASS/FAIL.")
    lines.append("")
    return "\n".join(lines) + "\n"


def write_judging_md(path, content):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


class HandoffError(JudgeError):
    pass


def load_task_package(path):
    """Read + lightly validate a judge-task.json. Returns the parsed dict."""
    if not os.path.exists(path):
        raise HandoffError("judge task package not found: %s" % path)
    with open(path, "r", encoding="utf-8") as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise HandoffError("judge task package must be a JSON object: %s" % path)
    if not isinstance(obj.get("cases"), list) or not obj["cases"]:
        raise HandoffError("judge task package has no cases[]: %s" % path)
    return obj


def load_verdicts(path):
    """Read + validate a judge-verdicts.json.

    Returns (verdicts_by_id: {int: {"verdict": str, "reason": str}}, warnings:
    list[str]). Raises HandoffError on hard errors (bad shape, illegal verdict).
    """
    if not os.path.exists(path):
        raise HandoffError("verdicts file not found: %s" % path)
    with open(path, "r", encoding="utf-8") as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise HandoffError("verdicts file must be a JSON object: %s" % path)

    warnings = []
    schema = obj.get("schema")
    if schema != VERDICTS_SCHEMA:
        warnings.append(
            "verdicts schema is %r, expected %r" % (schema, VERDICTS_SCHEMA))

    verdicts = obj.get("verdicts")
    if not isinstance(verdicts, list):
        raise HandoffError("verdicts file missing a verdicts[] array")

    by_id = {}
    for idx, v in enumerate(verdicts):
        if not isinstance(v, dict):
            raise HandoffError("verdicts[%d] is not an object" % idx)
        if "id" not in v:
            raise HandoffError("verdicts[%d] missing 'id'" % idx)
        try:
            cid = int(v["id"])
        except (TypeError, ValueError):
            raise HandoffError("verdicts[%d] has non-integer id %r" % (idx, v.get("id")))
        verdict = str(v.get("verdict", "")).upper().strip()
        if verdict not in ("PASS", "FAIL"):
            raise HandoffError(
                "verdicts[%d] (id=%s) has illegal verdict %r — must be PASS or FAIL"
                % (idx, cid, v.get("verdict")))
        if cid in by_id:
            raise HandoffError("duplicate verdict for id %d" % cid)
        by_id[cid] = {"verdict": verdict, "reason": str(v.get("reason", "")).strip()}
    return by_id, warnings
