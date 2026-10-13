# RealThor v0.9 — Tracing

Listing Supply Intelligence agent for the Ciudaty PropTech. Adds **distributed tracing**:
every `analyze`/`chat` run can emit a Langfuse trace — the ordered tree of spans for each
model call and tool call — so you can see *how* an output was produced, not just what it was.
Logs (v0.7) tell you a run happened; replay (v0.8) restores its state; a trace shows the
reasoning path between input and output.

---

## Setup

```bash
uv sync
cp .env.example .env   # set LLM_PROVIDER + its key (Vocareum by default); for tracing add the LANGFUSE_* keys
```

---

## What changed from the previous version

RealThor v0.9 instruments the agent with tracing on top of the v0.8 replay system:

- **`tracing.py`** (student deliverable): `build_tracer`, `trace_callbacks`, `flush_tracer`.
  Returns a Langfuse `CallbackHandler` when tracing is enabled *and* the `LANGFUSE_*` env
  keys are present, `None` otherwise — the agent always runs, traced or not.
- **`app.py`**: `analyze`/`chat` gain a `--trace/--no-trace` flag (default from config). The
  tracer is spliced into the existing callback list — the same `config={"callbacks": [...]}`
  interface the usage-metadata callback already uses — and **flushed in `finally`** so a
  short-lived CLI process delivers its batched spans before exiting.
- **`config.yaml`**: new `tracing.enabled` toggle (the checked-in on/off switch; the host +
  keys are secrets that live in `.env`); prompt bumped to `system_prompt_v9.md`; version `0.9.0`.
- **`.env.example`**: adds `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`.
- **5 tracing regression scenarios** added to the eval suite (95 total) — confirming that
  attaching the tracing callback did not change agent behavior.

`agents.py` and `monitor.py` are unchanged: tracing is a pure observer attached at invoke
time, so no agent-construction or logging code had to move.

---

## Langfuse setup

The backend is chosen entirely by env vars — switching between local and cloud is a `.env`
change, not a code change.

**Local (self-hosted, default)** — run Langfuse's official Docker stack, pinned to a release:

```bash
git clone --branch v3.130.0 https://github.com/langfuse/langfuse.git
cd langfuse
docker compose up -d          # UI on http://localhost:3000 after ~2-3 min
```

Open `http://localhost:3000`, create a project, copy its public/secret keys into this
project's `.env`, and keep `LANGFUSE_HOST=http://localhost:3000`. This is a **separate**
stack from RealThor's own `compose.yaml` — run it with its own compose file.

**Cloud (alternative)** — create a free account at `cloud.langfuse.com`, copy the keys, and
set `LANGFUSE_HOST=https://us.cloud.langfuse.com` (or the EU host).

> Pin the Langfuse release tag you clone; the self-hosting stack evolves. Verify the current
> quickstart at https://langfuse.com/self-hosting/deployment/docker-compose.

---

## Main usage

**`analyze`** / **`chat`** — unchanged interface; add `--trace` to emit a Langfuse trace.

```bash
uv run realthor analyze --user analyst_001 --region north --property-type house --bedrooms 3 --trace
# → ... Run ID: 3f9a...  (replay with: realthor replay --run-id 3f9a...)
#     Trace sent to Langfuse — open your project to inspect the run.
```

`--no-trace` forces a run untraced even when the config default is on; a run with tracing
enabled but no `LANGFUSE_*` keys simply runs untraced (no error). Every traced run is tagged
(`langfuse_tags=["analyze"]` or `["chat"]`) so you can filter RealThor's runs in the UI.

---

## How to read a trace

Open a run in the Langfuse UI and you get a **trace** — one complete request, from the input
question to the final answer, captured as a single unit. Inside it is a tree of
**observations**, one per step, nested to show what happened inside what. Two kinds matter:

- **Spans** — the tool calls (and chain steps). Click a tool span like `get_demand_signals`
  or `get_supply_snapshot` and the panel shows its **input** (the arguments the agent passed,
  e.g. `region=north, property_type=house, bedrooms=3`) and its **output** (the row it
  returned). These are the facts the agent had in hand.
