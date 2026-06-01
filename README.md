# agentforce-probe

**A local, privacy-first CLI to run automated tests against Salesforce
Agentforce agents — and score the results into evidence.**

`agentforce-probe` auto-detects the agent type and picks the right path:

- **ExternalCopilot** (customer/service agents) → drives
  `sf agent test create/run/results`. Salesforce **Testing Center** provides the
  LLM judge (`output_validation`) for you — no extra setup.
- **InternalCopilot** (employee agents) → **this is the tool's core value.**
  Testing Center *cannot* run employee agents, so `agentforce-probe` walks the
  headless path instead: **External Client App → Client Credentials mint (JWT) →
  Agent API headless session → one message per utterance → a configurable
  LLM-as-judge** scores each response.

Both paths emit **one unified evidence markdown report** (per case: utterance /
topic / agent response / each assertion), using the same assertion-filtering
rules.

## Why this exists

Salesforce's built-in Testing Center (`sf agent test`) only runs
**ExternalCopilot** agents — the customer-facing ones that have a Bot User to
impersonate. **InternalCopilot** (employee/internal) agents have no run-as Bot
User, so the Testing Center judge never fires and you simply cannot get an
automated test score for them through the supported tooling.

That's a real product gap. `agentforce-probe` closes it: for Internal agents it
bypasses the Testing Center and drives the **headless Agent API** directly,
replaying each utterance through a real session and grading the responses with
an LLM-as-judge. One command, one evidence report, both agent types.

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

From source (until published to PyPI):

```bash
git clone https://github.com/raykuonz/agentforce-probe
cd agentforce-probe
pip install -e .
```

This installs the `agentforce-probe` console command. You can also run it as a
module:

```bash
agentforce-probe --help
python3 -m agentforce_probe --help
```

The only runtime dependency is `pyyaml`.

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
pytest            # run the test suite (pure logic; no network, no secrets)
ruff check .      # lint
```

## License

[MIT](LICENSE).
