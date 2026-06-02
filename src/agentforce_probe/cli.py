#!/usr/bin/env python3
"""agentforce-probe CLI entrypoint.

Usage:
  agentforce-probe run    --org <alias> --agent <Name> --spec <spec.yaml>
                          [--judge provider:model] [--out evidence.md] [--dry-run]
  agentforce-probe doctor --org <alias>

Privacy: fully local. The only network calls are to the target Salesforce org
and (Internal path only) the configured judge LLM. Secrets are read from a
gitignored .env or environment variables and are NEVER printed or written to
evidence.
"""

import argparse
import sys

from . import config as config_mod
from . import doctor as doctor_mod
from . import recommendations as rec_mod


def _print(msg=""):
    sys.stdout.write(str(msg) + "\n")


def _err(msg):
    sys.stderr.write(str(msg) + "\n")


# ── scan ──────────────────────────────────────────────────────────────────────
def cmd_scan(args):
    from . import scan as scan_mod

    specs = scan_mod.discover_specs(args.root)
    _print(scan_mod.render_discovery(specs, args.root))

    if not args.run:
        return 0
    if not args.org:
        _err("\n--run needs --org <alias> to execute the discovered specs.")
        return 2
    if not specs:
        return 0

    # Execute each discovered spec through the normal run path.
    worst = 0
    for s in specs:
        _print("")
        _print("─" * 60)
        run_args = argparse.Namespace(
            org=args.org,
            agent=s["agent"],
            spec=s["path"],
            judge=args.judge,
            out=None,
            from_results=None,
            from_verdicts=None,
            judge_task=None,
            dry_run=False,
            force_type=None,
            bot_id=None,
        )
        code = cmd_run(run_args)
        worst = max(worst, code)
    return worst


# ── doctor ────────────────────────────────────────────────────────────────────
def cmd_doctor(args):
    cfg = config_mod.Config()
    checks, overall_ok = doctor_mod.run_doctor(args.org, cfg)
    icons = {"ok": "✅", "warn": "⚠️ ", "fail": "❌"}
    _print("agentforce-probe doctor — org: %s" % (args.org or "(none)"))
    _print("")
    for c in checks:
        _print(f"{icons.get(c['status'], '?')} {c['name']:<22} {c['detail']}")
    _print("")
    _print("Overall: %s" % ("READY" if overall_ok else "BLOCKED (see ❌ above)"))
    return 0 if overall_ok else 1


