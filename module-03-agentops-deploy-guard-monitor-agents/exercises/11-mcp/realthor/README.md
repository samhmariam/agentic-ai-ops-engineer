# RealThor v0.11 — Agent Communication Protocols (MCP)

Listing Supply Intelligence agent for the Ciudaty PropTech. In v0.11 RealThor stops being one
system: its market-data tools no longer live in its own process: they are served by a **separate
MCP server** and RealThor consumes them over the **Model Context Protocol**. RealThor is now an
MCP *client* of a standard tool service. The lesson of the final chapter: **scale comes from
standard interfaces, not more custom integrations.**

Everything from v0.10 carries forward: the interactive **login** app is still the only way to
talk to RealThor, identity is still a password-verified `UserContext`, and guardrails + HITL +
tracing still apply. What changed is *where the tools come from*.

---

## Two projects

```
exercises/solution/
  realthor/   # the interactive agent — an MCP client
  mcp/        # the market-data service — an MCP server (its own project)
```

The MCP server is a genuinely separate system with its own code, data, tests, and container. You
run it, then run RealThor, which connects to it.

---

## Setup

```bash
# 1) the data service
cd mcp && uv sync && cd ..

# 2) the agent
cd realthor && uv sync
cp .env.example .env   # set LLM_PROVIDER + its key (Vocareum by default); for tracing add the LANGFUSE_* keys
```

`realthor.db` (users + sessions) is seeded automatically on first run from `users.csv` with the
shared dev password (`realthor-dev`); seed explicitly with `uv run python data_forge/seed_db.py`.

---

## Main usage — run the server, then the agent

```bash
# terminal 1 — start the MCP data service
cd mcp && uv run proptech-mcp serve            # streamable HTTP on http://localhost:8000/mcp

# terminal 2 — start RealThor (connects to the server on startup)
cd realthor && uv run realthor
# User id: analyst_001
# Password: realthor-dev
# --- Menu --- 1) New session  2) Resume a session  3) Analyze a segment  4) Logout
```

Ask a demand/supply/velocity question and the agent answers using tools **served over MCP** — the
data lookups run in the `mcp/` process, not RealThor's. If the server isn't running, RealThor
can't fetch its tools at startup: start `mcp serve` first. A turn that triggers an approval-gated
tool (e.g. `submit_channel_recommendation`) prompts the operator to **approve or reject** inline
and resumes on the spot.

The `report` and `replay` subcommands are read-only ops utilities (monitoring + debugging) and
need no server.

---

## What changed from the previous version

- **`mcp/` (new project)** — a FastMCP server (`company_mcp.server.build_server`) publishing the
  read-only `get_demand_signals` / `get_supply_snapshot` / `get_listing_velocity` tools over MCP.
  Run with `uv run proptech-mcp serve` (streamable HTTP) or `--transport stdio`.
- **`realthor/src/realthor/mcp_client.py` (new, the student deliverable)** — `load_mcp_tools(cfg)`
  builds a `MultiServerMCPClient` from `cfg["mcp"]` and returns the server's tools as LangChain
  tools. This is the connection that makes RealThor an MCP client.
- **`agents.py`** — `build_main_agent(cfg, checkpointer, mcp_tools=...)`: when MCP tools are
  injected, RealThor's data lookups come from them instead of the local `make_tools(...)` copies;
  the local action/analyst tools, model, prompt, identity context, and guardrail/HITL middleware
  are unchanged.
- **`app.py` / `interactive.py`** — the headless `analyze`/`chat` commands and `--user`/`--password`
  flags are **removed**; the interactive login app is the only interface. The turn is now **async**
  (`ainvoke`) because MCP tools are async; the interactive loop drives it with `asyncio.run`.
- **`guardrails.py`** — `ToolGuardrails` gains an async `awrap_tool_call` twin (same access checks
  and redaction) so guardrails still apply when the agent runs with `ainvoke`.
- **`config.yaml`** — new `mcp:` section (transport + url; stdio alternative documented); prompt
  bumped to `system_prompt_v11.md`; version `0.11.0`.
- **5 MCP eval scenarios** (106 total) — parity checks that a demand/supply/velocity answer is the
  same whether the tool ran locally or over MCP.

### Identity + guardrails survive the boundary

Because the agent, its `context_schema=UserContext`, and the guardrail/HITL middleware stay in
RealThor's process and only *tool execution* is remote, identity-based guardrails still enforce
in-process. A region-restricted broker asking outside their region is still blocked: the MCP
server never sees identity; RealThor gates access before the call. The HITL-gated action tools
(`submit_channel_recommendation`, `flag_segment_for_review`) stay local; only the read-only data
tools move to MCP.

> **Known limitation.** The MCP data service is unauthenticated: it trusts its caller on a
> private network. A client reaching it directly would bypass RealThor's guardrails. Production
> adds MCP-level auth (`headers: {Authorization: Bearer …}` on the client, a token check on the
> server).

---

## Transports

- **streamable HTTP** (default) — the server runs as a service; the client connects to a URL.
  This is the "deploy as a service, any client connects" story (demo + Docker).
- **stdio** — the client launches the server as a subprocess over stdin/stdout (self-contained,
  no port). Uncomment the `mcp.command`/`mcp.args` block in `config.yaml` to use it.

`load_mcp_tools` is transport-agnostic: it reads whichever the config selects.

---

## Multi-agent (conceptual)

