# RealThor v0.8 — Debugging

Listing Supply Intelligence agent for the Ciudaty PropTech. Adds durable state persistence and run replay: every invocation checkpoints its state to `state.db` keyed by `run_id`, and `realthor replay --run-id <id>` reconstructs a past run's execution context — input, active prompt/dataset version, tool trajectory, intermediate values, and final answer — long after the process has exited.

---

## Setup

```bash
uv sync
cp .env.example .env   # set LLM_PROVIDER + its key (Vocareum by default)
```

---

## What changed from the previous version

RealThor v0.8 makes runs reproducible on top of the v0.7 monitoring system:

- **`replay.py`** (student deliverable): `build_checkpointer`, `load_run`, `reconstruct_context`. Reads persisted checkpoints through the `SqliteSaver` API and cross-references `logs/runs.jsonl` — no model, no API key, no dataset load.
- **`app.py`**: the checkpointer is upgraded from `InMemorySaver` to a durable **`SqliteSaver`**, and every `analyze`/`chat` run is keyed by `thread_id = run_id`, so a run's state survives the process. New **`replay`** subcommand.
- **`monitor.py`**: `RunRecord` gains `prompt_version` and `dataset_version` (defaulted) so the versions active during a run are persisted for reconstruction.
- **`config.yaml`**: new `debug.state_db` path; prompt bumped to `system_prompt_v8.md`; version `0.8.0`.
- **5 debugging regression scenarios** added to the eval suite (90 total).

---

## Main usage

**`analyze`** / **`chat`** — unchanged interface, now every run is checkpointed and prints its `run_id`.

```bash
uv run realthor chat -u analyst_002 -m "Should we acquire through iBuyer in north for 3-bedroom houses?"
# → ... Run ID: 3f9a...  (replay with: realthor replay --run-id 3f9a...)
```

**`replay`** — reconstruct a past run from its persisted state.

```bash
uv run realthor replay --run-id 3f9a...
# Replay of run 3f9a...
#   state restored : True
#   input          : Should we acquire through iBuyer in north for 3-bedroom houses?
#   prompt version : system_prompt_v8.md
#   dataset version: 0.8.0
#   tool trajectory: get_demand_score → get_supply_snapshot → recommend_channel
#   intermediate values: ...
#   final output   : ...
```

A failure that won't reproduce on rerun can still be inspected, because the original *run* is restored from disk rather than re-rolled.

---

## Architecture

```
CLI (app.py)
    ↓
build_checkpointer (replay.py) → SqliteSaver(state.db)   # durable, keyed by run_id
    ↓
build_main_agent (agents.py, checkpointer=...)
    ├── 15 bespoke tools (tools.py)
    ├── analyze_data tool (wraps analyst sub-agent)
    └── middleware (guardrails.py) + HITL (make_hitl_policy)
    ↓
_log_run (app.py) — appends RunRecord (incl. prompt/dataset version) to logs/runs.jsonl
    ↓
realthor replay --run-id <id>
    → load_run (checkpointer.list) + reconstruct_context (+ cross-ref runs.jsonl)
    → ReplayContext report
```

---

## Project structure

```
realthor/
├── src/realthor/
│   ├── app.py          # CLI (analyze + chat + report + replay)
│   ├── agents.py       # build_analyst_agent + build_main_agent (unchanged)
│   ├── replay.py       # build_checkpointer, load_run, reconstruct_context (new)
│   ├── monitor.py      # RunRecord (+prompt/dataset version), metrics, report
│   ├── policies.py     # PolicyDecision + evaluate_channel_policy
│   ├── guardrails.py   # 3 guardrail layers + make_hitl_policy
│   ├── sandbox.py      # validate_code + run_sandboxed
│   ├── config.py       # config/path utilities
│   └── tools.py        # 15 bespoke tools + make_execute_python_tool
├── tests/
│   ├── fixtures/
│   │   ├── state.db                # committed replay fixture (offline)
│   │   ├── make_replay_fixture.py  # regenerates state.db, model-free
│   │   ├── replay_runs.jsonl       # matching log row
│   │   └── sample_runs.jsonl
│   ├── test_replay.py              # 7 unit tests
│   ├── test_monitor.py             # 9 unit tests
│   ├── test_data_integrity.py      # 18 pre-provided, never modify
│   ├── test_config.py / test_guardrails.py / test_policies.py
│   └── test_sandbox.py / test_tools.py
├── evaluation/
│   ├── eval_scenarios.csv          # 90 scenarios, never hand-edit
│   └── run_eval.py
├── data/                           # 9 CSVs
├── data_forge/
├── logs/runs.jsonl                 # appended by every analyze/chat invocation
├── reports/                        # monitoring_report.{md,json,html}
├── prompts/system_prompt_v8.md
├── config.yaml
├── ops.sh
└── pyproject.toml
```

---

## How to verify

```bash
sh ops.sh
```

Expected output:

```
=== Running unit tests ===
... 81 passed

=== Checking data integrity ===
18 passed

=== Running evaluation ===
Running 10/90 scenarios (sampled evenly by type)...
10/10 scenarios passed
All scenarios passed.

=== Building container ===
[+] Building ...

=== Running deployed agent ===
Identity: analyst_001 (analyst)
[agent output]

All checks passed.
```

To reconstruct a real run end-to-end:

```bash
uv run realthor chat -u analyst_002 -m "Should we acquire through iBuyer in north?"
uv run realthor replay --run-id <printed run id>
```

---

## Local vs Deployed

```bash
# Local
uv run realthor replay --run-id <run id>

# Deployed (Docker — local only, not available in Udacity Workspace)
docker compose run --rm realthor replay --run-id <run id>
```

Same interface, same flags. Only the runtime changes.

---

## Docker Reference

### Inspect

```bash
docker images
docker ps -a
docker system df
```

### Clean up

```bash
docker system prune
docker compose down --rmi all
```

### Interactive shell

```bash
docker compose run --rm -it realthor sh
```

### Secrets

| Environment | Injection mechanism |
|---|---|
| Local | `env_file: .env` in `compose.yaml` |
| Kubernetes | `secretKeyRef` in pod spec |
| AWS ECS | Secrets Manager ARN in task definition |
| HashiCorp Vault | Vault agent sidecar |

### Tagging images

```bash
GIT_SHA=$(git rev-parse --short HEAD)
docker build -t realthor:$GIT_SHA -t realthor:latest .
```

---

## Commit

```bash
git add author/modules/08_debugging/exercises/solution/
git commit -m "feat: add replay.py with SqliteSaver state persistence and run reconstruction"
```