# ── run ─────────────────────────────────────────────────────────────────────
def cmd_run(args):
    # Imports are local so `doctor` and `--help` work even if optional deps for a
    # given path are missing.
    from . import evidence as evidence_mod
    from . import scorer

    cfg = config_mod.Config()

    try:
        spec = scorer.load_spec(args.spec)
    except Exception as e:
        _err(f"spec error: {e}")
        return 2

    agent_name = args.agent or spec.get("subjectName")
    if not agent_name:
        _err("no agent name (pass --agent or set subjectName in the spec)")
        return 2

    judge_label = args.judge or config_mod.DEFAULT_JUDGE

    # ── offline: collect Claude Code verdicts (handoff step ③), no org call ──
    if getattr(args, "from_verdicts", None):
        return _run_from_verdicts(args, spec, agent_name, scorer, evidence_mod)

    # ── offline re-score: load an existing results JSON, no org call ──
    if getattr(args, "from_results", None):
        import json

        from . import sf_external

        raw = open(args.from_results, encoding="utf-8").read()
        start = raw.find("{")
        if start < 0:
            _err(f"no JSON object found in {args.from_results}")
            return 2
        obj = json.loads(raw[start:])
        results_obj = obj.get("result", obj)
        scored = sf_external.map_results_to_cases(results_obj, spec)
        agg, total_pass, total = scorer.aggregate(scored)
        pct = round(100 * total_pass / total) if total else 0
        _print(f"Agent: {agent_name}  ·  offline re-score from {args.from_results}")
        _print("")
        _print(
            f"Score: {total_pass}/{total} = {pct}%  ·  topic {agg['topic'][0]}/{agg['topic'][1]} · actions {agg['actions'][0]}/{agg['actions'][1]} · output {agg['output'][0]}/{agg['output'][1]}"
        )
        _print(rec_mod.render(scored))
        out_path = args.out or (f"{agent_name}-evidence.md")
        content = evidence_mod.render_evidence(
            agent_name=agent_name,
            org_alias=args.org,
            agent_type="ExternalCopilot (offline re-score)",
            path_label="Offline re-score of existing `sf agent test` results",
            results=scored,
            judge_label="Salesforce Testing Center (recorded)",
        )
        evidence_mod.write_evidence(out_path, content)
        _print(f"Evidence written: {out_path}")
        return 0

    # Resolve agent type from the org (unless forced offline).
    if args.dry_run and args.force_type:
        is_internal = args.force_type.lower() == "internal"
        meta = {
            "id": args.bot_id,
            "type": args.force_type,
            "is_internal": is_internal,
            "label": agent_name,
            "developer_name": agent_name,
        }
    else:
        from . import agent_meta

        try:
            meta = agent_meta.resolve_agent(args.org, agent_name)
        except Exception as e:
            _err(f"could not resolve agent metadata: {e}")
            return 3
        is_internal = meta["is_internal"]

    _print(
        "Agent: {}  ·  type: {}  ·  path: {}".format(
            agent_name,
            meta.get("type"),
            "InternalCopilot (Agent API)" if is_internal else "ExternalCopilot (sf agent test)",
        )
    )

    # ── dispatch ──
    try:
        if is_internal:
            outcome = _run_internal(args, cfg, spec, meta, judge_label, agent_name)
            # handoff mode wrote a task package and asked the user to run Claude
            # Code; it returns a special marker (the int return code to use) so
            # we skip scoring/evidence here.
            if isinstance(outcome, _HandoffEmitted):
                return outcome.code
            results = outcome
            path_label = "Headless Agent API (Client Credentials + JWT, bypassUser:false)"
        else:
            results = _run_external(args, spec, agent_name)
            path_label = "Salesforce Testing Center (`sf agent test`)"
            judge_label = "Salesforce Testing Center (built-in output_validation)"
    except Exception as e:
        _err(f"run failed: {e}")
        return 4

    # ── score summary ──
    agg, total_pass, total = scorer.aggregate(results)
    pct = round(100 * total_pass / total) if total else 0
    _print("")
    _print(
        f"Score: {total_pass}/{total} = {pct}%  ·  topic {agg['topic'][0]}/{agg['topic'][1]} · actions {agg['actions'][0]}/{agg['actions'][1]} · output {agg['output'][0]}/{agg['output'][1]}"
    )
    _print(rec_mod.render(results))

    # ── evidence ──
    out_path = args.out or (f"{agent_name}-evidence.md")
    content = evidence_mod.render_evidence(
        agent_name=agent_name,
        org_alias=args.org,
        agent_type=meta.get("type"),
        path_label=path_label,
        results=results,
        judge_label=judge_label,
    )
    evidence_mod.write_evidence(out_path, content)
    _print(f"Evidence written: {out_path}")
    return 0


class _HandoffEmitted:
    """Marker: handoff mode wrote a task package and exited (no scoring here)."""

    def __init__(self, code=0):
        self.code = code


def _run_internal(args, cfg, spec, meta, judge_label, agent_name):
    from . import judge as judge_mod
    from . import sf_internal, sfcli

    ck, cs = cfg.eca_credentials()
    if not (ck and cs):
        raise RuntimeError(
            "InternalCopilot path needs ECA consumer key + secret in .env "
            "(AGENTPROBE_SF_CONSUMER_KEY / AGENTPROBE_SF_CONSUMER_SECRET)"
        )
    bot_id = meta.get("id") or args.bot_id
    if not bot_id:
        raise RuntimeError("no BotDefinition Id resolved for the Internal path")

    provider, model = judge_mod.parse_judge(judge_label)

    if args.dry_run:
        raise RuntimeError(
            "--dry-run cannot exercise the live Agent API (needs org credentials + "
            "Einstein). Use `doctor` for local checks; run live without --dry-run."
        )

    instance_url = sfcli.get_org_instance_url(args.org)
    if not instance_url:
        raise RuntimeError("could not determine org instance URL")

    # ── handoff: replay the session, write the judge task package, then EXIT.
    #    No LLM is contacted. The developer grades with Claude Code, then runs
    #    `--from-verdicts` to collect the verdicts into evidence.
    if provider == "handoff":
        raw = sf_internal.run_session(
            spec=spec,
            instance_url=instance_url,
            bot_definition_id=bot_id,
            consumer_key=ck,
            consumer_secret=cs,
            diag=lambda m: _print(f"  [diag] {m}"),
        )
        return _emit_handoff(args, spec, agent_name, raw)

    # ── API-key (or mock) judge: grade live in one step (unchanged path). ──
    judge_api_key = None
    if provider != "mock":
        judge_api_key = cfg.judge_api_key(provider)
        if not judge_api_key:
            raise RuntimeError(f"no API key for judge provider '{provider}'")

    return sf_internal.run_internal(
        spec=spec,
        instance_url=instance_url,
        bot_definition_id=bot_id,
        consumer_key=ck,
        consumer_secret=cs,
        judge_provider=provider,
        judge_model=model,
        judge_api_key=judge_api_key,
        diag=lambda m: _print(f"  [diag] {m}"),
    )


