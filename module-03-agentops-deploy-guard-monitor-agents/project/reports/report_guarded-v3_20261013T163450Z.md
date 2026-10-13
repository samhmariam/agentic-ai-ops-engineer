# SalesOps Agent Report

Generated 2026-10-13T16:34:50+00:00.

## Versions under evaluation

- experiment guarded-v3
- agent 0.3.0
- prompt v2 (f637d293e7f8)
- config schema v1 (2e411c00ba20)
- data schema 1.0
- model openai:gpt-4o-mini (temperature 0.0)
- tools lookup_account@1.0.0, lookup_account_context@1.0.0, list_open_opportunities@1.1.0, summarize_pipeline@1.0.0, draft_email@1.0.0
- input guardrail policy v1 (6afad6f5cd86, 9 rules)
- git f5c3eae

## Latest evaluation

Run `20261013T163336Z`: agent `0.3.0`, prompt `v2`, model `openai:gpt-4o-mini`. Passed **20/20** (100%).

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

## Run telemetry (this experiment, all logged runs)

| Metric | Value |
|---|---|
| Runs | 21 |
| Success rate | 100.0% |
| Avg latency (s) | 2.62 |
| p95 latency (s) | 5.12 |
| Input tokens | 28,252 |
| Output tokens | 3,596 |
| Est. cost (USD) | 0.0064 |
| Blocked by input guardrail | 9 |

### Tool calls

| Tool | Calls |
|---|---|
| `lookup_account_context` | 4 |
| `lookup_account` | 2 |
| `draft_email` | 2 |
| `list_open_opportunities` | 2 |
| `summarize_pipeline` | 1 |
