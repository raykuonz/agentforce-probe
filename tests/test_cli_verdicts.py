"""cli _run_from_verdicts filtering branches + internal preflight errors."""

import json

from agentforce_probe import cli


def test_from_verdicts_recomputes_topic_actions(monkeypatch, capsys, tmp_path):
    """spec declares expectedTopic + expectedActions; the task package carries
    actual_topic/actual_actions, so the from-verdicts path recomputes the
    topic/actions filtering (cli.py lines ~330-336)."""
    from agentforce_probe import judge as judge_mod
    from agentforce_probe import scorer

    spec = {
        "subjectName": "Help",
        "testCases": [
            {
                "utterance": "track order",
                "expectedOutcome": "status",
                "expectedTopic": "Orders",
                "expectedActions": ["LookupOrder"],
            }
        ],
    }
    monkeypatch.setattr(scorer, "load_spec", lambda p: spec)
    raw = [
        {
            "number": 1,
            "utterance": "track order",
            "response": "ships tmrw",
            "topic": "Orders",
            "actions": ["LookupOrder"],
        }
    ]
    task = judge_mod.build_task_package("Help", "o", spec, raw)
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
    # 1 output + 1 topic + 1 actions all PASS = 3/3
    assert "Score: 3/3 = 100%" in out
    md = out_path.read_text(encoding="utf-8")
    assert "topic: **PASS**" in md
    assert "actions: **PASS**" in md


def test_from_verdicts_sibling_task_fallback(monkeypatch, capsys, tmp_path):
    """No --judge-task and no --out: the task package is found as a sibling of
    the verdicts file (cli.py lines ~287-291)."""
    from agentforce_probe import judge as judge_mod
    from agentforce_probe import scorer

    spec = {"subjectName": "Help", "testCases": [{"utterance": "q", "expectedOutcome": "o"}]}
    monkeypatch.setattr(scorer, "load_spec", lambda p: spec)
    monkeypatch.chdir(tmp_path)  # so the cwd-based default task path misses, forcing sibling fallback
    raw = [{"number": 1, "utterance": "q", "response": "r", "topic": None, "actions": []}]
    task = judge_mod.build_task_package("Help", "o", spec, raw)
    subdir = tmp_path / "out"
    subdir.mkdir()
    task_path = subdir / "Help-judge-task.json"
    judge_mod.write_task_package(str(task_path), task)
    verdicts = {
        "schema": judge_mod.VERDICTS_SCHEMA,
        "agent": "Help",
        "verdicts": [{"id": 1, "verdict": "PASS", "reason": "ok"}],
    }
    vpath = subdir / "Help-judge-verdicts.json"
    vpath.write_text(json.dumps(verdicts), encoding="utf-8")
    rc = cli.main(["run", "--org", "o", "--spec", "s.yaml", "--from-verdicts", str(vpath)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Score:" in out


def test_run_internal_no_bot_id_fails(monkeypatch, capsys):
    """Internal path, resolved meta has no id and no --bot-id -> RuntimeError (cli ~193)."""
    from agentforce_probe import agent_meta, scorer
    from agentforce_probe import config as config_mod

    spec = {"subjectName": "Help", "testCases": [{"utterance": "q", "expectedOutcome": "o"}]}
    monkeypatch.setattr(scorer, "load_spec", lambda p: spec)
    monkeypatch.setattr(
        agent_meta, "resolve_agent", lambda org, name: {"id": None, "type": "InternalCopilot", "is_internal": True}
    )
    monkeypatch.setattr(config_mod.Config, "eca_credentials", lambda self: ("ck", "cs"))
    rc = cli.main(["run", "--org", "o", "--spec", "s.yaml"])
    assert rc == 4
    assert "no BotDefinition Id" in capsys.readouterr().err


def test_from_verdicts_skips_output_when_no_expected_outcome(monkeypatch, capsys, tmp_path):
    """Task case with empty expected_outcome: verdict is accepted but output stays '-'."""
    from agentforce_probe import judge as judge_mod
    from agentforce_probe import scorer

    spec = {
        "subjectName": "Help",
        "testCases": [
            {"utterance": "q1", "expectedOutcome": "grounded expectation"},
            {"utterance": "q2"},  # no expectedOutcome
        ],
    }
    monkeypatch.setattr(scorer, "load_spec", lambda p: spec)
    raw = [
        {"number": 1, "utterance": "q1", "response": "r1", "topic": None, "actions": []},
        {"number": 2, "utterance": "q2", "response": "r2", "topic": None, "actions": []},
    ]
    task = judge_mod.build_task_package("Help", "o", spec, raw)
    task_path = tmp_path / "Help-judge-task.json"
    judge_mod.write_task_package(str(task_path), task)
    verdicts = {
        "schema": judge_mod.VERDICTS_SCHEMA,
        "agent": "Help",
        "verdicts": [
            {"id": 1, "verdict": "PASS", "reason": "ok"},
            {"id": 2, "verdict": "PASS", "reason": "ok"},
        ],
    }
    vpath = tmp_path / "Help-judge-verdicts.json"
    vpath.write_text(json.dumps(verdicts), encoding="utf-8")
    out_path = tmp_path / "ev.md"
    rc = cli.main(
        [
            "run", "--org", "o", "--spec", "s.yaml",
            "--from-verdicts", str(vpath),
            "--judge-task", str(task_path),
            "--out", str(out_path),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    # output denominator is 1 (only the case with expectedOutcome)
    assert "output 1/1" in captured.out
    # a WARN line appears for the skipped case
    assert "output not scored" in captured.err


def test_run_internal_no_instance_url_fails(monkeypatch, capsys):
    """Internal path, org instance URL not resolvable -> RuntimeError (cli ~205)."""
    from agentforce_probe import agent_meta, scorer, sfcli
    from agentforce_probe import config as config_mod

    spec = {"subjectName": "Help", "testCases": [{"utterance": "q", "expectedOutcome": "o"}]}
    monkeypatch.setattr(scorer, "load_spec", lambda p: spec)
    monkeypatch.setattr(
        agent_meta, "resolve_agent", lambda org, name: {"id": "0XxBOT", "type": "InternalCopilot", "is_internal": True}
    )
    monkeypatch.setattr(config_mod.Config, "eca_credentials", lambda self: ("ck", "cs"))
    monkeypatch.setattr(sfcli, "get_org_instance_url", lambda org: None)
    rc = cli.main(["run", "--org", "o", "--spec", "s.yaml"])
    assert rc == 4
    assert "could not determine org instance URL" in capsys.readouterr().err