def _emit_handoff(args, spec, agent_name, raw_results):
    """Write <agent>-judge-task.json + <agent>-JUDGING.md and print next steps."""
    from . import judge as judge_mod

    task_path = judge_mod.task_package_path(args.out, agent_name)
    judging_path = judge_mod.judging_md_path(args.out, agent_name)
    verdicts_p = judge_mod.verdicts_path(args.out, agent_name)

    task = judge_mod.build_task_package(agent_name, args.org, spec, raw_results)
    judge_mod.write_task_package(task_path, task)
    judge_mod.write_judging_md(judging_path, judge_mod.render_judging_md(agent_name, task_path, verdicts_p))

    n = len(task["cases"])
    _print("")
    _print("Judge mode: handoff (Claude Code) — NO LLM was contacted.")
    _print(f"Replayed {n} case(s) through the Agent API; wrote the judging materials:")
    _print(f"  • task package : {task_path}")
    _print(f"  • instructions : {judging_path}")
    _print("")
    _print("Next steps:")
    _print("  1. Open Claude Code in this repo and paste the block from:")
    _print(f"       {judging_path}")
    _print("     (it tells Claude Code to read the task package and write verdicts).")
    _print("  2. Claude Code writes verdicts to:")
    _print(f"       {verdicts_p}")
    _print("  3. Collect them into evidence:")
    out_flag = (f" --out {args.out}") if args.out else ""
    _print(f"       python3 -m agentforce_probe run --org {args.org} --agent {agent_name} --spec {args.spec} \\")
    _print(f"         --from-verdicts {verdicts_p}{out_flag}")
    _print("")
    _print("No secrets are written to any of these files (test data only).")
    return _HandoffEmitted(0)


def _run_from_verdicts(args, spec, agent_name, scorer, evidence_mod):
    """Handoff step ③: read judge-task.json + verdicts.json, re-score, emit
    unified evidence. Offline — never calls the org or any LLM.
    """
    from . import judge as judge_mod

    # Locate the task package: explicit --judge-task, else sibling of verdicts.
    task_path = getattr(args, "judge_task", None)
    if not task_path:
        task_path = judge_mod.task_package_path(args.out, agent_name)
        import os as _os

        if not _os.path.exists(task_path):
            # fall back to sibling of the verdicts file
            sib = _os.path.join(_os.path.dirname(_os.path.abspath(args.from_verdicts)), f"{agent_name}-judge-task.json")
            if _os.path.exists(sib):
                task_path = sib

    try:
        task = judge_mod.load_task_package(task_path)
        verdicts_by_id, warnings = judge_mod.load_verdicts(args.from_verdicts)
    except judge_mod.HandoffError as e:
        _err(f"handoff error: {e}")
        return 2

    if task.get("schema") != judge_mod.TASK_SCHEMA:
        _err("WARN: task package schema is {!r}, expected {!r}".format(task.get("schema"), judge_mod.TASK_SCHEMA))
    for w in warnings:
        _err(f"WARN: {w}")

    task_cases = task["cases"]
    task_ids = [int(c["id"]) for c in task_cases]

    # validate coverage: every task case id must have a verdict
    missing = [cid for cid in task_ids if cid not in verdicts_by_id]
    if missing:
        _err("verdicts are missing case id(s): {}".format(", ".join(str(m) for m in missing)))
        _err("Every case in the task package must have a PASS/FAIL verdict.")
        return 2
    extra = [cid for cid in verdicts_by_id if cid not in set(task_ids)]
    if extra:
        _err(
            "WARN: verdicts contain unknown id(s) not in the task package: {}".format(", ".join(str(x) for x in extra))
        )

    # spec cases by 1-based number to recompute topic/actions filtering
    spec_cases = spec["testCases"]

    scored = []
    for tc in task_cases:
        cid = int(tc["id"])
        spec_case = spec_cases[cid - 1] if 1 <= cid <= len(spec_cases) else {"utterance": tc.get("utterance", "")}
        actual_topic = tc.get("actual_topic")
        actual_actions = tc.get("actual_actions") or []

        topic_pass = None
        if "expectedTopic" in spec_case and actual_topic is not None:
            topic_pass = str(actual_topic) == str(spec_case["expectedTopic"])
        actions_pass = None
        if "expectedActions" in spec_case:
            exp = set(spec_case.get("expectedActions") or [])
            actions_pass = exp.issubset(set(actual_actions))

        v = verdicts_by_id[cid]
        output_pass = v["verdict"] == "PASS"
        scored.append(
            scorer.score_case(
                spec_case,
                cid,
                topic_pass=topic_pass,
                actions_pass=actions_pass,
                output_pass=output_pass,
                response=tc.get("actual_response", ""),
                actual_topic=actual_topic,
                actual_actions=actual_actions,
                judge_reason=v["reason"],
            )
        )

    agg, total_pass, total = scorer.aggregate(scored)
    pct = round(100 * total_pass / total) if total else 0
    _print(f"Agent: {agent_name}  ·  collecting Claude Code verdicts from {args.from_verdicts}")
    _print("")
    _print(
        f"Score: {total_pass}/{total} = {pct}%  ·  topic {agg['topic'][0]}/{agg['topic'][1]} · actions {agg['actions'][0]}/{agg['actions'][1]} · output {agg['output'][0]}/{agg['output'][1]}"
    )
    _print(rec_mod.render(scored))

    out_path = args.out or (f"{agent_name}-evidence.md")
    content = evidence_mod.render_evidence(
        agent_name=agent_name,
        org_alias=args.org,
        agent_type="InternalCopilot (Agent API + Claude Code handoff judge)",
        path_label="Headless Agent API (recorded) + Claude Code file-handoff judge",
        results=scored,
        judge_label="Claude Code (file handoff)",
    )
    evidence_mod.write_evidence(out_path, content)
    _print(f"Evidence written: {out_path}")
    return 0


