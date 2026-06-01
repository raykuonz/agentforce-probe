"""Thin wrapper around the `sf` CLI + banner-tolerant JSON parsing.

`sf agent test results` (and some other commands) prepend a human banner before
the JSON body, so we never json.loads() the whole stdout — we scan for the first
brace that yields a parseable object.
"""

import json
import re
import shutil
import subprocess


class SfError(RuntimeError):
    pass


def sf_available():
    """True if the `sf` CLI is on PATH."""
    return shutil.which("sf") is not None


def parse_json_lenient(raw):
    """Find the first '{' offset that parses into a dict. Tolerates banners."""
    if not raw:
        raise SfError("empty output, nothing to parse")
    for m in re.finditer(r"\{", raw):
        s = m.start()
        try:
            obj = json.loads(raw[s:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    raise SfError("no parseable JSON object found in output")


def run_sf(args, timeout=300, check=True):
    """Run `sf <args>` and return CompletedProcess. args is a list (no shell)."""
    if not sf_available():
        raise SfError("the `sf` CLI is not installed or not on PATH")
    cmd = ["sf"] + list(args)
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        # surface stderr but keep it short
        err = (proc.stderr or proc.stdout or "").strip()
        raise SfError(f"`sf {' '.join(args)}` failed (rc={proc.returncode}): {err[:500]}")
    return proc


def run_sf_json(args, timeout=300):
    """Run an sf command expected to emit JSON (with --json) and parse leniently."""
    proc = run_sf(args, timeout=timeout, check=False)
    raw = proc.stdout or ""
    try:
        return parse_json_lenient(raw)
    except SfError:
        # Fall back to stderr in case CLI routed JSON there, else re-raise w/ context
        try:
            return parse_json_lenient(proc.stderr or "")
        except SfError:
            raise SfError(
                f"could not parse JSON from `sf {' '.join(args)}` "
                f"(rc={proc.returncode}); first 300 chars: {raw[:300]!r}"
            )


def query_soql(org, soql, timeout=120):
    """Run a SOQL query via `sf data query --json` and return list of records."""
    obj = run_sf_json(
        ["data", "query", "--query", soql, "--target-org", org, "--json"],
        timeout=timeout,
    )
    result = obj.get("result", obj)
    return result.get("records", []) or []


def get_org_instance_url(org, timeout=60):
    """Return the org's instanceUrl via `sf org display --json`."""
    obj = run_sf_json(["org", "display", "--target-org", org, "--json"], timeout=timeout)
    result = obj.get("result", obj)
    return result.get("instanceUrl")
