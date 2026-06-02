"""scan.discover_specs / render_discovery + the `scan` CLI command."""

import textwrap

from agentforce_probe import cli, scan


def _write(p, body):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")


def test_discover_finds_named_spec(tmp_path):
    _write(tmp_path / "README.md", "# not yaml at all\n")  # exercises the non-yaml skip
    _write(
        tmp_path / "support-spec.yaml",
        """
        subjectName: Support
        testCases:
          - utterance: hi
            expectedOutcome: greets
        """,
    )
    specs = scan.discover_specs(str(tmp_path))
    assert len(specs) == 1
    assert specs[0]["agent"] == "Support"
    assert specs[0]["num_cases"] == 1
    assert specs[0]["has_internal_signals"] is False


def test_discover_finds_spec_in_hint_dir_without_name(tmp_path):
    _write(
        tmp_path / "agent-specs" / "anything.yaml",
        """
        subjectName: Ops
        testCases:
          - utterance: q
            expectedOutcome: o
            expectedTopic: T
        """,
    )
    specs = scan.discover_specs(str(tmp_path))
    assert len(specs) == 1
    assert specs[0]["agent"] == "Ops"
    assert specs[0]["has_internal_signals"] is True  # expectedTopic present


def test_discover_skips_non_spec_yaml(tmp_path):
    _write(tmp_path / "config.yaml", "name: not a spec\nvalue: 1\n")
    _write(tmp_path / "data-spec.yaml", "- a\n- b\n")  # list, not mapping
    _write(tmp_path / "empty-spec.yaml", "subjectName: X\ntestCases: []\n")  # empty cases
    assert scan.discover_specs(str(tmp_path)) == []


def test_discover_skips_excluded_dirs(tmp_path):
    _write(
        tmp_path / "node_modules" / "pkg-spec.yaml",
        "subjectName: X\ntestCases:\n  - utterance: q\n",
    )
    _write(
        tmp_path / ".venv" / "lib-spec.yaml",
        "subjectName: Y\ntestCases:\n  - utterance: q\n",
    )
    assert scan.discover_specs(str(tmp_path)) == []


def test_discover_handles_unparseable_yaml(tmp_path):
    _write(tmp_path / "broken-spec.yaml", "subjectName: X\n  bad: : indent\n: :\n")
    # malformed YAML must be skipped, not crash
    assert scan.discover_specs(str(tmp_path)) == []


def test_name_looks_like_spec_direct():
    assert scan._name_looks_like_spec("support-spec.yaml") is True
    assert scan._name_looks_like_spec("foo.spec.yml") is True
    assert scan._name_looks_like_spec("README.md") is False  # not yaml
    assert scan._name_looks_like_spec("config.yaml") is False  # yaml but no "spec"


def test_discover_skips_non_spec_yaml_inside_hint_dir(tmp_path):
    # a hint dir pulls in *.yaml by location, but content sniffing must still reject non-specs
    _write(tmp_path / "agent-specs" / "config.yaml", "name: not a spec\nvalue: 1\n")
    assert scan.discover_specs(str(tmp_path)) == []


def test_render_discovery_with_specs(tmp_path):
    _write(
        tmp_path / "a-spec.yaml",
        "subjectName: Support\ntestCases:\n  - utterance: q\n    expectedOutcome: o\n",
    )
    specs = scan.discover_specs(str(tmp_path))
    out = scan.render_discovery(specs, str(tmp_path))
    assert "found 1 spec" in out
    assert "agentforce-probe run --org <alias> --agent Support" in out


def test_render_discovery_empty():
    out = scan.render_discovery([], ".")
    assert "found 0 spec" in out
    assert "No Agentforce specs found" in out


def test_render_discovery_subjectname_missing(tmp_path):
    _write(tmp_path / "x-spec.yaml", "testCases:\n  - utterance: q\n")
    specs = scan.discover_specs(str(tmp_path))
    out = scan.render_discovery(specs, str(tmp_path))
    assert "(subjectName not set)" in out
    # no --agent flag when subjectName is missing
    assert "--agent" not in out.split("Run one with:")[1]


# ── scan CLI command ──────────────────────────────────────────────────────────
def test_cmd_scan_discovery_only(tmp_path, capsys):
    _write(tmp_path / "s-spec.yaml", "subjectName: S\ntestCases:\n  - utterance: q\n")
    rc = cli.main(["scan", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "found 1 spec" in out


def test_cmd_scan_run_without_org_errors(tmp_path, capsys):
    _write(tmp_path / "s-spec.yaml", "subjectName: S\ntestCases:\n  - utterance: q\n")
    rc = cli.main(["scan", "--root", str(tmp_path), "--run"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "needs --org" in err


def test_cmd_scan_run_no_specs_is_zero(tmp_path, capsys):
    rc = cli.main(["scan", "--root", str(tmp_path), "--run", "--org", "demo"])
    assert rc == 0


def test_cmd_scan_run_executes_each(tmp_path, capsys, monkeypatch):
    _write(
        tmp_path / "s-spec.yaml",
        "subjectName: Support\ntestCases:\n  - utterance: q\n    expectedOutcome: o\n",
    )
    # stub cmd_run so we don't touch an org; assert it's invoked per spec
    seen = []

    def fake_run(ns):
        seen.append(ns.spec)
        return 0

    monkeypatch.setattr(cli, "cmd_run", fake_run)
    rc = cli.main(["scan", "--root", str(tmp_path), "--run", "--org", "demo"])
    assert rc == 0
    assert len(seen) == 1
    assert seen[0].endswith("s-spec.yaml")


def test_cmd_scan_run_propagates_worst_code(tmp_path, monkeypatch):
    _write(tmp_path / "a-spec.yaml", "subjectName: A\ntestCases:\n  - utterance: q\n")
    _write(tmp_path / "b-spec.yaml", "subjectName: B\ntestCases:\n  - utterance: q\n")
    codes = iter([0, 4])
    monkeypatch.setattr(cli, "cmd_run", lambda ns: next(codes))
    rc = cli.main(["scan", "--root", str(tmp_path), "--run", "--org", "demo"])
    assert rc == 4  # worst of {0, 4}
