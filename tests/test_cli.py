"""cli: argument routing + command dispatch with every I/O boundary mocked.

main(argv) is driven directly. agent_meta / sf_external / sf_internal / judge /
config / doctor are monkeypatched so no org, LLM, or secret is touched. Asserts
on return codes and on captured stdout/stderr.
"""

import json

import pytest

from agentforce_probe import cli


# ── parser ────────────────────────────────────────────────────────────────────
def test_build_parser_run_requires_org_and_spec():
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run"])  # missing required --org/--spec


def test_no_command_exits():
    with pytest.raises(SystemExit):
        cli.main([])


# ── doctor command ────────────────────────────────────────────────────────────
def test_cmd_doctor_ready(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.doctor_mod, "run_doctor", lambda org, cfg: ([{"name": "sf CLI", "status": "ok", "detail": "found"}], True)
    )
    rc = cli.main(["doctor", "--org", "myorg"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "READY" in out
    assert "sf CLI" in out


def test_cmd_doctor_blocked(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.doctor_mod,
        "run_doctor",
        lambda org, cfg: ([{"name": "sf CLI", "status": "fail", "detail": "missing"}], False),
    )
    rc = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "BLOCKED" in out


# ── run: spec errors ──────────────────────────────────────────────────────────
def test_run_bad_spec_returns_2(monkeypatch, capsys):
    # load_spec lives in scorer; patch it there to raise.
    from agentforce_probe import scorer

    monkeypatch.setattr(scorer, "load_spec", lambda p: (_ for _ in ()).throw(ValueError("boom")))
    rc = cli.main(["run", "--org", "o", "--spec", "missing.yaml"])
    assert rc == 2
    assert "spec error" in capsys.readouterr().err


def test_run_no_agent_name_returns_2(monkeypatch, capsys):
    from agentforce_probe import scorer

    monkeypatch.setattr(scorer, "load_spec", lambda p: {"testCases": [{"utterance": "q"}]})  # no subjectName
    rc = cli.main(["run", "--org", "o", "--spec", "s.yaml"])
    assert rc == 2
    assert "no agent name" in capsys.readouterr().err


# ── run: external dispatch ────────────────────────────────────────────────────
def test_run_external_path(monkeypatch, capsys, tmp_path):
    from agentforce_probe import agent_meta, scorer, sf_external

    monkeypatch.setattr(
        scorer,
        "load_spec",
        lambda p: {"subjectName": "Support", "testCases": [{"utterance": "q", "expectedOutcome": "o"}]},
    )
    monkeypatch.setattr(
        agent_meta, "resolve_agent", lambda org, name: {"id": "0Xx", "type": "ExternalCopilot", "is_internal": False}
    )
    scored = [
        {
            "number": 1,
            "utterance": "q",
            "topic": "-",
            "actions": "-",
            "output": "PASS",
            "response": "r",
            "expectedTopic": None,
            "expectedActions": None,
            "actualTopic": None,
            "actualActions": None,
            "judge_reason": None,
        }
    ]
    monkeypatch.setattr(sf_external, "run_external", lambda *a, **k: scored)
    out_path = tmp_path / "ev.md"
    rc = cli.main(["run", "--org", "o", "--spec", "s.yaml", "--out", str(out_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Score: 1/1 = 100%" in out
    assert out_path.exists()


def test_run_agent_meta_failure_returns_3(monkeypatch, capsys):
    from agentforce_probe import agent_meta, scorer

    monkeypatch.setattr(scorer, "load_spec", lambda p: {"subjectName": "X", "testCases": [{"utterance": "q"}]})
    monkeypatch.setattr(agent_meta, "resolve_agent", lambda org, name: (_ for _ in ()).throw(RuntimeError("no bot")))
    rc = cli.main(["run", "--org", "o", "--spec", "s.yaml"])
    assert rc == 3
    assert "could not resolve agent metadata" in capsys.readouterr().err


# ── run: offline --from-results ───────────────────────────────────────────────
def test_run_from_results_offline(monkeypatch, capsys, tmp_path):
    from agentforce_probe import scorer

    monkeypatch.setattr(
        scorer,
        "load_spec",
        lambda p: {"subjectName": "Support", "testCases": [{"utterance": "q", "expectedOutcome": "o"}]},
    )
    results = {
        "result": {
            "testCases": [
                {
                    "testNumber": 1,
                    "inputs": {"utterance": "q"},
                    "generatedData": {"generatedResponse": "hi"},
                    "testResults": [{"name": "output_validation", "result": "PASS"}],
                }
            ]
        }
    }
    rf = tmp_path / "results.json"
    rf.write_text("banner line\n" + json.dumps(results), encoding="utf-8")
    out_path = tmp_path / "ev.md"
    rc = cli.main(["run", "--org", "o", "--spec", "s.yaml", "--from-results", str(rf), "--out", str(out_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "offline re-score" in out
    assert out_path.exists()


def test_run_from_results_no_json_returns_2(monkeypatch, capsys, tmp_path):
    from agentforce_probe import scorer

    monkeypatch.setattr(scorer, "load_spec", lambda p: {"subjectName": "S", "testCases": [{"utterance": "q"}]})
    rf = tmp_path / "results.json"
    rf.write_text("no json here", encoding="utf-8")
    rc = cli.main(["run", "--org", "o", "--spec", "s.yaml", "--from-results", str(rf)])
    assert rc == 2
    assert "no JSON object" in capsys.readouterr().err


# ── run: internal dispatch via dry-run force-type (no org) ────────────────────
def test_run_internal_dry_run_refused(monkeypatch, capsys):
    from agentforce_probe import config as config_mod
    from agentforce_probe import scorer

    monkeypatch.setattr(
        scorer,
        "load_spec",
        lambda p: {"subjectName": "Help", "testCases": [{"utterance": "q", "expectedOutcome": "o"}]},
    )
    monkeypatch.setattr(config_mod.Config, "eca_credentials", lambda self: ("ck", "cs"))
    rc = cli.main(["run", "--org", "o", "--spec", "s.yaml", "--dry-run", "--force-type", "internal", "--bot-id", "0Xx"])
    assert rc == 4  # run failed (dry-run cannot exercise live Agent API)
    assert "dry-run" in capsys.readouterr().err.lower()


# ── run: handoff emission (internal, mocked session) ──────────────────────────
def test_run_internal_handoff_emits_task(monkeypatch, capsys, tmp_path):
    from agentforce_probe import agent_meta, scorer, sf_internal, sfcli
    from agentforce_probe import config as config_mod

    spec = {"subjectName": "Help", "testCases": [{"utterance": "reset my password", "expectedOutcome": "guides reset"}]}
    monkeypatch.setattr(scorer, "load_spec", lambda p: spec)
    monkeypatch.setattr(
        agent_meta, "resolve_agent", lambda org, name: {"id": "0XxBOT", "type": "InternalCopilot", "is_internal": True}
    )
    monkeypatch.setattr(config_mod.Config, "eca_credentials", lambda self: ("ck", "cs"))
    monkeypatch.setattr(sfcli, "get_org_instance_url", lambda org: "https://x.my.salesforce.com")
    raw = [
        {
            "number": 1,
            "utterance": "reset my password",
            "response": "Go to Setup > ...",
            "topic": "Account",
            "actions": [],
        }
    ]
    monkeypatch.setattr(sf_internal, "run_session", lambda **k: raw)
    out_path = tmp_path / "ev.md"
    rc = cli.main(["run", "--org", "o", "--spec", "s.yaml", "--out", str(out_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "handoff" in out.lower()
    # task package + judging md written next to --out
    assert (tmp_path / "Help-judge-task.json").exists()
    assert (tmp_path / "Help-JUDGING.md").exists()


# ── run: --from-verdicts collection ───────────────────────────────────────────
def test_run_from_verdicts(monkeypatch, capsys, tmp_path):
    from agentforce_probe import judge as judge_mod
    from agentforce_probe import scorer

    spec = {"subjectName": "Help", "testCases": [{"utterance": "reset my password", "expectedOutcome": "guides reset"}]}
    monkeypatch.setattr(scorer, "load_spec", lambda p: spec)
    # Build a real task package + verdicts on disk.
    task = judge_mod.build_task_package(
        "Help",
        "o",
        spec,
        [{"number": 1, "utterance": "reset my password", "response": "Go to Setup", "topic": "Account", "actions": []}],
    )
    task_path = tmp_path / "Help-judge-task.json"
    judge_mod.write_task_package(str(task_path), task)
    verdicts = {
        "schema": judge_mod.VERDICTS_SCHEMA,
        "agent": "Help",
        "verdicts": [{"id": 1, "verdict": "PASS", "reason": "ok"}],
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
    out = capsys.readouterr().out
    assert rc == 0
    assert "Score:" in out
    assert out_path.exists()


def test_run_from_verdicts_missing_verdict_returns_2(monkeypatch, capsys, tmp_path):
    from agentforce_probe import judge as judge_mod
    from agentforce_probe import scorer

    spec = {
        "subjectName": "Help",
        "testCases": [{"utterance": "a", "expectedOutcome": "x"}, {"utterance": "b", "expectedOutcome": "y"}],
    }
    monkeypatch.setattr(scorer, "load_spec", lambda p: spec)
    task = judge_mod.build_task_package(
        "Help",
        "o",
        spec,
        [
            {"number": 1, "utterance": "a", "response": "r1", "topic": None, "actions": []},
            {"number": 2, "utterance": "b", "response": "r2", "topic": None, "actions": []},
        ],
    )
    task_path = tmp_path / "Help-judge-task.json"
    judge_mod.write_task_package(str(task_path), task)
    verdicts = {
        "schema": judge_mod.VERDICTS_SCHEMA,
        "agent": "Help",
        "verdicts": [{"id": 1, "verdict": "PASS", "reason": "ok"}],
    }  # case 2 missing
    vpath = tmp_path / "Help-judge-verdicts.json"
    vpath.write_text(json.dumps(verdicts), encoding="utf-8")
    rc = cli.main(
        ["run", "--org", "o", "--spec", "s.yaml", "--from-verdicts", str(vpath), "--judge-task", str(task_path)]
    )
    assert rc == 2
    assert "missing case id" in capsys.readouterr().err
