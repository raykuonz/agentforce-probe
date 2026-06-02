"""doctor.run_doctor: preflight checks.

sfcli + Config are monkeypatched so checks resolve deterministically with no org
and no secrets. Covers the all-green ready path, the sf-missing blocked path, and
mixed warnings.
"""

from agentforce_probe import doctor


class _Cfg:
    def __init__(self, ck=None, cs=None, openai=None, anthropic=None, env_exists=False):
        self._ck, self._cs = ck, cs
        self._openai, self._anthropic = openai, anthropic
        self._env_exists = env_exists

    def eca_credentials(self):
        return self._ck, self._cs

    def judge_api_key(self, provider):
        return {"openai": self._openai, "anthropic": self._anthropic}.get(provider)

    def env_file_exists(self):
        return self._env_exists

    def env_file_path(self):
        return "/tmp/.env"


def test_doctor_sf_missing_is_blocked(monkeypatch):
    monkeypatch.setattr(doctor.sfcli, "sf_available", lambda: False)
    checks, ok = doctor.run_doctor(None, _Cfg())
    assert ok is False
    sf_check = next(c for c in checks if c["name"] == "sf CLI")
    assert sf_check["status"] == "fail"


def test_doctor_ready_path(monkeypatch):
    monkeypatch.setattr(doctor.sfcli, "sf_available", lambda: True)
    monkeypatch.setattr(doctor.sfcli, "get_org_instance_url", lambda org: "https://x.my.salesforce.com")
    monkeypatch.setattr(doctor.sfcli, "query_soql", lambda org, soql, **k: [{"MasterLabel": "ECA One"}])
    cfg = _Cfg(ck="k", cs="s", openai="sk-x", env_exists=True)
    checks, ok = doctor.run_doctor("myorg", cfg)
    assert ok is True
    names = {c["name"]: c["status"] for c in checks}
    assert names["org connection"] == "ok"
    assert names["ECA secrets"] == "ok"
    assert names["judge API key"] == "ok"
    assert names[".env file"] == "ok"


def test_doctor_org_unreachable_is_fail(monkeypatch):
    monkeypatch.setattr(doctor.sfcli, "sf_available", lambda: True)

    def boom(org):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(doctor.sfcli, "get_org_instance_url", boom)
    checks, ok = doctor.run_doctor("myorg", _Cfg())
    assert ok is False
    org_check = next(c for c in checks if c["name"] == "org connection")
    assert org_check["status"] == "fail"


def test_doctor_no_org_warns_not_blocks(monkeypatch):
    monkeypatch.setattr(doctor.sfcli, "sf_available", lambda: True)
    checks, ok = doctor.run_doctor(None, _Cfg())
    assert ok is True  # warnings don't block
    org_check = next(c for c in checks if c["name"] == "org connection")
    assert org_check["status"] == "warn"


def test_doctor_partial_eca_secret_warns(monkeypatch):
    monkeypatch.setattr(doctor.sfcli, "sf_available", lambda: True)
    cfg = _Cfg(ck="only-key", cs=None)
    checks, ok = doctor.run_doctor(None, cfg)
    eca = next(c for c in checks if c["name"] == "ECA secrets")
    assert eca["status"] == "warn"
    assert "only one" in eca["detail"]


def test_doctor_no_eca_apps_found_warns(monkeypatch):
    monkeypatch.setattr(doctor.sfcli, "sf_available", lambda: True)
    monkeypatch.setattr(doctor.sfcli, "get_org_instance_url", lambda org: "https://x.my.salesforce.com")
    monkeypatch.setattr(doctor.sfcli, "query_soql", lambda org, soql, **k: [])
    checks, ok = doctor.run_doctor("myorg", _Cfg())
    eca_apps = next(c for c in checks if c["name"] == "External Client Apps")
    assert eca_apps["status"] == "warn"