Coordinating specialized agents (demand / supply / pricing / policy) uses LangChain's multi-agent
patterns — subagents, handoffs, routers — orchestrated with LangGraph. MCP is the protocol such a
system communicates *through*; the hands-on here is the client + server that make it possible.

---

## Langfuse setup (carried forward)

Tracing still works over MCP: the MCP tool calls appear as **spans** in the trace, so the protocol
boundary is transparent to observability. Backend is an env-var choice.

**Local (self-hosted, default)** — Langfuse's official Docker stack, pinned to a release:

```bash
git clone --branch v3.130.0 https://github.com/langfuse/langfuse.git
cd langfuse && docker compose up -d          # UI on http://localhost:3000 after ~2-3 min
```

Create a project, copy its public/secret keys into `realthor/.env`, keep
`LANGFUSE_HOST=http://localhost:3000`. A separate stack from RealThor's own `compose.yaml`.

**Cloud** — set `LANGFUSE_HOST=https://us.cloud.langfuse.com` and use your cloud project's keys.

Traces are attributed by **user** and **session** (`langfuse_user_id` / `langfuse_session_id`),
set at invoke time in `arun_agent_turn` via `config["metadata"]`.

---

## Architecture

```
mcp/  (separate system)
  company_mcp.server.build_server → FastMCP("proptech-data")
    get_demand_signals · get_supply_snapshot · get_listing_velocity   # over MCP

realthor/  (the agent — an MCP client)
  interactive.py: login → menu (new / resume / analyze / logout)
        ↓
  auth.authenticate → UserContext                     # password-verified, from realthor.db
        ↓
  load_mcp_tools(cfg) → MultiServerMCPClient.get_tools()   # ← the deliverable: fetch tools over MCP
        ↓
  build_main_agent(cfg, checkpointer, mcp_tools=…)    # data tools = MCP; actions/analyst = local
        ↓
  arun_agent_turn (async):
        thread_id = thread_id_for(user_id, session_id)     # user-namespaced checkpointer key
        await agent.ainvoke(..., context=user_ctx, config={..., metadata:{user,session,tags}})
        ├── guardrails + HITL middleware (in-process; async awrap_tool_call)
        └── analyze_data sub-agent invoked with context= (scoped)
```

---

## Project structure

```
mcp/
├── src/company_mcp/{server.py, config.py}   # FastMCP server + `mcp serve` CLI
├── data/                                     # the CSVs this service owns
├── tests/test_server.py · test_config.py     # offline, in-memory FastMCP client
├── config.yaml · ops.sh · pyproject.toml · Dockerfile

realthor/
├── src/realthor/
│   ├── mcp_client.py   # load_mcp_tools — the deliverable
│   ├── interactive.py  # login → session menu (only interface)
│   ├── app.py          # interactive entry + report/replay ops (analyze/chat removed)
│   ├── agents.py       # build_main_agent(mcp_tools=…) + analyst sub-agent
│   ├── auth.py · sessions.py · context.py    # login + owned sessions + identity
│   ├── guardrails.py   # 3 layers + HITL (async awrap_tool_call)
│   ├── tracing.py · replay.py · monitor.py · policies.py · sandbox.py · tools.py · config.py
├── tests/
│   ├── test_mcp.py                           # NEW: load_mcp_tools against a stdio FastMCP stub
│   ├── test_interactive.py                   # CliRunner suite (login/session/isolation/HITL, async)
│   ├── test_data_integrity.py                # 18, pre-provided
│   └── test_config/tools/guardrails/sandbox/policies/monitor/replay/tracing/context/auth/sessions.py
├── evaluation/{eval_scenarios.csv (106), run_eval.py}
├── data/ · data_forge/ · logs/ · reports/
├── prompts/system_prompt_v11.md
├── config.yaml · config.docker.yaml · ops.sh · Dockerfile · compose.yaml · pyproject.toml
```

---

## How to verify

```bash
cd mcp && sh ops.sh          # the data service: 8 offline tests
cd ../realthor && sh ops.sh  # unit (125) + integrity (18) + eval + docker build/smoke
```

Live end-to-end (MCP-served tools):

```bash
# terminal 1
cd mcp && uv run proptech-mcp serve
# terminal 2
cd realthor && uv run realthor    # log in, ask a demand question → answer comes over MCP
```

Kill the server and ask again — the tool call fails, confirming the tools are truly remote.

---

## Local vs Deployed

```bash
# Local — two processes
cd mcp && uv run proptech-mcp serve
cd realthor && uv run realthor

# Deployed — two compose services (mcp server + realthor client)
docker compose up -d mcp                     # the data service on :8000
docker compose run --rm -it realthor         # interactive client → connects to http://mcp:8000/mcp
```

Same interface. Only the runtime and the server host change (`localhost` → `mcp`, via
`config.docker.yaml`).

---

## Docker Reference

### Inspect / Clean up

```bash
docker images && docker ps -a && docker system df
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

> The dev password (`realthor-dev`) is a local convenience; in production per-user secrets go
> through one of the above and hashing moves to bcrypt/argon2. The MCP server's Bearer token would
> be injected the same way.

### Tagging images

```bash
GIT_SHA=$(git rev-parse --short HEAD)
docker build -t realthor:$GIT_SHA -t realthor:latest .
```

---

## Commit

```bash
git add author/modules/11_mcp/exercises/solution/
git commit -m "feat: RealThor consumes market-data tools over MCP (client) + mcp/ data service"
```
