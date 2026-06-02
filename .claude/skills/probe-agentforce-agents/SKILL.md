---
name: probe-agentforce-agents
description: Test Salesforce Agentforce agents (External + Internal Copilot) and score them into evidence using the agentforce-probe CLI. Use when asked to test, evaluate, QA, or score an Agentforce/Einstein Copilot agent, or when a repo contains agent test specs (testCases YAML).
---

# Probe Agentforce Agents

Drive the `agentforce-probe` CLI to run automated tests against Salesforce
Agentforce agents and produce scored evidence — fully local, privacy-first.

**Why this tool exists:** Salesforce's built-in Testing Center (`sf agent test`)
only tests **ExternalCopilot** (customer-facing) agents. It cannot test
**InternalCopilot** (employee-facing) agents. `agentforce-probe` covers both:
External via Testing Center, Internal via the headless Agent API
(ECA Client-Credentials → JWT → session), running each utterance and capturing
the real response.

## When to use

- "Test / evaluate / QA / score this Agentforce agent"
- "Run the agent test specs in this repo"
- A repo has `*-spec.yaml` files with a `testCases:` list
- You need an evidence report of agent behavior (pass/fail per utterance)

## Step 0 — make sure the CLI is installed (do this first, automatically)

Detect, then install only if missing. Do not ask the user — just check:

```bash
agentforce-probe --help >/dev/null 2>&1 && echo INSTALLED || echo MISSING
```

If `MISSING`, install it (prefer the published package; fall back to the local
checkout if you're inside the repo):

```bash
# preferred: from PyPI (once published)
pip install agentforce-probe  # or: uv tool install agentforce-probe

# fallback: editable install from a local checkout
pip install -e .              # run from the repo root
```

Re-verify with `agentforce-probe --help` before continuing. The CLI has three
commands: `scan`, `run`, `doctor`.

## Step 1 — discover specs (scan)

Point it at the repo root. `scan` finds every valid spec (a YAML mapping with a
`testCases:` list, named `*spec*.yaml` or under an `agent-specs/` dir) and tells
you how to run each:

```bash
agentforce-probe scan --root .
```

To discover **and** run them all in one shot (needs an org alias):

```bash
agentforce-probe scan --root . --run --org <alias>
```

## Step 2 — preflight (doctor)

Before a live run, confirm the environment is ready (sf CLI present, org
reachable, ECA configured for the Internal path, secrets loaded from a
gitignored `.env`):

```bash
agentforce-probe doctor --org <alias>
```

Fix anything marked ❌ before running. `doctor` never prints secrets.

## Step 3 — run a spec

```bash
agentforce-probe run --org <alias> --spec path/to/agent-spec.yaml --out evidence.md
```

- The CLI auto-detects the agent **type** from the org and picks the path:
  ExternalCopilot → `sf agent test`; InternalCopilot → headless Agent API.
- `--agent <DeveloperName>` overrides the spec's `subjectName`.
- Output: a score summary, **actionable recommendations**, and an evidence
  markdown file.

### The judge (Internal path) — default is the Claude Code handoff

Internal agents need an LLM to judge whether each response satisfies the
expected outcome. The **default** judge requires **no API key** — it uses a
file-handoff protocol with Claude Code (you):

1. `run` produces a **judge task package** `<Agent>-judge-task.json` plus a
   `<Agent>-JUDGING.md` instruction file.
2. **You (Claude Code)** read `<Agent>-JUDGING.md`, judge each case against its
   expected outcome, and write verdicts to `<Agent>-judge-verdicts.json` using
   the exact schema shown in JUDGING.md (one entry per case id:
   `{"id": N, "verdict": "PASS"|"FAIL", "reason": "..."}`).
3. Feed the verdicts back to produce final evidence:

```bash
agentforce-probe run --org <alias> --spec spec.yaml \
  --from-verdicts <Agent>-judge-verdicts.json --out evidence.md
```

Every case in the task package **must** get a verdict, or the collect step
fails. Re-read the actual agent responses before trusting any verdict — don't
rubber-stamp.

Optional live-LLM fallback (if the team has a key): `--judge openai:gpt-4o`,
`--judge anthropic:claude-3-5-sonnet-latest`, or `--judge mock` for smoke tests.

## Step 4 — read the recommendations and act

After scoring, the CLI prints prioritized recommendations. Translate them into
concrete fixes:

- **🔴 Empty agent response** → the agent isn't answering. Check it's active,
  the BotDefinition Id is right, and (Internal) the Agent API minted a real JWT.
  Run `doctor`.
- **🔴 Output assertions failing** → re-read the response vs the `expectedOutcome`.
  Vague or over-strict expectations cause false FAILs; tighten the wording in
  the spec or fix the agent's topic/instructions.
- **🔴 Everything failed (0%)** → almost always environment, not content: wrong
  org, wrong agent type, expired creds, judge misconfig. `doctor` first.
- **🟡 Topic routing mismatch** → the classifier routed elsewhere; tune the topic
  or correct the spec's `expectedTopic`.
- **🟡 Expected actions not invoked** → the topic's action wiring is off, or the
  utterance doesn't trigger the intent.

When a run scores low, propose the specific spec edits or agent-config changes
the recommendations point to, then offer to re-run.

## Spec format (quick reference)

```yaml
subjectName: Support_Agent        # agent DeveloperName (or pass --agent)
testCases:
  - utterance: "where is my order?"
    expectedOutcome: "provides order status or asks for an order number"
    expectedTopic: Order_Management        # optional — scored only if present
    expectedActions: [LookupOrderStatus]   # optional — scored only if present
  - utterance: "reset my password"
    expectedOutcome: "guides the user through password reset"
```

Filtering rule: `topic` and `actions` are scored **only** when the case declares
`expectedTopic` / `expectedActions`. `output` (LLM-as-judge) is the primary
behavioral signal and is always scored.

## Privacy (hard rules)

- Fully local. The only network calls are to the target Salesforce org and
  (Internal path, live-LLM judge only) the configured judge API.
- Secrets come from a **gitignored** `.env` or environment variables and are
  **never** printed, logged, or written into evidence.
- Evidence files, judge task packages, and verdicts contain test data — they're
  gitignored by default. Don't commit them.

## Offline / no-org modes

- `--from-results <sf agent test results.json>` — re-score an existing External
  results payload, no org call, no Einstein cost.
- `--dry-run` — local validation only; refuses to call the org/Einstein.
