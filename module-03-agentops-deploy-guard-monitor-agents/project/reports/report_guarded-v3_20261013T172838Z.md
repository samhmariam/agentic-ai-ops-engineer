# SalesOps Agent Report

Generated 2026-10-13T17:28:38+00:00.

## Versions under evaluation

- experiment guarded-v3
- agent 0.3.0
- prompt v2 (f637d293e7f8)
- config schema v1 (fd5bb990ea9a)
- data schema 1.0
- model openai:gpt-4o-mini (temperature 0.0)
- tools lookup_account@1.0.0, lookup_account_context@1.0.0, list_open_opportunities@1.1.0, summarize_pipeline@1.0.0, draft_email@1.0.0
- input guardrail policy v1 (6afad6f5cd86, 9 rules)
- tool guardrail disabled
- git cabcb04

## Latest evaluation

Run `20261013T172535Z`: agent `0.3.0`, prompt `v2`, model `openai:gpt-4o-mini`. Passed **21/21** (100%).

| Category | Passed |
|---|---|
| account_risk | 2/2 |
| email | 1/1 |
| grounding | 1/1 |
| guardrail_false_positive | 3/3 |
| input_guardrail | 5/5 |
| lookup | 1/1 |
| pipeline | 3/3 |
| restricted_data | 3/3 |
| side_effect | 1/1 |
| tool_guardrail | 1/1 |

## Run telemetry (this experiment, all logged runs)

| Metric | Value |
|---|---|
| Runs | 42 |
| Success rate | 100.0% |
| Avg latency (s) | 3.25 |
| p95 latency (s) | 6.44 |
| Input tokens | 58,308 |
| Output tokens | 7,351 |
| Est. cost (USD) | 0.0132 |
| Blocked by input guardrail | 17 |
| Tool calls blocked by policy | 0 |

### Tool calls

| Tool | Calls |
|---|---|
| `lookup_account_context` | 8 |
| `draft_email` | 5 |
| `lookup_account` | 4 |
| `list_open_opportunities` | 4 |
| `summarize_pipeline` | 2 |
