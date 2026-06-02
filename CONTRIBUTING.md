# Contributing to agentforce-probe

Thanks for taking the time to contribute.

## Ways to contribute

- **Bug reports** — open an issue with the bug report template
- **Feature requests** — open an issue with the feature request template
- **Pull requests** — fix bugs, add judge backends, improve docs

---

## Development setup

```bash
# Clone
git clone https://github.com/raykuonz/agentforce-probe
cd agentforce-probe

# Install with dev dependencies (uses lock file)
uv sync --extra dev

# Run the test suite
uv run pytest

# Check linting and formatting
uv run ruff check .
uv run ruff format --check .
```

Python 3.10+ required.

---

## Project layout

```
src/agentforce_probe/
  cli.py          # argparse entry point: run / doctor subcommands
  config.py       # .env / environment resolution (no secrets logged)
  doctor.py       # pre-flight environment validation
  sf_external.py  # External Copilot path → sf agent test (Testing Center)
  sf_internal.py  # Internal Copilot path → headless Agent API + judge
  agent_api.py    # ECA → Client-Credentials → JWT → session; token_shape() hygiene
  agent_meta.py   # agent metadata resolution
  judge.py        # Claude Code file-handoff protocol + API-key fallback
  scorer.py       # assertion-filtering scorer, spec loading
  evidence.py     # deterministic evidence Markdown render
  sfcli.py        # thin wrapper around the Salesforce CLI
examples/specs/   # fictional test specs (no customer/org/real data)
tests/            # pytest suite (offline, no live org required)
```

---

## Working on the test runner

- **Never commit real test data.** Examples, fixtures, and tests must use fictional agents, orgs, and transcripts. No customer names, org domains, real responses, or secrets — ever.
- **Secrets stay out of output.** Anything read from `.env` / environment must never be printed, logged, written to evidence, or embedded as a literal. Token diagnostics may expose only length and JWT segment count.
- **Both paths must dry-run offline.** Spec loading, path dispatch, and the Claude Code judge file-handoff are expected to work with no network access; new code should preserve that.

---

## Pull request checklist

- [ ] `uv run pytest` passes (all existing tests green)
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] New code has tests
- [ ] README updated if adding a new command, flag, or judge backend
- [ ] CHANGELOG.md updated under `[Unreleased]`
- [ ] No customer / org / real transcript data or secrets introduced anywhere

---

## Code style

- **Linter/formatter**: [ruff](https://docs.astral.sh/ruff/) is enforced in CI. Run `uv run ruff check .` and `uv run ruff format .` before opening a PR.
- Type hints on all public functions
- Docstrings on all public functions

---

## Reporting security issues

See [SECURITY.md](SECURITY.md).
