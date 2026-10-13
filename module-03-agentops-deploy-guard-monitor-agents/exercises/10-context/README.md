# RealThor v0.10 — Context & State Isolation

Listing Supply Intelligence agent for the Ciudaty PropTech. RealThor is now a **multi-user
application**: callers **log in** with a password (no more `--user` impersonation), work
inside **owned, resumable sessions**, and every run's agent state is keyed to identity. The
isolation the model needs is not a smarter prompt: it is state scoped to *who* is asking.

Logs (v0.7) said a run happened; replay (v0.8) restored its state; traces (v0.9) showed the
reasoning path. v0.10 makes sure the *right* state reaches the *right* caller and no other —
and, because tracing carries forward, each run is attributed by **user** and **session** so
that isolation is visible in Langfuse, not just asserted.

---

## Setup

```bash
uv sync
cp .env.example .env   # set LLM_PROVIDER + its key (Vocareum by default); for tracing add the LANGFUSE_* keys
```

The application database (`realthor.db`) is seeded automatically on first run from
`users.csv` with a shared development password (`realthor-dev`). To seed it explicitly:

```bash
uv run python data_forge/seed_db.py
```

---

## What changed from the previous version

RealThor v0.10 turns the v0.9 single-shot CLI into a real application:

- **`context.py`** (two student deliverables): `thread_id_for(user_id, session_id)` — the
  checkpointer thread key, **namespaced by user** (same user+session resumes; a different user
  *or* session is isolated; a leaked `session_id` can't cross into another user's checkpoint
  space) — and `trace_metadata(user_ctx, session_id, command)` — the `langfuse_user_id` /
  `langfuse_session_id` / `langfuse_tags` dict that attributes each trace to who ran it (identity
  → observability). Also hosts `resolve_user` (identity → `UserContext`, read from the database).
- **`auth.py`** (new): `authenticate` verifies a password (salted PBKDF2, stdlib) against the
  `users` table before any context is resolved. Identity is a proven credential, not a flag.
- **`sessions.py`** (new): the application database (`realthor.db`) — `users` and `sessions`
  tables, session create/list/resume **scoped to the owner**, and LLM session titles.
- **`interactive.py`** (new) + **`app.py`**: bare `realthor` launches the interactive app
  (login → menu: new session / resume / analyze / logout). The `analyze`/`chat` subcommands
  stay for scripting/CI, now authenticating via `--user`/`--password`. Every turn keys the
  checkpointer by `thread_id_for(...)` and, when traced, attributes the run with
  `langfuse_user_id` + `langfuse_session_id` (on top of the command tag).
- **`agents.py`**: the delegated analyst sub-agent now runs under the caller's `context=`, so
  a sub-agent call can't widen the caller's scope — context is threaded through every hop.
- **`config.yaml`**: `paths.app_db: realthor.db`; prompt bumped to `system_prompt_v10.md`;
  version `0.10.0`.
- **6 context-isolation eval scenarios** (101 total) — 4 normal regressions + 2 region-scope blocks,
  resolving identity from the database.

### The two databases

RealThor now keeps two SQLite databases with different jobs:

| Database | Responsibility | Keyed by |
|---|---|---|
| `realthor.db` | **Application state** — users (credentials, role, region access) + sessions | `user_id`, `session_id` |
| `state.db` | **Agent state** — the LangGraph checkpointer (conversation messages/tool results) | `thread_id` |

`thread_id_for` is the bridge: it derives the checkpointer's `thread_id` from an application
`(user, session)` pair.

### Sessions and isolation

A random `thread_id` per run gave RealThor amnesia (no memory) and no isolation contract (the
naive fix — a shared thread — leaks one caller's state to another). Both are the same missing
abstraction. RealThor's isolation is now a three-layer contract:

1. **Authentication** — you are who you logged in as (password-verified, not a `--user` claim).
2. **Session ownership** — `list_sessions`/`get_session` are scoped by `user_id`; you can only
   see and resume your own sessions, even if you learn another's id.
3. **User-namespaced thread** — `thread_id_for(user, session)` prefixes the checkpointer key
   with the user, so a leaked `session_id` still can't reach another user's state.

Because an interactive session keeps one thread across turns, `realthor replay --run-id
<user:session>` reconstructs that session's **latest** turn (headless one-shots still get a
unique id per run).

