# RealThor Monitoring Report

## Summary

| Metric | Value |
|---|---|
| Total runs | 34 |
| Successes | 30 |
| Failures | 4 |
| Success rate | 88.2% |
| Avg latency | 3.16s |
| p95 latency | 7.08s |
| Total cost | $0.0123 |
| Avg cost per run | $0.0004 |
| Guardrail blocks | 4 |
| HITL approvals | 2 |
| HITL rejections | 1 |

## Tool Call Distribution

| Tool | Calls |
|---|---|
| get_demand_signals | 17 |
| get_supply_snapshot | 16 |
| get_supply_opportunities | 10 |
| get_listing_velocity | 6 |
| submit_channel_recommendation | 3 |

## Common Failure Reasons

| Reason | Count |
|---|---|
| RateLimitError: rate limit exceeded | 2 |
| APITimeoutError: request timed out | 1 |
| APIConnectionError: connection reset | 1 |

## Key Signals

- p95 latency 7.08s exceeds 5s threshold
- failure rate 11.8% exceeds 10% threshold
