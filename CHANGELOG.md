# Changelog

All notable changes to agentforce-probe are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.3.0] — 2026-06-05

### Added

- **Hybrid judge aggregation (conjunctive veto + compensatory mean).** The
  six-axis judge no longer reduces to a plain average. A critical axis below a
  floor — `factualAccuracy` or `instructionAdherence` under `0.3` — now **vetoes
  the case to FAIL** regardless of the other axes, so a fluent, well-structured
  answer that fabricates a figure or breaches a security gate can no longer
  average its way to a pass. Above the floor, the remaining axes composite as
  before against the `0.7` threshold.
- **Cohen's kappa in the calibration harness.** `eval/calibrate.py` now reports
  chance-corrected agreement (Cohen's κ) alongside raw agreement and the
  confusion matrix, because raw agreement alone is misleading on skewed label
  distributions.
- **Hand-labelled calibration set expanded to 30 cases** (`eval/calibration/cases.jsonl`),
  including deliberately fluent-but-fabricated and gate-breach traps that
  specifically exercise the veto.
- **Offline calibration regression in CI** (`tests/test_calibration_baseline.py`
  + `eval/calibration/judge-baseline.json`). A frozen snapshot of judge axis
  scores is re-checked on every commit — with no API key and no network — to
  prove the scoring logic still reproduces the human PASS/FAIL labels and keeps
  Cohen's κ above a floor. A change to the veto floor or threshold that breaks
  alignment with the calibration set now fails the build.

### Notes

- The calibration result (30/30 agreement, κ = 1.0, with all FAILs caught by the
  veto) is a *smoke-level* check on a small synthetic set — it shows the scoring
  logic aligns with human judgment on those cases, not a statistical accuracy
  guarantee for every agent or domain.

---

## [0.2.0] — 2026-06-04

### Added

- **Six-axis grounded judge.** The LLM-as-judge now scores six named axes — `factualAccuracy`, `completeness`, `citationQuality`, `answerStructure`, `instructionAdherence`, `answerRelevance` — each `0.0–1.0`, composited into a PASS/FAIL at threshold `0.7`, instead of a single binary verdict. This lets a confident, well-structured answer that *fabricates figures* fail on `factualAccuracy` even when it reads well. Verdicts schema bumped to `@2`; `@1` legacy verdicts are still readable.
- **Per-call cost estimate** printed before a live-judge run, so the call volume is visible up front.
- **Maintainer-only calibration harness** (`eval/`) to meta-evaluate the judge against synthetic triplets — optional, key-gated, and kept out of the published package.

### Changed

- **Mock judge is flagged as ungrounded and gated.** Its fake pass rate can no longer be mistaken for a real one: evidence written with a mock judge carries a banner and requires `--allow-mock-evidence`.
- **Cases without an `expectedOutcome` are no longer scored** on output (shown as `-`, excluded from the denominator), so empty rubrics don't skew the pass rate.

### Fixed

- **`--out` parent directories are now created before writing.** A nested output path (e.g. `docs/evidence/x.md`) previously crashed with `FileNotFoundError` *after* the Agent API replay had already run, wasting the calls. The evidence, task-package, and judging-instruction writers now create the parent directory first.

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

[Unreleased]: https://github.com/raykuonz/agentforce-probe/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/raykuonz/agentforce-probe/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/raykuonz/agentforce-probe/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/raykuonz/agentforce-probe/releases/tag/v0.1.0
