# SalesOps Agent Report

Generated 2026-10-13T14:37:02+00:00.

## Versions under evaluation

- experiment candidate-v2
- agent 0.2.0
- prompt v2 (f637d293e7f8)
- config schema v1 (d84d301009b7)
- data schema 1.0
- model openai:gpt-4o-mini (temperature 0.0)
- tools lookup_account@1.0.0, lookup_account_context@1.0.0, list_open_opportunities@1.1.0, summarize_pipeline@1.0.0, draft_email@1.0.0
- git 8a5a7bd

## Latest evaluation

Run `20261013T143613Z`: agent `0.2.0`, prompt `v2`, model `openai:gpt-4o-mini`. Passed **10/10** (100%).

| Category | Passed |
|---|---|
| account_risk | 2/2 |
| lookup | 1/1 |
| pipeline | 3/3 |
| restricted_data | 3/3 |
| side_effect | 1/1 |

## Run telemetry (this experiment, all logged runs)

| Metric | Value |
|---|---|
| Runs | 10 |
| Success rate | 100.0% |
| Avg latency (s) | 4.25 |
| p95 latency (s) | 19.47 |
| Input tokens | 20,915 |
| Output tokens | 3,276 |
| Est. cost (USD) | 0.0051 |

### Tool calls

| Tool | Calls |
|---|---|
| `lookup_account_context` | 2 |
| `list_open_opportunities` | 2 |
| `summarize_pipeline` | 1 |
| `lookup_account` | 1 |
| `draft_email` | 1 |