---

## Concepts carried forward (and where they'd grow in production)

- **State vs Runtime Context vs Store.** *State* is the conversation (checkpointer, per-thread).
  *Runtime Context* is the static per-invocation identity (`UserContext`, passed via `context=`).
  A *Store* is cross-thread long-term memory (semantic/vector recall) — a separate object from
  the checkpointer, conceptual here.
- **Production checkpointer.** SQLite is fine locally; a **PostgreSQL** checkpointer is the
  drop-in production upgrade for concurrent, durable state.
- **Long conversations.** `SummarizationMiddleware` compacts history once it grows past a
  threshold, so a long session doesn't blow the context window.

---

## Main usage

**Interactive app** — the primary experience:

```bash
uv run realthor
# User id: analyst_001
# Password: realthor-dev
# --- Menu --- 1) New session  2) Resume a session  3) Analyze a segment  4) Logout
```

A new session gets a human-readable title from your first message; resume lists your own
sessions (title · message count · last active) and continues the thread; it remembers. A turn
that triggers an approval-gated tool (e.g. `submit_channel_recommendation`) prompts the operator
to **approve or reject** inline and resumes on the spot — no dangling interrupt.

**Headless** (scripting / CI) — same identity model, credentials on the flags:

```bash
uv run realthor analyze --user analyst_001 --password realthor-dev \
  --region north --property-type house --bedrooms 3 --trace
```

`--no-trace` forces a run untraced; a run with tracing enabled but no `LANGFUSE_*` keys simply
runs untraced (no error).

---

## Langfuse setup

The backend is an env-var choice: local vs cloud is a `.env` change, not code.

**Local (self-hosted, default)** — Langfuse's official Docker stack, pinned to a release:

```bash
git clone --branch v3.130.0 https://github.com/langfuse/langfuse.git
cd langfuse
docker compose up -d          # UI on http://localhost:3000 after ~2-3 min
```

Open `http://localhost:3000`, create a project, copy its public/secret keys into this
project's `.env`, keep `LANGFUSE_HOST=http://localhost:3000`. This is a **separate** stack from
RealThor's own `compose.yaml`.

**Cloud (alternative)** — set `LANGFUSE_HOST=https://us.cloud.langfuse.com` (or the EU host)
and use your cloud project's keys.

> Pin the Langfuse release tag you clone; the self-hosting stack evolves. Verify the current
> quickstart at https://langfuse.com/self-hosting/deployment/docker-compose.

---

## How to read a trace — now attributed by identity

Open a run in Langfuse: a **trace** is one complete request, containing a tree of
**observations** — **spans** (tool calls, with input args and returned rows) and
**generations** (LLM calls, with model, tokens, cost, latency). What v0.10 adds is
**attribution**:

- **Filter by User** — pick `analyst_001` and you see only that analyst's runs. A different
  user's runs are a separate, attributed group. The isolation the checkpointer enforces on
  state is now visible in the traces.
- **Filter by Session** — one session groups a user's turns, so you can follow a conversation
  across runs (and return to it later — the payoff of a persistent session).

Attribution is set at invoke time in `run_agent_turn` via `config["metadata"]`:
`langfuse_user_id`, `langfuse_session_id`, and `langfuse_tags`.

---

## Architecture

