# SalesOps Agent Report

Generated 2026-10-13T15:09:32+00:00.

## Versions under evaluation

- experiment candidate-v2
- agent 0.2.0
- prompt v2 (f637d293e7f8)
- config schema v1 (d84d301009b7)
- data schema 1.0
- model openai:gpt-4o-mini (temperature 0.0)
- tools lookup_account@1.0.0, lookup_account_context@1.0.0, list_open_opportunities@1.1.0, summarize_pipeline@1.0.0, draft_email@1.0.0
- git 06607f0

## Latest evaluation

Run `20261013T150734Z`: agent `0.2.0`, prompt `v2`, model `openai:gpt-4o-mini`. Passed **12/12** (100%).

| Category | Passed |
|---|---|
| account_risk | 2/2 |
| email | 1/1 |
| grounding | 1/1 |
| lookup | 1/1 |
| pipeline | 3/3 |
| restricted_data | 3/3 |
| side_effect | 1/1 |

## Run telemetry (this experiment, all logged runs)

| Metric | Value |
|---|---|
| Runs | 34 |
| Success rate | 100.0% |
| Avg latency (s) | 4.36 |
| p95 latency (s) | 20.35 |
| Input tokens | 69,601 |
| Output tokens | 10,180 |
| Est. cost (USD) | 0.0165 |

### Tool calls

| Tool | Calls |
|---|---|
| `lookup_account_context` | 6 |
| `list_open_opportunities` | 6 |
| `lookup_account` | 5 |
| `draft_email` | 5 |
| `summarize_pipeline` | 3 |