- **Generations** — the LLM calls. A generation is a special span that also carries the
  **model name**, the full prompt and completion, the **token counts**, the **cost**, and the
  **latency**. The final generation is where the model reads the tool results and decides.

Read the tree top to bottom and the whole run is legible: which tools were called, in what
order, what each returned, and how the model weighed them into the recommendation — the
reasoning path that logs and replay can't show. Use the **tag** filter (`analyze` / `chat`)
to find RealThor's runs among everything the project has traced.

---

## Architecture

```
CLI (app.py)
    ↓
build_tracer (tracing.py) → Langfuse CallbackHandler | None   # from config + LANGFUSE_* env
    ↓
agent.invoke(..., config={"callbacks": [usage_cb, tracer], "configurable": {"thread_id": run_id}})
    ├── build_main_agent (agents.py, checkpointer=SqliteSaver)   # unchanged
    ├── 15 bespoke tools + analyze_data sub-agent
    └── middleware (guardrails.py) + HITL (make_hitl_policy)
    ↓
flush_tracer (finally) — deliver batched spans before the process exits
    ↓
_log_run (app.py) → logs/runs.jsonl   ·   replay --run-id → reconstruct from state.db
```

---

## Project structure

```
realthor/
├── src/realthor/
│   ├── app.py          # CLI (analyze + chat + report + replay); --trace wiring
│   ├── agents.py       # build_analyst_agent + build_main_agent (unchanged)
│   ├── tracing.py      # build_tracer, trace_callbacks, flush_tracer (new)
│   ├── replay.py       # build_checkpointer, load_run, reconstruct_context
│   ├── monitor.py      # RunRecord, metrics, report (unchanged)
│   ├── policies.py     # PolicyDecision + evaluate_channel_policy
│   ├── guardrails.py   # 3 guardrail layers + make_hitl_policy
│   ├── sandbox.py      # validate_code + run_sandboxed
│   ├── config.py       # config/path utilities
│   └── tools.py        # 15 bespoke tools + make_execute_python_tool
├── tests/
│   ├── fixtures/                     # state.db + sample logs (offline)
│   ├── test_tracing.py               # 5 unit tests (new, no network)
│   ├── test_replay.py                # 7 unit tests
│   ├── test_monitor.py               # 9 unit tests
│   ├── test_data_integrity.py        # 18 pre-provided, never modify
│   └── test_config/guardrails/policies/sandbox/tools.py
├── evaluation/
│   ├── eval_scenarios.csv            # 95 scenarios, never hand-edit
│   └── run_eval.py
├── data/                             # 9 CSVs
├── data_forge/
├── logs/runs.jsonl
├── reports/
├── prompts/system_prompt_v9.md
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
... 86 passed

=== Checking data integrity ===
18 passed

=== Running evaluation ===
Running 10/95 scenarios (sampled evenly by type)...
10/10 scenarios passed
All scenarios passed.

=== Building container ===
[+] Building ...

=== Running deployed agent ===
Identity: analyst_001 (analyst)
[agent output]

All checks passed.
```

The unit + data-integrity + eval stages need no Langfuse backend (`test_tracing.py`
monkeypatches the handler). To emit a live trace end-to-end, start Langfuse (see above), put
the keys in `.env`, then:

```bash
uv run realthor analyze --user analyst_001 --region north --property-type house --bedrooms 3 --trace
# open the run in the Langfuse UI
```

---

## Local vs Deployed

```bash
# Local
uv run realthor analyze --user analyst_001 --region north --property-type house --bedrooms 3 --trace

# Deployed (Docker — local only, not available in Udacity Workspace)
docker compose run --rm realthor analyze --region north --property-type house --bedrooms 3 --user analyst_001 --trace
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
git add author/modules/09_tracing/exercises/solution/
git commit -m "feat: add tracing.py with Langfuse instrumentation and --trace flag"
```
