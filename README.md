# agentforce-probe

**A local, privacy-first CLI to run automated tests against Salesforce
Agentforce agents — and score the results into evidence.**

> **TL;DR** — Salesforce's Testing Center *can* score both customer-facing and
> employee-facing agents — but in our live-org testing its built-in judge waved
> through a response it **itself flagged as likely fabricated**, and it can't
> show you which topic actually fired. `agentforce-probe` re-tests **both**
> agent types from one command with a **strict, multi-axis judge** and an
> **independent second path**, then hands you a single evidence report. It runs
> entirely on your machine, sends nothing to third parties, and needs **no API
> key** to get started.

### Do I need to set anything up? (the 30-second version)

| You're testing… | What you need | headless API / ECA? |
| --- | --- | --- |
| **ExternalCopilot** (customer/service agents) | just an `sf`-authenticated org | ❌ none — Testing Center judges for you, zero secrets |
| **InternalCopilot** (employee agents) | the above **+ a one-time External Client App** (consumer key/secret in `.env`) | ✅ yes — the independent headless path used to cross-check the official run |
| *Optional:* grade with a live LLM judge | an OpenAI/Anthropic API key | the default judge is a **no-key Claude Code handoff** |

So: **External agents work out of the box.** The only real setup is a one-time
ECA for the Internal path — and even then the judge needs no API key by default.
Full steps are in [Configure secrets](#configure-secrets-env).

`agentforce-probe` auto-detects the agent type and picks the right path:

- **ExternalCopilot** (customer/service agents) → drives
  `sf agent test create/run/results`. Salesforce **Testing Center** provides the
  LLM judge (`output_validation`) for you — no extra setup.
- **InternalCopilot** (employee agents) → **this is the tool's core value.**
  Testing Center *can* run employee agents, but its judge is a lenient 0–5
  rating and its routing is unobservable (see [Why this exists](#why-this-exists)).
  So `agentforce-probe` also walks an independent headless path —
  **External Client App → Client Credentials mint (JWT) → Agent API headless
  session → one message per utterance → a configurable LLM-as-judge** — letting
  you cross-check the official result with a strict, multi-axis score.

Both paths emit **one unified evidence markdown report** (per case: utterance /
topic / agent response / each assertion), using the same assertion-filtering
rules.

## Why this exists

Salesforce's built-in Testing Center (`sf agent test`) **can** test
**InternalCopilot** (employee) agents — we ran the full
`create → run → results` flow against a real internal agent in a live org and
it created the test, invoked the agent's actions, returned real data, and
scored the result. So the gap isn't *whether* it runs. It's *how it judges*,
and what it lets you see:

1. **The official judge is a loose 0–5 rating that passes fabrication
   through.** On one case it returned **PASS / score 3** while writing, in its
   own explanation:

   > *"the bot's figures are likely fabricated and not verified against real
   > data … this constitutes a partial alignment."*

   It flagged the doubt — and passed it anyway. A score that can't decide
   whether the data was real isn't a score you can ship behind.

2. **Routing is unobservable for internal agents.** Every internal-agent run
   reported topic `agent_router` instead of the topic that actually fired, so
   you can't assert on routing.

`agentforce-probe` addresses both. It grades each response with a **structured
multi-axis judge** — every axis scored *with a written reason*, including a
factual-accuracy axis that drives unsupported figures toward FAIL instead of a
hand-wavy "3". Critically, the judge is **not a plain average**: a critical axis
below a floor (a fabricated figure, a breached security gate) **vetoes** the
whole case to FAIL regardless of how polished the rest of the response is — a
fluent-but-fabricated answer can't buy its way to a pass. And it runs an
**independent second path** (a real headless Agent API session) so you can
cross-check what the official run reports rather than trust a single, lenient
source. One command, one evidence report, both agent types.

> All claims above are from our own runs against a live org on 2026-06-05; see
> [`docs/evidence/`](docs/evidence/) for the raw commands and output. We
> describe what *we measured*, not a guarantee about every org or release.

## Is the judge itself trustworthy?

A judge that catches the official scorer's mistakes is only useful if *it*
agrees with human judgment. So we keep a hand-labelled calibration set
([`eval/calibration/cases.jsonl`](eval/calibration/cases.jsonl), 30 synthetic
PASS/FAIL cases including deliberately fluent-but-fabricated traps) and measure
the judge against it.

On that set, an LLM judge (run via the no-API-key Claude Code handoff path)
scored each case independently — without seeing the human labels — and its
derived PASS/FAIL verdicts agreed with the human labels on **30/30 cases
(Cohen's κ = 1.0)**, with every one of the 17 FAILs caught by the
factual-accuracy / instruction-adherence veto. A frozen snapshot of those axis
scores is checked into [`eval/calibration/judge-baseline.json`](eval/calibration/judge-baseline.json)
and a **CI test re-verifies the alignment on every commit** (offline, no key) —
so a change to the veto floor or threshold that breaks agreement with the
calibration set turns the build red.

> This is a *smoke-level* calibration on a small synthetic set, not a
> statistical guarantee. It shows the scoring logic aligns with human judgment
> on these cases; it is not a claim of accuracy on every agent or domain. The
> live calibration harness ([`eval/calibrate.py`](eval/calibrate.py)) lets you
> re-run this against your own labelled cases with a real judge.

## Privacy

Everything runs on your machine. The **only** outbound network calls are:

1. to the target Salesforce org (`sf` CLI + the Agent API), and
2. **(InternalCopilot path only, and only if you opt into a live API-key
   judge)** to the judge LLM you configure.

No telemetry, no third parties. Secrets (ECA consumer key/secret, judge API key)
are read from a gitignored `.env` (or env vars), held in memory only, and are
**never** printed, logged, written to evidence, or passed through a shell. Token
diagnostics only ever expose length + JWT segment count — never bytes.

## Install

### Recommended: install the skill into your AI agent (one command)

If you work in an AI coding agent (Claude Code, Cursor, Codex, OpenCode…), the
fastest way to use this is to **install the bundled skill** — then just ask your
agent to "test my Agentforce agent" and it drives the tool for you. It even
installs the CLI itself on first use, so this is all you run:

```bash
npx skills add raykuonz/agentforce-probe
```

It'll let you pick which agent(s) to install into —
[50+ are supported](https://github.com/vercel-labs/skills#supported-agents)
(Claude Code, Cursor, Codex, OpenCode, …). Preview the skill first with
`npx skills add raykuonz/agentforce-probe --list`. No clone, no manual setup —
just `npx`.

**Then just ask your agent in plain language** — the skill triggers on requests like:

- *"Test my Agentforce agent `Support_Concierge` against `examples/specs/Support_Concierge-testSpec.yaml`"*
- *"QA / evaluate / score the IT Helpdesk agent in my org and give me an evidence report"*
- *"Run the agent test specs in this repo"*

The agent then handles the rest for you: it installs the CLI if needed, finds
your test specs, runs them against the org, and writes the scored evidence
report — no commands to memorize. (For the InternalCopilot path you'll still do
the one-time ECA setup in [Configure secrets](#configure-secrets-env); the agent
will tell you if it's missing.)

### Or: install the CLI directly

Prefer to run it yourself from the terminal? Install from
[PyPI](https://pypi.org/project/agentforce-probe/):

```bash
pip install agentforce-probe
```

This gives you the `agentforce-probe` command (the only runtime dependency is
`pyyaml`):

```bash
agentforce-probe --help
python3 -m agentforce_probe --help     # or run it as a module
```

To hack on it / track `main`, install from source instead:

```bash
git clone https://github.com/raykuonz/agentforce-probe
cd agentforce-probe
pip install -e .
```

## Maturity & limitations

Read this before you trust a score in anger. The tool is deliberately honest
about what has and hasn't been validated.

### What's verified

- **Logic layer — fully tested.** 207 unit tests, 100% line coverage across all
  modules. Spec loading, assertion filtering, scoring, evidence rendering, the
  judge contract, token-shape validation, and the Agent API error ladder are all
  exercised — with the network and the `sf` CLI mocked.

### What's not yet verified

- **100% coverage is not the same as "proven against a live org."** Every test
  mocks the network and `sf`. The genuine end-to-end paths — `sf agent test`
  against a real **External** agent, and ECA mint → JWT → live **Agent API**
  session against a real **Internal** agent — have **not** been re-run against a
  live Salesforce org in this open-source extraction. The InternalCopilot
  gotchas baked into the code (opaque-token 404, 412 config errors,
  `bypassUser` handling) were learned from real-world use, but treat **your
  first live run as the first true end-to-end validation** and sanity-check the
  evidence by hand.

### Known limitations

- **Internal path needs a one-time manual UI step.** The External Client App
  must have `isNamedUserJwtEnabled` **on**, or the mint returns an opaque token
  and the session endpoint 404s. The tool *detects and reports* this, but cannot
  fix it for you — see the ECA prerequisite below. This is the most common place
  to get stuck.
- **Agent-type detection relies on a live org query** (`BotDefinition.Type`). If
  your org's metadata shape differs, auto-detection can misfire; override with
  `--force-type internal|external` (and `--bot-id` for the Internal path).
- **The `handoff` judge is an LLM, so verdicts are not perfectly reproducible.**
  Two graders (or the same grader twice) may disagree on a borderline case. The
  score is a well-evidenced judgment, not a deterministic measurement — always
  read the captured agent responses, don't rubber-stamp.
- **Single-turn only.** Each utterance runs in its own fresh session; the tool
  does **not** test multi-turn context or memory.
- **`endSession` is best-effort** and silently ignores failures, so an
  unreachable org could leave a dangling session server-side (low risk, no
  effect on the score).
- **`--from-results` accepts External-shaped payloads only** (offline re-scoring
  of `sf agent test results`); there's no offline replay for the Internal path.

## Configure secrets (`.env`)

Only the **InternalCopilot** path needs secrets. Copy the template into the
directory you run `agentforce-probe` from and fill it in (the file is
gitignored):

```bash
cp .env.example .env
# then edit .env:
#   AGENTPROBE_SF_CONSUMER_KEY=...      (Internal path: ECA consumer key)
#   AGENTPROBE_SF_CONSUMER_SECRET=...   (Internal path: ECA consumer secret)
#   AGENTPROBE_ANTHROPIC_API_KEY=...    (only if you use a live API-key judge)
#   AGENTPROBE_OPENAI_API_KEY=...       (only if you use a live API-key judge)
```

Environment variables take precedence over `.env`. The ExternalCopilot path
needs **none** of these (Testing Center judges for you). You can also point at a
specific file with `AGENTPROBE_ENV_FILE=/path/to/.env`.

### Prerequisite for the Internal path — the External Client App

The InternalCopilot path needs an **External Client App (ECA)** configured for
the Client Credentials flow. To get its consumer key/secret:

1. **Setup → App Manager** (or **External Client App Manager**).
2. Find your ECA → row dropdown → **View / Manage Consumer Details** (you may be
   asked to verify your identity).
3. Copy the **Consumer Key** and **Consumer Secret** into `.env`.
4. Confirm the ECA has Client Credentials enabled, a Run-As user
   (`clientCredentialsFlowUser`), and **`isNamedUserJwtEnabled` ON** — otherwise
   the mint returns an *opaque* token instead of a JWT and the Agent API session
   endpoint 404s. (`agentforce-probe` detects this and tells you.)

That's the only step that requires the Salesforce UI. Everything else is CLI.

## Usage

### `doctor` — preflight (local + read-only)

```bash
agentforce-probe doctor --org my-org
```

Reports: is `sf` installed, does the org connect, are External Client Apps
present, are ECA secrets + judge keys configured, where is `.env`. Never spends
Einstein credits; secrets shown only as present/absent.

### Run an ExternalCopilot agent (Testing Center)

```bash
agentforce-probe run \
  --org my-org \
  --agent Support_Concierge \
  --spec examples/specs/Support_Concierge-testSpec.yaml \
  --out support_concierge-evidence.md
```

### Run an InternalCopilot agent (headless Agent API + judge)

```bash
agentforce-probe run \
  --org my-org \
  --agent IT_Helpdesk_Assistant \
  --spec examples/specs/IT_Helpdesk_Assistant-testSpec.yaml \
  --out it_helpdesk-evidence.md
  # --judge handoff is the default (grade with Claude Code, no API key)
```

`--judge` selects the Internal-path judge:

- **`handoff` (default)** — *no API key needed.* Grade with Claude Code via a
  file-handoff protocol. See [Judge via Claude Code](#judge-via-claude-code-no-api-key-needed).
- `openai:<model>` / `anthropic:<model>` — grade live in one step using a raw
  LLM API key from `.env`.
- `mock` — offline heuristic (no network), for dry runs / smoke tests.

> ⚠️ Running a real test (`sf agent test run` or a live Internal Agent API
> session) **spends Einstein credits**. `doctor`, `--dry-run`, `--from-results`,
> and `--from-verdicts` are all free / offline.

## Judge via Claude Code (no API key needed)

The InternalCopilot path needs an LLM to grade each agent response PASS/FAIL.
If your team has **Claude Code** (or a similar coding agent) open in the editor
but **no raw LLM API key**, use the default `handoff` judge — a three-step file
protocol where Claude Code *is* the judge runtime and `agentforce-probe` just
defines the contract. No secret ever leaves your machine; the handoff files
contain only test data.

**Step ① — produce the judge task package** (replays the agent; contacts no LLM):

```bash
agentforce-probe run \
  --org my-org --agent IT_Helpdesk_Assistant \
  --spec examples/specs/IT_Helpdesk_Assistant-testSpec.yaml \
  --out it_helpdesk-evidence.md            # --judge handoff is the default
```

This mints the token, opens the headless Agent API session, sends every
utterance, captures `response` / `topic` / `invokedActions`, and writes two
files next to `--out`, then exits:

- `IT_Helpdesk_Assistant-judge-task.json` — the grading materials (schema below).
- `IT_Helpdesk_Assistant-JUDGING.md` — a block you paste into Claude Code.

**Step ② — grade in Claude Code.** Open Claude Code in this repo and paste the
block from `*-JUDGING.md`. It instructs Claude Code to read the task package,
apply the rubric, and write `*-judge-verdicts.json` (verdict is strictly
`PASS`/`FAIL`, one entry per case id, no skips).

**Step ③ — collect the verdicts into evidence** (offline; no org/LLM call):

```bash
agentforce-probe run \
  --org my-org --agent IT_Helpdesk_Assistant \
  --spec examples/specs/IT_Helpdesk_Assistant-testSpec.yaml \
  --from-verdicts IT_Helpdesk_Assistant-judge-verdicts.json \
  --out it_helpdesk-evidence.md
```

`agentforce-probe` reads the verdicts back, aligns them to the task package by
`id`, recomputes topic/actions (from the recorded live values + the spec), uses
each verdict as the `output` signal, applies the **same** assertion-filtering
rules, and writes the unified evidence markdown. It validates that every case id
has a verdict (missing ids = error) and that each verdict is `PASS`/`FAIL`.

### Schemas

**`<agent>-judge-task.json`** (`agentforce-probe/judge-task@1`):

```json
{
  "schema": "agentforce-probe/judge-task@1",
  "agent": "IT_Helpdesk_Assistant", "org": "my-org",
  "rubric": "<strict-QA-grader rubric>",
  "instructions": "For each case, decide if actual_response satisfies expected_outcome. Write {id,verdict,reason} for every case into the verdicts file. Do not skip any case.",
  "cases": [
    {"id": 1, "utterance": "...", "expected_outcome": "...",
     "actual_response": "...", "actual_topic": "...", "actual_actions": ["..."]}
  ]
}
```

**`<agent>-judge-verdicts.json`** (`agentforce-probe/judge-verdicts@1`):

```json
{"schema": "agentforce-probe/judge-verdicts@1",
 "agent": "IT_Helpdesk_Assistant",
 "verdicts": [{"id": 1, "verdict": "PASS", "reason": "..."}]}
```

All handoff files (`*-judge-task.json`, `*-judge-verdicts.json`, `*-JUDGING.md`)
are run artifacts (test data) and are gitignored.

## Test spec format (`*.yaml`)

```yaml
name: "My Suite"
subjectType: AGENT
subjectName: IT_Helpdesk_Assistant
testCases:
  - utterance: "..."             # required
    expectedTopic: account_help  # optional (= subagent / topic name)
    expectedActions: [foo, bar]  # optional (Level-2 invocation names)
    expectedOutcome: "..."       # used by the judge; almost always present
```

See [`examples/specs/`](examples/specs/) for complete, runnable examples (using
fictional demo data).

## Scoring rules (assertion filtering)

- `topic_assertion` is scored **only** if the case declares `expectedTopic`.
- `actions_assertion` is scored **only** if the case declares `expectedActions`.
- `output_validation` (LLM-as-judge) is the **primary** behavioral signal and is
  scored for every case.
- A dimension with no declared expectation renders as `-` and never counts
  against the score.

> A `topic` FAIL with an `output` PASS usually means the agent behaved correctly
> even though single-turn routing picked a semantically adjacent topic — look at
> the primary `output` signal first.

## Module layout

| file | responsibility |
|---|---|
| `cli.py` | argparse entrypoint; dispatches `run` / `doctor` |
| `config.py` | reads secrets from `.env` / env; never exposes values |
| `doctor.py` | local + read-only preflight checks |
| `agent_meta.py` | resolves `BotDefinition.Type`/Id (Internal vs External) |
| `sf_external.py` | ExternalCopilot path via `sf agent test` |
| `agent_api.py` | InternalCopilot mint + headless Agent API (urllib, token-safe) |
| `sf_internal.py` | Internal path orchestration (session → judge → score) |
| `judge.py` | configurable judge: `handoff` (default) + live `openai`/`anthropic`/`mock` |
| `scorer.py` | spec loading + assertion-filtering scorer |
| `evidence.py` | unified evidence markdown generator |
| `sfcli.py` | `sf` CLI wrapper + banner-tolerant JSON parsing |

## InternalCopilot Agent API — gotchas baked in

These are battle-tested; the code enforces them so you don't re-learn them:

1. **Mint:** `grant_type=client_credentials` → `{instance}/services/oauth2/token`;
   read `access_token` **and** `api_instance_url`.
2. **Token must be a JWT** (~1700 chars, 3 dot segments). An opaque token → 404 →
   `isNamedUserJwtEnabled` is off. The tool refuses to proceed on an opaque token.
3. **Host = `api_instance_url`** from the mint response (sandbox/scratch =
   `https://test.api.salesforce.com`). Never hardcoded.
4. **Session:** `POST .../einstein/ai-agent/v1/agents/{0Xx...}/sessions` with
   `bypassUser:false` (true → 400 "Invalid user ID"). Run-as = the ECA's
   `clientCredentialsFlowUser`; no `userId` in the body.
5. **Message:** `POST .../sessions/{id}/messages` with
   `{"message":{"sequenceId":N,"type":"Text","text":"..."}}`, N increments.
6. **Error ladder:** 404 empty = wrong host / opaque token; 400 "Invalid user ID"
   = use `bypassUser:false`; 412 "Invalid Config" = auth OK but planner config
   broken (usually an action missing its `inputs` block).
7. **Bearer hygiene:** the auth header is built at runtime from an in-memory
   variable (never a source literal, never `echo`'d) to dodge both shell-quoting
   and log-redaction traps.

## Development

```bash
pip install -e ".[dev]"
pre-commit install   # gate every commit/push on the same checks CI runs
pytest               # run the test suite (pure logic; no network, no secrets)
ruff check .         # lint
```

### Pre-commit / pre-push gate

The repo ships a [`pre-commit`](https://pre-commit.com) config with `local`
hooks (no external hook repos, works offline). After `pre-commit install`:

- **on every commit** — a privacy/hygiene scan (`scripts/check-secrets.sh`:
  no secrets, JWTs, org IDs, customer data, agent footprints, or run artifacts)
  plus `ruff check` and `ruff format --check`.
- **on every push** — the full `pytest` suite with the 100% coverage gate.

So a commit that would leak a secret, or a push that would break a test or drop
coverage, is blocked locally before it ever reaches GitHub. CI re-runs the same
checks, so green-local means green-pipeline.

## License

[MIT](LICENSE).
