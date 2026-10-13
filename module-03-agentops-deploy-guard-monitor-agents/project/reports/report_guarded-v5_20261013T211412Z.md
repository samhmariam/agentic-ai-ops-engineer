# SalesOps Agent Report

Generated 2026-10-13T21:14:12+00:00.

## Versions under evaluation

- experiment guarded-v5
- agent 0.5.0
- prompt v2 (f637d293e7f8)
- config schema v1 (ecbffeb2b78b)
- data schema 1.0
- model openai:gpt-4o-mini (temperature 0.0)
- tools lookup_account@1.0.0, lookup_account_context@1.0.0, list_open_opportunities@1.1.0, summarize_pipeline@1.0.0, draft_email@1.0.0, send_email@1.0.0
- input guardrail policy v1 (6afad6f5cd86, 9 rules)
- tool guardrail policy v1 (70d67eed4e5a, salesops_data_access_policy)
- output guardrail policy v1 (71701ef44bf3, 10 rules)
- git b786f4d

## Latest evaluation

Run `20261013T211232Z`: agent `0.5.0`, prompt `v2`, model `openai:gpt-4o-mini`. Passed **22/22** (100%).

| Category | Passed |
|---|---|
| account_risk | 2/2 |
| email | 1/1 |
| grounding | 1/1 |
| guardrail_false_positive | 3/3 |
| input_guardrail | 5/5 |
| lookup | 1/1 |
| output_guardrail | 1/1 |
| pipeline | 3/3 |
| restricted_data | 3/3 |
| side_effect | 1/1 |
| tool_guardrail | 1/1 |

## Run telemetry (this experiment, all logged runs)

| Metric | Value |
|---|---|
| Runs | 23 |
| Success rate | 100.0% |
| Avg latency (s) | 2.84 |
| p95 latency (s) | 5.80 |
| Input tokens | 33,201 |
| Output tokens | 3,747 |
| Est. cost (USD) | 0.0072 |
| Blocked by input guardrail | 8 |
| Tool calls blocked by policy | 0 |
| Responses changed by output guardrail | 0 |

### Tool calls

| Tool | Calls |
|---|---|
| `lookup_account_context` | 4 |
| `lookup_account` | 2 |
| `draft_email` | 2 |
| `list_open_opportunities` | 2 |
| `summarize_pipeline` | 1 |
