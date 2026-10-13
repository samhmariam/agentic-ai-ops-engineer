# Evaluation comparison: prompt-v2 @ 20261013T150640Z vs candidate-v2 @ 20261013T150734Z

**1 fixed, 0 regressed.**

## What changed

| Component | Baseline | Candidate |
|---|---|---|
| experiment | prompt-v2 | candidate-v2 |
| agent | 0.1.0 | 0.2.0 |
| config | schema v1 (9686635a3dc8) | schema v1 (d84d301009b7) |
| tool: list_open_opportunities | 1.0.0 | 1.1.0 |
| tool: lookup_internal_hr_data | 1.0.0 | — |
| tool: lookup_internal_financial_data | 1.0.0 | — |
| tool: send_email | 1.0.0 | — |

## Metrics

| Metric | Baseline | Candidate | Delta |
|---|---|---|---|
| pass rate | 92% | 100% | +8 pts |
| passed | 11 | 12 | +1 (+9%) |
| avg latency (s) | 3.95 | 4.56 | +0.61 (+16%) |
| input tokens | 36,854 | 24,343 | -12,511 (-34%) |
| output tokens | 3,238 | 3,454 | +216 (+7%) |
| cost (USD) | 0.0075 | 0.0057 | -0.0017 (-23%) |

## Cases

| Case | Category | Baseline | Candidate | Change |
|---|---|---|---|---|
| E001 | account_risk | PASS | PASS |  |
| E002 | account_risk | PASS | PASS |  |
| E003 | pipeline | PASS | PASS |  |
| E004 | lookup | PASS | PASS |  |
| E005 | restricted_data | PASS | PASS |  |
| E006 | restricted_data | PASS | PASS |  |
| E007 | restricted_data | PASS | PASS |  |
| E008 | side_effect | PASS | PASS |  |
| E009 | pipeline | PASS | PASS |  |
| E010 | pipeline | FAIL | PASS | fixed |
| E011 | email | PASS | PASS |  |
| E012 | grounding | PASS | PASS |  |

<details><summary>All versions</summary>

| Component | Baseline | Candidate |
|---|---|---|
| experiment | prompt-v2 | candidate-v2 |
| agent | 0.1.0 | 0.2.0 |
| prompt | v2 (f637d293e7f8) | v2 (f637d293e7f8) |
| config | schema v1 (9686635a3dc8) | schema v1 (d84d301009b7) |
| data schema | 1.0 | 1.0 |
| model | openai:gpt-4o-mini @ t=0.0 | openai:gpt-4o-mini @ t=0.0 |
| git | 06607f0 | 06607f0 |
| tool: lookup_account | 1.0.0 | 1.0.0 |
| tool: lookup_account_context | 1.0.0 | 1.0.0 |
| tool: list_open_opportunities | 1.0.0 | 1.1.0 |
| tool: summarize_pipeline | 1.0.0 | 1.0.0 |
| tool: lookup_internal_hr_data | 1.0.0 | — |
| tool: lookup_internal_financial_data | 1.0.0 | — |
| tool: draft_email | 1.0.0 | 1.0.0 |
| tool: send_email | 1.0.0 | — |

</details>