def _run_external(args, spec, agent_name):
    from . import sf_external

    if args.dry_run:
        raise RuntimeError(
            "--dry-run cannot exercise `sf agent test` (needs org + Einstein). "
            "Use `doctor` for local checks; run live without --dry-run."
        )
    return sf_external.run_external(agent_name, spec, args.spec, args.org)


# ── parser ────────────────────────────────────────────────────────────────────
def build_parser():
    p = argparse.ArgumentParser(
        prog="agentforce-probe",
        description="Local, privacy-first test runner + scorer for Salesforce "
        "Agentforce agents (ExternalCopilot via sf agent test; "
        "InternalCopilot via headless Agent API).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("run", help="run a test spec against an agent and score it")
    pr.add_argument("--org", required=True, help="Salesforce org alias")
    pr.add_argument("--agent", help="agent DeveloperName (defaults to spec subjectName)")
    pr.add_argument("--spec", required=True, help="path to test spec YAML")
    pr.add_argument(
        "--judge",
        help="judge for the Internal path. `handoff` "
        "(default — grade with Claude Code, no API "
        "key) or provider:model for a live LLM, e.g. "
        "openai:gpt-4o / anthropic:claude-3-5-sonnet-"
        "latest / mock",
    )
    pr.add_argument("--out", help="evidence markdown output path")
    pr.add_argument(
        "--from-results",
        dest="from_results",
        help="offline: score an existing `sf agent test results` JSON "
        "(or result.testCases payload) instead of calling the org. "
        "External-shape results only; no Einstein cost.",
    )
    pr.add_argument(
        "--from-verdicts",
        dest="from_verdicts",
        help="offline (handoff step ③): collect Claude Code verdicts. "
        "Reads the paired <agent>-judge-task.json + this verdicts "
        "JSON, applies the filtering rules, and emits evidence. "
        "No org/LLM call.",
    )
    pr.add_argument(
        "--judge-task",
        dest="judge_task",
        help="(with --from-verdicts) explicit path to the "
        "<agent>-judge-task.json package; defaults to the sibling "
        "of --out / the verdicts file.",
    )
    pr.add_argument("--dry-run", action="store_true", help="local validation only; refuses to call org/Einstein")
    pr.add_argument(
        "--force-type", choices=["internal", "external"], help="(dry-run aid) skip org lookup and assume this type"
    )
    pr.add_argument("--bot-id", help="(dry-run aid) BotDefinition Id for Internal path")
    pr.set_defaults(func=cmd_run)

    pd = sub.add_parser("doctor", help="preflight: sf CLI, org, ECA, secrets")
    pd.add_argument("--org", help="Salesforce org alias to probe")
    pd.set_defaults(func=cmd_doctor)

    ps = sub.add_parser(
        "scan",
        help="discover Agentforce test specs in a codebase (optionally run them all)",
    )
    ps.add_argument("--root", default=".", help="directory to scan (default: current dir)")
    ps.add_argument("--run", action="store_true", help="run every discovered spec (needs --org)")
    ps.add_argument("--org", help="Salesforce org alias (required with --run)")
    ps.add_argument("--judge", help="judge for the Internal path (same values as `run --judge`)")
    ps.set_defaults(func=cmd_scan)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
