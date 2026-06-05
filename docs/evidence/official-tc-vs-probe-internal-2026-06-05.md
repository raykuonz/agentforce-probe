# Evidence — Official Testing Center vs. agentforce-probe on an InternalCopilot agent

**Date:** 2026-06-05
**Org:** a live demo org (alias `demo-org`)
**Agent under test:** `IT_Helpdesk_Assistant` — `Type = InternalCopilot`, `BotUserId = null` (employee-facing)

This file records the raw commands and output behind the claims in the README's
[Why this exists](../../README.md#why-this-exists) section. Identifiers below are
fictional demo values; the behaviors, scores, and judge text are reproductions of
what we observed running this flow against a live org. No real customer, org, or
personal data is included.

---

## 1. Confirm the agent is InternalCopilot

```
$ sf data query -q "SELECT Id, DeveloperName, MasterLabel, Type, BotUserId FROM BotDefinition" --target-org demo-org
```
```
DEVELOPERNAME           MASTERLABEL            TYPE             BOTUSERID
Support_Concierge       Support Concierge      ExternalCopilot  005...QAO
Billing_Assistant       Billing Assistant      ExternalCopilot  005...QAO
IT_Helpdesk_Assistant   IT Helpdesk Assistant  InternalCopilot  null
```

`IT_Helpdesk_Assistant` is the internal/employee agent: `Type = InternalCopilot`,
`BotUserId = null` (no Bot User to run-as).

---

## 2. The official Testing Center flow runs end-to-end on the internal agent

Minimal 1-utterance spec (`subjectName: IT_Helpdesk_Assistant`, utterance:
*"Summarize the open ticket history for asset A-1006 so I can plan the next
maintenance window."*).

```
$ sf agent test create --spec <spec> --api-name Internal_TC_Probe --target-org demo-org --json
=> status 0  (deployed AiEvaluationDefinition)

$ sf agent test run --api-name Internal_TC_Probe --target-org demo-org --json
=> status 0  {"status":"NEW","runId":"<runId>"}

$ sf agent test results --job-id <runId> --target-org demo-org --json
=> status 0, run status COMPLETED
```

So **creating, running, and fetching results for an InternalCopilot agent all
succeed.** The official judge fired with a real score:

```json
{
  "metricLabel": "output_validation",
  "result": "PASS",
  "score": 3,
  "metricExplainability": "The bot response provides a summary with specific figures
    and a recommendation. However, the expected response requires the bot to use real
    data and not invent figures. Since the bot's figures are likely fabricated and not
    verified against real data, this constitutes a partial alignment. ..."
}
```

**The judge flagged the figures as "likely fabricated" and still returned PASS / score 3.**

The same run also returned `topic_assertion: FAILURE` with `actualValue = agent_router`
(the real topic was not observable; the run reported the router topic).

---

## 3. The official run really invokes actions and touches data (it is not pure simulation)

A control test with a deliberately nonexistent asset:

```
utterance: "Summarize the open ticket history for asset Z9X-NONEXISTENT-7777 ..."
generatedResponse: "No record matched 'asset Z9X-NONEXISTENT-7777'. Please provide a more
  specific identifier so I can summarize its history ..."
invokedActions: [summarize_by_lookup]
output_validation: PASS / score 5
  ("correctly informs the user that no record matches ... aligning with the expected
   response that nothing should be invented")
```

For a nonexistent identifier the agent invoked the lookup action, found nothing,
and said so — it did **not** invent a record or figures. This confirms the
official run executes real action lookups against real data; it is not a hollow
simulation.

---

## 4. Independent headless path (agentforce-probe) cross-checks the same record

Same agent, same asset A-1006, via the headless Agent API path
(Client Credentials + JWT, `bypassUser: false`):

```
$ agentforce-probe run --org demo-org --spec <spec> --bot-id <0Xx...> --judge mock --allow-mock-evidence --out <evidence.md>
  [diag] minted token: segments=3 len=1736 (JWT ok)
  [diag] agent api host: https://test.api.salesforce.com
  [diag] session started: <sessionId>
  [diag] case 1 replayed (response len=183)
```

The headless real session returned the same underlying figures for A-1006 that
the official run did. The two independent paths agree on the data — which is
exactly the point of having a second path: you can confirm whether a reported
figure is real instead of trusting a single, lenient judge.

> Note: `--judge mock` only checks "response present" and is **not** a real pass
> rate. It is used here solely to capture the raw agent response text for the
> cross-check.

---

## Conclusion (what we measured)

On this live org, official Testing Center **can** test an InternalCopilot agent:
create / run / results all succeed, real actions fire, real data is returned.
Its weaknesses are **judge leniency** (PASS / 3 on a response it itself called
"likely fabricated") and **routing unobservability** (topic reported as
`agent_router`). `agentforce-probe` addresses these with a strict multi-axis
judge and an independent second path for cross-checking.

This describes what we measured in one org on one date — not a guarantee about
every org or Salesforce release.