```
CLI (app.py)
  ├── bare `realthor` → interactive.py: login → menu (new / resume / analyze / logout)
  └── analyze | chat  → authenticate(--user, --password)   # headless, service-account style
        ↓
  auth.authenticate (auth.py) → UserContext          # password-verified, from realthor.db
        ↓
  run_agent_turn (app.py):
        thread_id = thread_id_for(user_id, session_id)     # context.py — user-namespaced key
        agent.invoke(..., context=user_ctx,
            config={"configurable": {"thread_id": thread_id},
                    "callbacks": [usage_cb, tracer],
                    "metadata": {langfuse_user_id, langfuse_session_id, langfuse_tags}})
        ├── build_main_agent (agents.py, checkpointer=SqliteSaver → state.db)
        │     └── analyze_data sub-agent invoked with context= (scoped)
        └── guardrails + HITL middleware
        ↓
  sessions.py (realthor.db): create / list / get / touch — ownership-scoped
```

---

## Project structure

```
realthor/
├── src/realthor/
│   ├── app.py          # CLI: interactive entry + analyze/chat/report/replay (headless auth)
│   ├── interactive.py  # login → session menu (new)
│   ├── auth.py         # password hashing + authenticate + session token (new)
│   ├── sessions.py     # realthor.db: users + sessions, ownership-scoped (new)
│   ├── context.py      # thread_id_for + resolve_user (new; thread_id_for = deliverable)
│   ├── agents.py       # build_main_agent + analyst sub-agent (context propagated)
│   ├── tracing.py      # build_tracer/trace_callbacks/flush_tracer (carried forward)
│   ├── replay.py       # build_checkpointer, reconstruct_context
│   ├── monitor.py      # RunRecord, metrics, report
│   ├── guardrails.py   # UserContext + 3 guardrail layers + HITL policy
│   ├── policies.py · sandbox.py · config.py · tools.py
├── tests/
│   ├── test_context.py · test_auth.py · test_sessions.py   # new, offline
│   ├── test_interactive.py                                 # new: CliRunner CLI suite (login/session/isolation/HITL)
│   ├── test_data_integrity.py                              # 18, pre-provided
│   └── test_config/tools/guardrails/sandbox/policies/monitor/replay/tracing.py
├── evaluation/
│   ├── eval_scenarios.csv            # 101 scenarios, never hand-edit
│   └── run_eval.py
├── data/ · data_forge/ (seed_db.py new) · logs/ · reports/
├── prompts/system_prompt_v10.md
├── config.yaml · ops.sh · Dockerfile · compose.yaml · pyproject.toml
```

---

## How to verify

```bash
sh ops.sh
```

Expected:

```
=== Running unit tests ===
... 120 passed

=== Checking data integrity ===
18 passed

=== Seeding application database (realthor.db) ===
  realthor.db (14 users seeded; dev password 'realthor-dev')

=== Running evaluation ===
Running 10/101 scenarios (sampled evenly by type)...
10/10 scenarios passed

=== Building container ===  ·  === Running deployed agent ===
All checks passed.
```

Unit + integrity + eval need no Langfuse backend. To see identity-attributed traces, start
Langfuse (above), put the keys in `.env`, then run a traced turn and filter the UI by user or
session.

**See isolation directly:**

```bash
uv run realthor            # log in as analyst_001 → New session, ask something, exit
uv run realthor            # log in as analyst_001 → Resume → it remembers
uv run realthor            # log in as analyst_002 → their session list is separate
```

---

## Local vs Deployed

```bash
# Local
uv run realthor analyze --user analyst_001 --password realthor-dev \
  --region north --property-type house --bedrooms 3 --trace

# Deployed (Docker — local only, not available in Udacity Workspace)
docker compose run --rm realthor analyze --user analyst_001 --password realthor-dev \
  --region north --property-type house --bedrooms 3 --trace
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

> The dev password (`realthor-dev`) is a local convenience. In production, per-user secrets go
> through one of the mechanisms above, and password hashing moves to bcrypt/argon2.

### Tagging images

```bash
GIT_SHA=$(git rev-parse --short HEAD)
docker build -t realthor:$GIT_SHA -t realthor:latest .
```

---

## Commit

```bash
git add author/modules/10_context/exercises/solution/
git commit -m "feat: identity-scoped context and state isolation (login + sessions + thread_id_for)"
```
