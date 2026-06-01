"""Preflight checks (`agentforce-probe doctor`).

All checks are LOCAL or read-only org probes. None spend Einstein credits.
Secrets are reported only as present/absent — never printed.
"""

from . import config as config_mod
from . import sfcli

OK = "ok"
WARN = "warn"
FAIL = "fail"


def _check(name, status, detail):
    return {"name": name, "status": status, "detail": detail}


def run_doctor(org, cfg=None):
    """Return (list_of_checks, overall_ok: bool)."""
    cfg = cfg or config_mod.Config()
    checks = []

    # 1. sf CLI present
    if sfcli.sf_available():
        checks.append(_check("sf CLI", OK, "found on PATH"))
        sf_ok = True
    else:
        checks.append(_check("sf CLI", FAIL, "not found on PATH — install Salesforce CLI"))
        sf_ok = False

    # 2. org reachable
    instance_url = None
    if sf_ok and org:
        try:
            instance_url = sfcli.get_org_instance_url(org)
            if instance_url:
                checks.append(_check("org connection", OK, f"connected to {instance_url}"))
            else:
                checks.append(_check("org connection", WARN, "org display returned no instanceUrl"))
        except Exception as e:
            checks.append(_check("org connection", FAIL, f"could not reach org '{org}': {str(e)[:160]}"))
    elif not org:
        checks.append(_check("org connection", WARN, "no --org provided; skipped"))

    # 3. ECA / Client Credentials presence (best-effort SOQL)
    if sf_ok and org and instance_url:
        try:
            recs = sfcli.query_soql(
                org, "SELECT Id, DeveloperName, MasterLabel FROM ExternalClientApplication LIMIT 50"
            )
            if recs:
                labels = ", ".join(r.get("MasterLabel") or r.get("DeveloperName", "?") for r in recs[:5])
                checks.append(_check("External Client Apps", OK, f"{len(recs)} found (e.g. {labels})"))
            else:
                checks.append(_check("External Client Apps", WARN, "none found — Internal (Agent API) path needs one"))
        except Exception as e:
            checks.append(
                _check("External Client Apps", WARN, f"could not query (may lack object access): {str(e)[:120]}")
            )

    # 4. secrets configured (presence only — values NEVER shown)
    ck, cs = cfg.eca_credentials()
    if ck and cs:
        checks.append(_check("ECA secrets", OK, "consumer key + secret present (Internal path ready)"))
    elif ck or cs:
        checks.append(
            _check("ECA secrets", WARN, "only one of consumer key/secret set — both required for Internal path")
        )
    else:
        checks.append(_check("ECA secrets", WARN, "not set (only needed for InternalCopilot agents)"))

    # 5. judge keys (presence only)
    judge_keys = []
    for provider in ("openai", "anthropic"):
        if cfg.judge_api_key(provider):
            judge_keys.append(provider)
    if judge_keys:
        checks.append(_check("judge API key", OK, "configured: {}".format(", ".join(judge_keys))))
    else:
        checks.append(
            _check("judge API key", WARN, "none set (needed for InternalCopilot scoring; use mock for dry runs)")
        )

    # 6. .env location info
    if cfg.env_file_exists():
        checks.append(_check(".env file", OK, f"present at {cfg.env_file_path()}"))
    else:
        checks.append(_check(".env file", WARN, f"absent ({cfg.env_file_path()}) — using env vars only"))

    overall_ok = all(c["status"] != FAIL for c in checks)
    return checks, overall_ok
