"""sfcli: subprocess wrapper + banner-tolerant JSON parsing.

No real `sf` binary is ever invoked. `subprocess.run` and `shutil.which` are
monkeypatched so the retry/error/parse paths are exercised deterministically.
"""

import subprocess

import pytest

from agentforce_probe import sfcli


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ── parse_json_lenient ────────────────────────────────────────────────────────
def test_parse_json_lenient_skips_banner():
    raw = 'Some human banner text\nWARNING: blah\n{"result": {"ok": true}}'
    obj = sfcli.parse_json_lenient(raw)
    assert obj == {"result": {"ok": True}}


def test_parse_json_lenient_picks_first_parseable_object():
    # A stray '{' that does not start valid JSON must be skipped.
    raw = 'prefix { not json } trailing {"a": 1}'
    obj = sfcli.parse_json_lenient(raw)
    assert obj == {"a": 1}


def test_parse_json_lenient_empty_raises():
    with pytest.raises(sfcli.SfError):
        sfcli.parse_json_lenient("")


def test_parse_json_lenient_no_object_raises():
    with pytest.raises(sfcli.SfError):
        sfcli.parse_json_lenient("no braces at all here")


# ── sf_available ──────────────────────────────────────────────────────────────
def test_sf_available_true(monkeypatch):
    monkeypatch.setattr(sfcli.shutil, "which", lambda _: "/usr/bin/sf")
    assert sfcli.sf_available() is True


def test_sf_available_false(monkeypatch):
    monkeypatch.setattr(sfcli.shutil, "which", lambda _: None)
    assert sfcli.sf_available() is False


# ── run_sf ────────────────────────────────────────────────────────────────────
def test_run_sf_raises_when_cli_missing(monkeypatch):
    monkeypatch.setattr(sfcli, "sf_available", lambda: False)
    with pytest.raises(sfcli.SfError, match="not installed"):
        sfcli.run_sf(["org", "display"])


def test_run_sf_success(monkeypatch):
    monkeypatch.setattr(sfcli, "sf_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(0, "ok"))
    proc = sfcli.run_sf(["org", "display"])
    assert proc.returncode == 0
    assert proc.stdout == "ok"


def test_run_sf_nonzero_with_check_raises(monkeypatch):
    monkeypatch.setattr(sfcli, "sf_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(1, "", "boom"))
    with pytest.raises(sfcli.SfError, match="rc=1"):
        sfcli.run_sf(["data", "query"], check=True)


def test_run_sf_nonzero_without_check_returns(monkeypatch):
    monkeypatch.setattr(sfcli, "sf_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(1, "", "boom"))
    proc = sfcli.run_sf(["data", "query"], check=False)
    assert proc.returncode == 1


# ── run_sf_json ───────────────────────────────────────────────────────────────
def test_run_sf_json_parses_stdout(monkeypatch):
    monkeypatch.setattr(sfcli, "sf_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(0, 'banner\n{"result": {"x": 1}}'))
    obj = sfcli.run_sf_json(["org", "display", "--json"])
    assert obj["result"]["x"] == 1


def test_run_sf_json_falls_back_to_stderr(monkeypatch):
    monkeypatch.setattr(sfcli, "sf_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(1, "garbage no json", '{"result": {"y": 2}}'))
    obj = sfcli.run_sf_json(["data", "query", "--json"])
    assert obj["result"]["y"] == 2


def test_run_sf_json_unparseable_raises(monkeypatch):
    monkeypatch.setattr(sfcli, "sf_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(1, "no json", "still no json"))
    with pytest.raises(sfcli.SfError, match="could not parse JSON"):
        sfcli.run_sf_json(["data", "query", "--json"])


# ── query_soql / get_org_instance_url ─────────────────────────────────────────
def test_query_soql_returns_records(monkeypatch):
    monkeypatch.setattr(sfcli, "run_sf_json", lambda *a, **k: {"result": {"records": [{"Id": "001"}]}})
    recs = sfcli.query_soql("myorg", "SELECT Id FROM Account")
    assert recs == [{"Id": "001"}]


def test_query_soql_empty_records(monkeypatch):
    monkeypatch.setattr(sfcli, "run_sf_json", lambda *a, **k: {"result": {}})
    assert sfcli.query_soql("myorg", "SELECT Id FROM Account") == []


def test_get_org_instance_url(monkeypatch):
    monkeypatch.setattr(
        sfcli, "run_sf_json", lambda *a, **k: {"result": {"instanceUrl": "https://example.my.salesforce.com"}}
    )
    assert sfcli.get_org_instance_url("myorg") == "https://example.my.salesforce.com"
