# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Scope

agentforce-probe runs **locally** and is **privacy-first by design**. It talks to two kinds of endpoints, and only when you explicitly configure them:

- **Salesforce Testing Center** via the Salesforce CLI (`sf agent test`) for the External Copilot path
- **Salesforce Agent API** (headless) for the Internal Copilot path, authenticated with your own External Client App credentials

When no credentials are configured, the tool runs fully offline (spec loading, dry-run dispatch, and the Claude Code judge file-handoff all work with no network access).

Security-relevant areas:

- **Secrets** — consumer key/secret and any API keys are read from environment variables or a local `.env`. They are **never** printed, logged, written into evidence files, or embedded as source literals. Token diagnostics (`token_shape()`) expose only length and JWT segment count, never the token bytes.
- **Evidence output** — generated evidence Markdown contains the utterances you supplied and the agent's real responses. Treat it with the same sensitivity as your test data; do not commit evidence for production agents to a public repo.
- **Judge handoff package** — the Claude Code judge task package contains the utterances and agent responses to be judged. It is written locally; review it before sharing.
- **Network** — outbound calls go only to the Salesforce endpoints you configure (your org's My Domain / Agent API) and, if you opt into the API-key judge, to your chosen LLM provider. No telemetry, no other outbound calls.

## Reporting a vulnerability

**Do not open a public issue for security vulnerabilities.**

Please report security issues using [GitHub's private vulnerability reporting](https://github.com/raykuo/agentforce-probe/security/advisories/new).

Include:
- A description of the issue and its impact
- Steps to reproduce or a minimal proof-of-concept
- Affected versions

You can expect an acknowledgement within **72 hours** and a resolution or mitigation plan within **14 days** for confirmed issues. We will credit you in the release notes unless you prefer to remain anonymous.
