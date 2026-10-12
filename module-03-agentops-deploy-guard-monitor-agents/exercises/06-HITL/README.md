# RealThor v0.6 — Human-in-the-Loop

Listing Supply Intelligence agent for the Ciudaty PropTech. Adds a HITL policy layer and channel recommendation tool: marketplace submissions execute immediately; high-value iBuyer submissions pause for operator approval.

---

## Setup

```bash
uv sync
cp .env.example .env   # set LLM_PROVIDER + its key (Vocareum by default)
```

---

## What changed from the previous version

RealThor v0.6 adds human-in-the-loop (HITL) for high-risk actions:

- **`policies.py`**: `PolicyDecision` dataclass + `evaluate_channel_policy()`. Pure Python — no LangChain imports. This is the student deliverable.
- **`make_hitl_policy(cfg)` in `guardrails.py`**: configures `HumanInTheLoopMiddleware` as a fourth middleware layer. Its `when` predicate calls `evaluate_channel_policy()` — interrupts only when the policy returns `requires_approval=True`.
- **`submit_channel_recommendation` tool** in `tools.py`: pure action tool with no interrupt logic. Middleware handles when to pause; the tool just records the decision.
- **`app.py` `chat` command**: new `--approval approve|reject` flag; adds `InMemorySaver` + interrupt detection + `Command(resume=...)` loop.
- **`config.yaml`**: new `hitl.ibuyer_threshold: 500000`; new `paths.channel_recommendations`.
- **100-scenario evaluation suite**: 10 new scenarios (`H001–H010`) covering HITL pending, approved, rejected, and guardrail-blocked channel submissions.

---

## Main usage

**`analyze`** — structured operational interface (unchanged).

```bash
uv run realthor analyze --region west --property-type apartment --bedrooms 2 --user analyst_001
```

**`chat`** — natural-language interface with HITL.

```bash
# Marketplace — executes immediately, no approval needed
uv run realthor chat -u analyst_001 -m "Recommend marketplace channel for OPP-00001"

# High-value iBuyer — pauses for approval
uv run realthor chat -u analyst_001 -m "Recommend iBuyer channel for OPP-00015"
# → [HITL] Pending approval: submit_channel_recommendation
# → Re-run with --approval approve or --approval reject.

# Resume with approval
uv run realthor chat -u analyst_001 -m "Recommend iBuyer channel for OPP-00015" --approval approve

# Resume with rejection
uv run realthor chat -u analyst_001 -m "Recommend iBuyer channel for OPP-00015" --approval reject
```

---

## Architecture

```
CLI (app.py)
    ↓
build_main_agent (agents.py)
    ├── 15 bespoke tools (tools.py — + submit_channel_recommendation)
    ├── analyze_data tool (wraps analyst sub-agent)
    └── middleware (guardrails.py)
            ├── InputGuardrails
            ├── ToolGuardrails
            ├── OutputGuardrails
            └── HumanInTheLoopMiddleware ← new (make_hitl_policy)
                    when: evaluate_channel_policy() → requires_approval?
                    yes  → interrupt() → wait for operator decision
                    no   → execute submit_channel_recommendation immediately
```

Key distinction: **guardrails are unconditional** (always block or pass based on role/content). **`HumanInTheLoopMiddleware` is conditional** — the `when` predicate evaluates context before deciding whether to pause.

---

## Project structure

```
realthor/
├── src/realthor/
│   ├── app.py          # CLI (analyze + chat) — + --approval flag, interrupt loop
│   ├── agents.py       # build_analyst_agent + build_main_agent — + checkpointer param
│   ├── policies.py     # PolicyDecision + evaluate_channel_policy (student deliverable)
│   ├── guardrails.py   # 3 guardrail layers + make_hitl_policy (new)
│   ├── sandbox.py      # validate_code + run_sandboxed
│   ├── config.py       # config/path utilities
│   └── tools.py        # 15 bespoke tools + make_execute_python_tool
├── tests/
│   ├── test_config.py
│   ├── test_data_integrity.py   # 18 pre-provided, never modify
│   ├── test_guardrails.py
│   ├── test_policies.py         # 9 unit tests (new)
│   ├── test_sandbox.py
│   └── test_tools.py
├── evaluation/
│   ├── eval_scenarios.csv       # 100 scenarios, never hand-edit
│   └── run_eval.py
├── data/
│   ├── *.csv                    # 9 CSVs
│   └── channel_recommendations.jsonl   # appended by submit_channel_recommendation
├── data_forge/
├── prompts/
│   ├── system_prompt_v6.md
│   └── analyst_prompt.md
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
... 65 passed

=== Checking data integrity ===
18 passed

=== Running evaluation ===
Running 10/100 scenarios (sampled evenly by type)...
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
uv run realthor chat --user analyst_001 --message "Recommend iBuyer channel for OPP-00015" --approval approve

# Deployed (Docker — local only, not available in Udacity Workspace)
docker compose run --rm realthor chat --user analyst_001 --message "Recommend iBuyer channel for OPP-00015" --approval approve
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
git add author/modules/06_hitl/exercises/solution/
git commit -m "feat: add HITL policy middleware and channel recommendation tool"
```
