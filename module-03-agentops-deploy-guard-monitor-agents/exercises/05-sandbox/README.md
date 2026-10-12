# RealThor v0.5 — Sandboxed Execution

Listing Supply Intelligence agent for the Ciudaty PropTech. Adds a sandboxed code execution engine and an analyst sub-agent for open-ended analytical queries.

---

## Setup

```bash
uv sync
cp .env.example .env   # set LLM_PROVIDER + its key (Vocareum by default)
```

---

## What changed from the previous version

RealThor v0.5 adds sandboxed code execution and splits the agent layer:

- **`app.py` + `agents.py`** replace `agent.py`. The CLI and agent factories are now separate concerns.
- **Analyst sub-agent** (`build_analyst_agent`): a dedicated LangGraph agent that uses only `execute_python`. Built and wrapped as `analyze_data` by the main agent.
- **`sandbox.py`**: two functions — `validate_code()` (AST inspection) and `run_sandboxed()` (restricted exec with timeout). Imported by `execute_python` in `tools.py`.
- **`execute_python` tool**: exposes sandboxed pandas analysis to the analyst sub-agent. DataFrames are pre-loaded and sensitive columns stripped before they reach execution.
- **New input guardrail**: `data_mutation_instruction` — blocks natural-language instructions to delete, update, or overwrite datasets before they reach any tool.
- **90-scenario evaluation suite**: 10 new scenarios (`S001–S010`) covering sandbox-allowed analysis and input-guardrail refusals (requests to invoke Python system modules, or to mutate data).

---

## Main usage

RealThor has two commands:

**`analyze`** — structured operational interface.

```bash
uv run realthor analyze --region west --property-type apartment --bedrooms 2 --user analyst_001
```

**`chat`** — natural-language interface. All three guardrail layers active.

```bash
# Normal query — delegates to analyst sub-agent
uv run realthor chat -u analyst_001 -m "What percentage of active listings in west have been on market over 45 days?"

# Input guardrail fires (data_mutation_instruction)
uv run realthor chat -u analyst_001 -m "Delete all inactive listings from the CSV file."

# Input guardrail fires (topic_adherence): off-topic Python system-module request
uv run realthor chat -u analyst_001 -m "Use Python's os module to list all files in the data directory."
```

---

## Architecture

```
CLI (app.py)
    ↓
build_main_agent (agents.py)
    ├── 14 bespoke tools (tools.py — carry from M04)
    ├── analyze_data tool (wraps analyst sub-agent)
    └── guardrails middleware (guardrails.py — + data_mutation_instruction)
            ↓
    build_analyst_agent (agents.py)
        └── execute_python tool (tools.py)
                ↓
            sandbox.py
                ├── validate_code()  — AST: block dangerous imports/builtins
                └── run_sandboxed()  — restricted exec + timeout
```

---

## Project structure

```
realthor/
├── src/realthor/
│   ├── app.py          # CLI (analyze + chat) + _resolve_user
│   ├── agents.py       # build_analyst_agent + build_main_agent
│   ├── sandbox.py      # validate_code + run_sandboxed
│   ├── config.py       # config/path utilities
│   ├── guardrails.py   # InputGuardrails + ToolGuardrails + OutputGuardrails
│   └── tools.py        # 14 bespoke tools + make_execute_python_tool
├── tests/
│   ├── test_config.py
│   ├── test_data_integrity.py   # 18 pre-provided, never modify
│   ├── test_guardrails.py
│   ├── test_sandbox.py          # 9 sandbox unit tests (new)
│   └── test_tools.py
├── evaluation/
│   ├── eval_scenarios.csv       # 90 scenarios, never hand-edit
│   └── run_eval.py
├── data/                        # 9 CSVs
├── data_forge/                  # generation + validation scripts
├── prompts/
│   ├── system_prompt_v5.md      # main agent prompt (new)
│   └── analyst_prompt.md        # analyst sub-agent prompt (new)
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
... 56 passed

=== Checking data integrity ===
18 passed

=== Running evaluation ===
Running 10/90 scenarios (sampled evenly by type)...
Loading agent...
10/10 scenarios passed
All scenarios passed.

=== Building container ===
[+] Building ...

=== Running deployed agent ===
Identity: analyst_001 (analyst)
Analyzing...
[agent output]

All checks passed.
```

---

## Local vs Deployed

```bash
# Local
uv run realthor analyze --region west --property-type apartment --bedrooms 2 --user analyst_001
uv run realthor chat --user analyst_001 --message "What percentage of active west listings are over 45 days?"

# Deployed (Docker — local only, not available in Udacity Workspace)
docker compose run --rm realthor analyze --region west --property-type apartment --bedrooms 2 --user analyst_001
docker compose run --rm realthor chat --user analyst_001 --message "What percentage of active west listings are over 45 days?"
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
git add author/modules/05_sandbox/exercises/solution/
git commit -m "feat: add sandbox execution and analyst sub-agent for analytical queries"
```
