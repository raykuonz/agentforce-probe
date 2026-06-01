# Contributing to agentforce-probe

Thanks for your interest! This is a small, focused tool. Contributions that keep
it small, local, and privacy-first are very welcome.

## Ground rules

1. **Privacy-first, always.** Secrets (ECA consumer key/secret, judge API keys,
   tokens) must never be printed, logged, written to evidence, embedded as
   source literals, or passed through a shell. Token diagnostics may expose only
   length and JWT segment count — never bytes. If a change risks leaking a
   secret, it will not be merged.
2. **No customer / org / real test data.** Examples, fixtures, and tests must use
   only fictional, made-up data. Never commit a real org alias, customer name,
   agent transcript, or anything that identifies a real Salesforce org.
3. **Stay local.** The only network calls the tool makes are to the target
   Salesforce org and (optionally, Internal path) the configured judge LLM. No
   telemetry, no third-party calls.
4. **Stdlib-first.** The only runtime dependency is `pyyaml`. Please don't add
   dependencies without a strong reason.

## Dev setup

```bash
git clone https://github.com/OWNER/agentforce-probe
cd agentforce-probe
pip install -e ".[dev]"
```

## Before you open a PR

```bash
pytest            # all tests must pass (they are offline; no org/secret needed)
ruff check .      # lint must be clean
```

- Add tests for new behavior. The existing tests run with **no network and no
  secrets** (they inject fake sessions / mock judges) — keep it that way.
- If you touch the Agent API flow, update the "gotchas" section of the README if
  the behavior changes.
- Keep the unified evidence format stable, or bump it deliberately.

## Reporting bugs

Open an issue with: the command you ran (redact secrets/org names), what you
expected, what happened, and the relevant `doctor` output. Never paste tokens,
consumer secrets, or real customer data into an issue.

## License

By contributing you agree that your contributions are licensed under the
[MIT License](LICENSE).
