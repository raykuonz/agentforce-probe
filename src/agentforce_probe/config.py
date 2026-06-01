"""Config + secret loading for agentforce-probe.

Secrets are read from (in priority order):
  1. process environment variables
  2. a .env file next to the package (gitignored)

Secrets are NEVER printed, logged, or written to evidence files. The only thing
this module ever exposes about a secret is whether it is *present* and (for
diagnostics) its length / shape — never its value.
"""
import os

# ── secret names (env var keys) ──────────────────────────────────────────────
# Salesforce External Client App (Client Credentials flow) for the Internal path.
ECA_CONSUMER_KEY = "AGENTPROBE_SF_CONSUMER_KEY"
ECA_CONSUMER_SECRET = "AGENTPROBE_SF_CONSUMER_SECRET"

# Judge LLM API keys (provider-specific). Only the one matching --judge is needed.
JUDGE_KEY_ENV = {
    "openai": "AGENTPROBE_OPENAI_API_KEY",
    "anthropic": "AGENTPROBE_ANTHROPIC_API_KEY",
}

# Default judge if --judge not supplied. `handoff` (Claude Code file-handoff)
# is the default for the Internal path because the target teams have Claude Code
# open in their editor but no raw LLM API key. Users with a key can still pass
# --judge openai:gpt-4o / anthropic:... to grade in one live step.
DEFAULT_JUDGE = "handoff"


def _env_path():
    """Locate the .env file.

    Priority:
      1. AGENTPROBE_ENV_FILE (explicit override), if set.
      2. .env in the current working directory (where you run the command —
         this is the normal place to put it).
      3. .env one directory above the installed package (covers a flat,
         non-src checkout where the package sits at the repo root).

    Returns the first path that exists; if none exist, returns the cwd/.env
    path (so diagnostics point at the place you most likely meant).
    """
    override = os.environ.get("AGENTPROBE_ENV_FILE")
    if override:
        return override

    cwd_env = os.path.join(os.getcwd(), ".env")
    here = os.path.dirname(os.path.abspath(__file__))
    pkg_parent_env = os.path.join(os.path.dirname(here), ".env")

    for candidate in (cwd_env, pkg_parent_env):
        if os.path.exists(candidate):
            return candidate
    return cwd_env


def _parse_env_file(path):
    """Minimal .env parser: KEY=VALUE per line, supports quotes and # comments."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            out[key] = val
    return out


class Config:
    """Lazy secret accessor. env vars win over .env file."""

    def __init__(self):
        self._file = _parse_env_file(_env_path())

    def get(self, key, default=None):
        if key in os.environ and os.environ[key] != "":
            return os.environ[key]
        if key in self._file and self._file[key] != "":
            return self._file[key]
        return default

    def has(self, key):
        return self.get(key) is not None

    # ── convenience accessors ────────────────────────────────────────────────
    def eca_credentials(self):
        """Returns (consumer_key, consumer_secret) or (None, None)."""
        return self.get(ECA_CONSUMER_KEY), self.get(ECA_CONSUMER_SECRET)

    def judge_api_key(self, provider):
        env_key = JUDGE_KEY_ENV.get(provider)
        if not env_key:
            return None
        return self.get(env_key)

    def env_file_path(self):
        return _env_path()

    def env_file_exists(self):
        return os.path.exists(_env_path())
