# Future Work: Stand-out Feature Upgrades

This file tracks optional feature upgrades for the SalesOps agent that are planned but not yet built. They come from the course's "Suggestions to Make Your Project Stand Out" and "Optional Stand-Out Features" lists. None of them is required to pass.

Each item says:

- **Goal:** what to build.
- **Design:** how it fits the existing code.
- **Done when:** the evidence that shows it works.
- **Risks:** what could go wrong.

Wider production work (SSO, secret managers, Kubernetes, data-layer permissions) is covered separately in [README → Production Hardening Recommendations](README.md#production-hardening-recommendations). This file is limited to features that can be built and demonstrated inside this project.

Last updated: 2026-10-14.

## Status at a glance

| # | Feature | Course list item(s) | Effort | Status |
|---|---|---|---|---|
| F1 | GitHub Actions evaluation workflow | GitHub Actions workflow | S | To do |
| F2 | Dockerfile packaging | Dockerfile for packaging | S | To do |
| F3 | Richer HTML monitoring report | Richer HTML monitoring report | S | To do |
| F4 | SQLite state with user/session/thread IDs and memory isolation | SQLite state persistence; user/session/thread IDs; memory isolation demonstration | L | To do |
| F5 | Replayable run history | Replayable run history | M | To do |
| F6 | Streamlit interface with approval queue | Simple Streamlit or Gradio interface | M | To do (needs F4) |
| F7 | External observability (Langfuse) with dashboard screenshot | External observability integration | M | To do |
| F8 | Docker-backed sandbox | Docker-backed sandbox | M | To do |

Effort: **S** about half a day, **M** one to two days, **L** two to four days.

### Suggested order

1. **F1, F2, F3.** These are cheap, independent, and visible to a reviewer straight away. F1 also protects every later change.
2. **F4.** The course lists it first, and F5 and F6 build on its tables.
3. **F6, then F5.** The UI is the most visible result; replay reuses the same storage.
4. **F7, F8.** These need extra infrastructure (a Langfuse instance, a Docker daemon).

### Ground rules for every feature

These come from the controls already in place and are non-negotiable:

- **Redaction before persistence or export.** Anything written to SQLite, sent to Langfuse, or shown in the UI's history goes through `Redactor` first, the same way logs and traces do today. Restricted tool outputs are never stored raw.
- **Guardrails stay in the runtime path.** A new entry point (UI, container, CI) calls `run_question`, so the input, tool and output guardrails, the sandbox and the HITL gate all apply unchanged.
- **No secrets in images, workflows or the database.** `.env` stays gitignored and is never copied into an image. CI reads `OPENAI_API_KEY` and `OPENAI_BASE_URL` from repository secrets.
- **`data/` is input only.** New state goes in new gitignored paths (`state/`, `outbox/`, `review/`).
- **Offline tests for every feature.** Each feature adds tests that run without an API key, using the scripted graphs already used in `tests/test_logging_tracing.py`.

---

## F1. GitHub Actions evaluation workflow

> Add a GitHub Actions workflow that runs the evaluation suite automatically on push.

**Goal:** every push that touches this project runs the offline tests and the control probes. A gated job runs the live evaluation and fails on a regression.

**Design:**

- **Location:** `.github/workflows/module-03-agentops.yml` at the **repository root**, next to the existing `module-01-ci-cd.yml`. GitHub only reads workflows from the root. Use `paths: ["module-03-agentops-deploy-guard-monitor-agents/project/**"]` and `defaults.run.working-directory`.
- **Job `offline`** (every push and PR, free and deterministic):
  - `astral-sh/setup-uv`, then `uv sync --frozen`.
  - `uv run pytest`: the offline suite.
  - `uv run evaluate --probes`: the 11 control probes, with no LLM.
  - Upload `reports/` as a workflow artifact.
- **Job `live-eval`** (pushes to `main` and manual `workflow_dispatch` only; needs `offline`):
  - Secrets: `OPENAI_API_KEY`, `OPENAI_BASE_URL`.
  - `uv run evaluate --min-pass-rate 0.95`.
  - `uv run salesops-agent compare reports/results/guarded-v7.json <new result> --fail-on-regression`.
  - Upload the evaluation report and the comparison as artifacts. Write the pass rate into `$GITHUB_STEP_SUMMARY`.
- **Concurrency:** one live evaluation per branch (`concurrency: module-03-eval-${{ github.ref }}`). Keep the default of 2 workers, since the proxy stalls under higher concurrency.

**Done when:**

- A green `offline` run on a push, with a link in the README.
- A deliberately broken policy fails the probes job. Revert afterwards and keep a screenshot or run link.
- The README gets a CI badge.

**Risks:**

- **Expired proxy key:** the Vocareum proxy key may expire after the course. If so, `live-eval` skips with a clear message when the secret is missing, rather than failing.
- **Fork PRs:** they don't receive secrets, so only `offline` runs for them.
- **Windows path limits:** these don't apply on `ubuntu-latest`.

---

## F2. Dockerfile packaging

> Package the agent with a Dockerfile so a reviewer can run it outside the Udacity workspace.

**Goal:** `docker build` followed by `docker run ... ask "..."` works on any machine with Docker.

**Design:**

- **Multi-stage `Dockerfile`** in the project root:
  - **Builder stage:** `ghcr.io/astral-sh/uv` copies `uv`, then `uv sync --frozen --no-dev` runs into `/app/.venv`.
  - **Runtime stage:** `python:3.13-slim` with the venv, `src/`, `config.yaml`, `configs/`, `prompts/`, `policies/`, `data/` and `evaluation/`.
  - Runs as a non-root user, with `ENTRYPOINT ["salesops-agent"]` and `CMD ["--help"]`.
  - Labels: git SHA and `agent_version` from `config.yaml`.
- **`.dockerignore`:** `.env`, `.venv/`, `logs/`, `traces/`, `reports/eval_*`, `review/`, `outbox/` and `project_starter.ipynb`.
- **Runtime state through volumes:**
  ```bash
  docker run --rm --env-file .env -v "$PWD/logs:/app/logs" -v "$PWD/traces:/app/traces" \
    salesops-agent ask "Summarize the account risk for Acme Corp."
  ```
- **Integrity at startup:** the prompt-registry hash checks already run when the agent starts, so a modified prompt inside the image fails loudly.

**Done when:**

- The README has a "Run with Docker" section with `ask`, `evaluate --probes` and `generate-monitoring-report` examples.
- An offline test or CI step builds the image and runs `evaluate --probes` inside it (this can be added to F1).

**Risks:**

- **Image size:** keep it small with the slim base and `--no-dev`.
- **Proxy reachability:** the container needs to reach `OPENAI_BASE_URL`.
- **Interaction with F8:** if F8 is built, the containerised agent can't start sibling sandbox containers without mounting the Docker socket, which must not be done. The packaged image keeps the process sandbox (see F8).

---

## F3. Richer HTML monitoring report

> Richer HTML monitoring report.

**Goal:** `reports/monitoring_report.html`, a single self-contained page with charts, built from the same metrics as the md, csv and json files.

**Design:**

- **Renderer:** a new `render_html(metrics)` in `monitoring.py`, written by `write_monitoring_report` next to the other three formats. It uses the existing `compute_metrics` output, so it adds no new aggregation logic.
- **No new runtime dependencies:**
  - Inline CSS with light and dark themes through `prefers-color-scheme`.
  - Inline SVG bar charts.
  - No external scripts, so the file opens offline and can be attached to a CI run.
- **Sections:**
  - Headline cards: runs, success rate, p95 latency, total cost.
  - Outcomes by experiment (stacked bars).
  - Latency distribution with p50/p95 markers.
  - Tool calls executed vs blocked.
  - Guardrail interventions by stage and rule.
  - HITL approvals, rejections and pending.
  - Top failure reasons with example task IDs.
  - The existing "Interpretation" observations.
- **Aggregates only:** no per-run user input or output appears, so no redaction concerns arise.

**Done when:**

- A test checks that every required metric label appears in the HTML and that it contains no `<script src=` tag.
- The README links the committed `reports/monitoring_report.html` and includes a screenshot in `docs/images/`.

**Risks:** low. Keep the SVG generation small and readable rather than building a charting library.

---

## F4. SQLite state, user/session/thread IDs and memory isolation

> Implement state persistence (e.g., SQLite) with explicit user, session, and thread identifiers, and demonstrate that one user's memory does not leak into another user's session.

**Goal:**

- Multi-turn conversations that persist across processes.
- Every run tagged with `user_id`, `session_id` and `thread_id`.
- Test evidence that user B can't read or resume user A's thread.

**Design:**

- **Identifiers:**
  - `user_id`: who is asking. It comes from `--user` today (simulated, like `--role`) and from authentication later.
  - `session_id`: one CLI or UI session, generated per process or browser session.
  - `thread_id`: one conversation.
  - All three are added to the run record, the trace (`trace_schema_version` 3) and every `agent.jsonl` event.
- **Storage (`state/salesops.db`, gitignored):**
  - `threads(thread_id PK, user_id, created_at, title)`.
  - `sessions(session_id PK, user_id, started_at)`.
  - `runs(run_id PK, thread_id FK, session_id FK, user_id, status, ...)`: an index over the existing run record. JSONL stays the source for monitoring until migrated.
  - Conversation checkpoints use LangGraph's SQLite checkpointer (`langgraph-checkpoint-sqlite`), passed to `create_agent(checkpointer=...)`. Each call is made with `config={"configurable": {"thread_id": ...}}`.
- **Isolation, enforced in code rather than by convention:**
  - **Ownership check:** a `ThreadStore.open(user_id, thread_id)` method raises `ThreadAccessDenied` unless `threads.user_id == user_id`. `run_question` calls it **before** the checkpointer is touched. A thread ID is never accepted on its own.
  - **Unguessable IDs:** thread IDs are random UUIDs, never derived from user input.
  - **Scoped queries:** every query filters on `user_id`, and there is no "list all threads" path without it.
- **Redacted memory:**
  - The model's memory holds tool outputs, which for an HR admin could include restricted data. Restricted tool outputs are stored in the checkpoint as the same `[REDACTED: restricted tool output]` placeholder used in traces, so a later turn must re-fetch them through the tool guardrail.
  - The cost is that a follow-up question re-runs the lookup, which in turn keeps the access control check on every turn.
- **CLI:**
  - `ask --user alice --thread <id>` continues a thread. Without `--thread`, a new thread is created and printed.
  - `salesops-agent threads --user alice` lists that user's threads.

**Demonstration (tests plus a README walkthrough):**

1. Alice, in thread T1, says "Remember: my focus account is Acme Corp", then asks "What is my focus account?" and gets "Acme Corp" (memory works).
2. Bob, in a new thread T2, asks "What is Alice's focus account?" The answer doesn't mention Acme, and T2's checkpoint contains no T1 messages.
3. Bob passes `--thread T1`, which raises `ThreadAccessDenied`. The run is logged with status `thread_access_denied` and no model call is made.
4. Restart the process: Alice resumes T1 and the memory is still there (persistence works).
5. After an HR-admin run in T1, the raw SQLite file contains none of the `LEAKS` values from `tests/test_logging_tracing.py`.

Steps 1–5 run offline with scripted graphs. One live run of steps 1–3 is recorded as trace examples.

**Risks:**

- **SQLite concurrency:** `evaluate` uses 2 workers, so enable WAL mode and give each worker its own connection.
- **Schema migrations:** keep a `schema_version` table.
- **Checkpoint redaction:** this depends on a hook between tool output and checkpoint write. Verify that the checkpointer stores the wrapped tool's return value, not the raw result.

---

## F5. Replayable run history

> Replayable run history.

**Goal:** `salesops-agent replay <run_id>` re-runs a past request under its recorded versions, or under a different config, and shows what changed.

**Design:**

- **Inputs already recorded:** every trace has `user_input`, `role`, `task_id` and a full `versions` manifest (experiment, config hash, prompt version and hash, tool versions, guardrail policy versions and hashes). User input is stored with only sensitive values redacted, so most requests replay exactly.
- **Two modes:**
  - **`replay <run_id>`** re-runs with the config named in `versions.experiment`. It first checks that the current prompt, policy and tool hashes still match the recorded ones, and warns per component if they don't. That is the replay-fidelity report.
  - **`replay <run_id> --config configs/candidate.yaml`** runs the same request against a new version and prints a diff of status, tools called, guardrail interventions and final output. This is a one-run version of `compare`.
- **Safety:**
  - Replays always run with `--approval pending`, so a replay never sends an email.
  - A replay is a new run with `source: "replay"` and `replay_of: <run_id>` in the run record. Monitoring can include or exclude replays.
- **With F4:** `replay --thread <id>` replays a whole conversation in order, starting from an empty thread.
- **Limitation:** model output is nondeterministic even at temperature 0, so a replay reproduces the *conditions*, not the exact output. The diff makes that visible. Deterministic paths (input blocks, tool blocks, sandbox refusals, probes) should replay identically, and a test asserts it.

**Done when:**

- Tests cover deterministic replay of a blocked run, hash-drift warnings, and approval forced to `pending`.
- The README shows an example replay diff of a baseline-v1 failure replayed under guarded-v7.

**Risks:**

- **Redacted inputs:** a request that contained redacted values replays with `[REDACTED]` in place of the value. Report this rather than hiding it.

---

## F6. Streamlit interface with approval queue

> Build a simple frontend (e.g., Streamlit or Gradio) for interacting with the SalesOps agent, including the approval interface.

**Goal:** a local web UI where a user chats with the agent, sees which guardrails acted, and a reviewer approves or rejects pending emails.

**Design (Streamlit, `src/salesops_agent/ui/app.py`, started with `uv run salesops-ui`):**

- **Chat tab:**
  - Pick the user and role (simulated, like the CLI flags) and a thread (F4).
  - Every message calls `run_question`.
  - Under each answer, an expander shows status, tools called, guardrail interventions (stage, status, reason), latency, cost and the run ID with a link to its trace.
- **Approvals tab:**
  - **Asynchronous approval:** Streamlit reruns the script on every click, so the CLI's synchronous `--approval prompt` callback doesn't fit. The UI uses `pending` mode: the agent records the request and stops. The reviewer approves later, which matches the asynchronous approval workflow recommended in the README.
  - **Pending requests:** a table of pending requests from the approvals store (`review/approvals.jsonl` today, or an F4 table), showing tool, redacted recipient, subject, body preview, requester and run ID.
  - **Executing approved sends:** an approve button sends the stored action **once**, using the `approval_id` as an idempotency key (a second click is a no-op). It appends the decision to the audit trail with the reviewer identity. Reject records the decision and reason.
  - **Separation of duties:** the reviewer can't be the requester.
- **Review queue tab:** responses withheld by the output guardrail (`review/review_queue.jsonl`), with release or discard actions. This closes the "No review tooling" limitation in the README.
- **Monitoring tab:** renders the F3 HTML report, or the md report until F3 exists.
- **Dependencies:** `streamlit` goes in an optional `ui` dependency group, so the core install stays small.

**Done when:**

- Offline tests cover the approval executor: approve sends once, double approval is a no-op, reject never sends, and the requester can't approve.
- The README has screenshots of a blocked request, a pending email in the queue, and the same email after approval.

**Risks:**

- **Executing approved actions:** this is new code that performs a side effect. It must re-run the tool guardrail at execution time (recipient domain, role) rather than trusting the stored request.
- **Local only:** Streamlit has no authentication, so document the UI as local-only.

---

## F7. External observability (Langfuse) with dashboard screenshot

> Integrate an external observability tool such as MLflow, LangSmith, or Langfuse and include a screenshot of the dashboard.

**Goal:** every run also appears as a trace in an external tool with a dashboard, without leaking raw sensitive data.

**Choice: Langfuse.**

- It is open source and self-hostable with `docker compose`, so no customer data has to leave the machine.
- It has a LangChain `CallbackHandler`.
- It supports a client-side `mask` function.

LangSmith (hosted only, `hide_inputs`/`hide_outputs`) and MLflow tracing (`mlflow.langchain.autolog`) are reasonable alternatives. The design below works for any of them.

**Design:**

- **Config:** a new section, default off, so tests and the proxy setup are unaffected:
  ```yaml
  observability:
    exporter: none            # none | langfuse
  ```
  Keys go in `.env` (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`).
- **Callback:** `run_question` adds the Langfuse handler next to `LocalTraceRecorder` in `config["callbacks"]`. The handler gets `user_id`, `session_id` (F4) and tags for `experiment`, `agent_version` and `prompt_version` from the version manifest.
- **Redaction:**
  - Initialise the Langfuse client with `mask=lambda data: redactor(data)`, so the same `Redactor` that protects local traces runs before anything leaves the process.
  - Restricted tool outputs are replaced by the placeholder, exactly as in `traces/`.
  - An offline test exports to a fake handler and asserts that none of the `LEAKS` values appear.
- **Scores:**
  - Evaluation runs attach `task_passed` and failure reasons as Langfuse scores, so pass rates show up per prompt version.
  - Guardrail interventions and HITL decisions are attached as events, so the dashboard can filter blocked runs.
- **Dependencies:** `langfuse` goes in an optional `observability` dependency group.

**Done when:**

- Screenshots in `docs/images/` show the dashboard (runs, latency, cost by experiment), one trace's span tree, and the redacted HR tool output inside a trace.
- The redaction test passes.
- The README has a section on running Langfuse locally and enabling the exporter.

**Risks:**

- **Leakage:** a third-party callback sees raw prompt and tool values unless masking is applied. The masking test is the guard.
- **Uptime dependency:** export failures must never fail a run. The handler flushes in the background and errors are logged and swallowed.
- **Proxy compatibility:** this was not tested against the Vocareum proxy, since Langfuse needs only the LangChain callbacks, not the provider.

---

## F8. Docker-backed sandbox

> Docker-backed sandbox.

**Goal:** `run_analysis` code runs in a throwaway container with no network, a read-only filesystem and hard CPU and memory limits on every OS. This closes the "process-level isolation only" and "weak limits on Windows" limitations in the README.

**Design:**

- **Backend setting:** `policies/sandbox_v2.yaml` adds `backend: process | docker`. `process` is today's `python -I -S -B` subprocess. The new `DockerSandbox` in `sandbox/executor.py` implements the same `run(code) -> dict` interface, so the tool, the guardrail and the logging don't change.
- **Validation stays first:** AST validation in `sandbox/validator.py` still runs before any container starts. Docker is an extra layer, not a replacement.
- **Container command:**
  ```
  docker run --rm --network none --read-only --tmpfs /tmp:size=16m
    --memory 256m --cpus 0.5 --pids-limit 64 --user 65534:65534
    --cap-drop ALL --security-opt no-new-privileges
    -v <approved-datasets.json>:/data/datasets.json:ro
    salesops-sandbox:<digest> python -I -S -B /runner.py
  ```
  - The image is pinned by digest and contains only Python and `sandbox/runner.py`.
  - Approved datasets are mounted read-only; HR and financial data are never mounted.
  - The timeout is enforced from outside (`docker kill` after `limits.timeout_s`).
- **Latency:** container start-up adds about 0.5–1.5 s per call. Measure it and, if needed, keep a small pool of pre-started containers.
- **Fallback:** if Docker is unavailable and the policy says `docker`, `run_analysis` refuses with `status: "sandbox_unavailable"`. It never falls back to the weaker backend silently.
- **With F2:** inside the packaged image, the agent uses `backend: process`. Mounting the Docker socket into the agent container would give it host-level control, which is the opposite of sandboxing. If both are wanted in deployment, use a separate sandbox service (gVisor or Firecracker), as described in the README's hardening section.

**Done when:**

- The existing sandbox tests run against both backends (Docker tests skipped when no daemon is available).
- New tests show that network access fails, a memory bomb is killed by the cgroup limit, writing outside `/tmp` fails, and the timeout kills the container.
- A sandbox evidence scenario (P-series probe) runs under `backend: docker`, recorded as a trace example.

**Risks:**

- **Docker on Windows:** Docker Desktop with WSL2 is needed on Windows. Keep `process` as the default backend so the project still runs without Docker.
