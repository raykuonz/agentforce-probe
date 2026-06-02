# Changelog

All notable changes to agentforce-probe are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.1.1] — 2026-06-03

### Fixed

- **Internal (employee-agent) session create no longer fails with HTTP 500 `EngineConfigLookupException`.** The session body's `instanceConfig.endpoint` was incorrectly set to the Agent API host; per Salesforce's Agent API troubleshooting guidance it must be the org's **My Domain URL**. `AgentApiSession` now takes a `my_domain_url` and uses it for that field (falling back to the API host when absent); the HTTP request still targets the Agent API host. Added regression tests locking the contract.

---

## [0.1.0] — 2026-06-02

### Added

#### Core test runner
- Run automated test suites against Salesforce Agentforce agents and score each utterance into a single evidence report
- **Two dispatch paths**, auto-selected per spec:
  - **External Copilot** → delegates to Salesforce Testing Center (`sf agent test`), which provides its own judging
  - **Internal Copilot** (employee-facing) → headless Agent API, the path the official CLI cannot reach today
- Internal path auth chain: External Client App (ECA) → OAuth Client-Credentials → JWT → session, with adaptive retry on token minting
- Per-utterance session runner captures the agent's real response for scoring

#### Judge layer
- **Claude Code file-handoff protocol (default)** — emits a self-contained judge task package (JSON) plus instructions for Claude Code / Cursor to fill verdicts against a fixed schema, then reads them back. Zero incremental cost, no API key required, reuses the team's existing agentic IDE
- **API-key judge (optional fallback)** — direct OpenAI / Anthropic LLM-as-judge when keys are available
- Strict JSON schemas for the task package and the returned verdicts

#### Scoring & evidence
- Assertion-filtering scorer: per-case topic / action / output checks with pass-fail rollup
- Deterministic, reproducible evidence Markdown render with per-case breakdown and overall percentage
- Safety-gate cases (agent correctly refuses out-of-scope / sensitive requests) scored as passes

#### Token hygiene & safety
- Secrets are never printed, logged, written to evidence, or embedded as source literals
- `token_shape()` diagnostics expose only length and JWT segment count — never the token bytes
- `doctor` pre-flight command validates config and environment before any live run

#### Packaging
- `pip install agentforce-probe` console script (`run` / `doctor` subcommands)
- src-layout package, stdlib-first — the only runtime dependency is `pyyaml`
- Fictional example specs (no customer, org, or real transcript data) for both External and Internal paths

[Unreleased]: https://github.com/raykuonz/agentforce-probe/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/raykuonz/agentforce-probe/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/raykuonz/agentforce-probe/releases/tag/v0.1.0
