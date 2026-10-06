# Project Instructions: Production LLM FAQ Service

This is the capstone project for the LLM Ops course. You will operate
and extend a production-style RAG service across the full LLM Ops stack:
retrieval, prompt engineering, tiered model routing, evaluation,
guardrails, distributed tracing, cost monitoring, ingestion automation,
and (bonus) caching and streaming.

Read the rubric in the Classroom alongside these instructions —
the rubric tells you exactly what evidence to produce.

## Contents

- [§1. The Scenario](#1-the-scenario)
- [§2. What You Will Build](#2-what-you-will-build)
- [§3. Prerequisites Check](#3-prerequisites-check)
- [§4. Workspace Setup](#4-workspace-setup)
- [§5. How the Starter Works](#5-how-the-starter-works)
- [§6. Your Tasks](#6-your-tasks)
- [§7. Submission Requirements](#7-submission-requirements)
- [§8. Hints and Common Pitfalls](#8-hints-and-common-pitfalls)

---

## 1. The Scenario

You are an LLM Operations Engineer at **ThirdShotHub**, a mid-size
e-commerce company specializing in pickleball gear and apparel.
ThirdShotHub is replacing its static FAQ page with an LLM-powered
product Q&A service.

The static FAQ doesn't scale, can't answer product-specific questions,
and the support team is buried under tickets that should be self-serve.
Your job: take the production-ready RAG-based FAQ service the platform
team has scaffolded and extend it to handle the operational concerns
that show up in production — quality measurement, prompt-injection
defense, sensitive-data redaction, cost ceilings, observability, and
self-updating data.

You'll deliver real engineering work: tuning, measuring, instrumenting,
and writing up tradeoffs. You won't be writing the system from scratch
in a week; you'll be running it like it's yours.

## 2. What You Will Build

You will produce evidence for **9 required deliverables**. The starter
implements every layer; your job is to extend or measure each layer in
a specific, graded way. A handful of optional stand-out ideas
(semantic cache, streaming, a third routing tier, cost projection at
scale) are listed at the end — they aren't separately graded but make
for a stronger submission.

Track your progress against this list.

**Required (1–9):**

- [ ] 1. Vector store populated with chunked, embedded products — [Task 1](#task-1--populate-the-vector-database-30-min) 
- [ ] 2. RAG pipeline with structured JSON output **and** a `top_k` sweep — [Task 2](#task-2--rag-pipeline-with-structured-output-45-min) 
- [ ] 3. Tiered model routing via the LLM gateway — [Task 3](#task-3--llm-gateway-with-tiered-routing-20-min) 
- [ ] 4. Automated data ingestion + quarantine — [Task 4](#task-4--automated-data-ingestion-20-min) 
- [ ] 5. Automated evaluation suite (RAGAS) with a data-driven threshold — [Task 5](#task-5--automated-evaluation-suite-45-min) 
- [ ] 6. Input and output guardrails — [Task 6](#task-6--input-and-output-guardrails-125-hours) 
- [ ] 7. Distributed tracing (Phoenix) — [Task 7](#task-7--distributed-tracing-20-min) 
- [ ] 8. Cost monitoring, per-tier summary, and savings vs. baseline — [Task 8](#task-8--cost-monitoring-per-tier-summary-and-savings-analysis-30-min) 
- [ ] 9. Documented, reproducible submission — [Task 9](#task-9--documented-reproducible-submission-30-min) 

**Stand-out (optional, not separately graded):**

- [ ] Semantic caching — [Stand-out: Semantic Cache](#stand-out-semantic-cache)
- [ ] Latency optimization via streaming — [Stand-out: Streaming/TTFT](#stand-out-streamingttft)
- [ ] A third routing tier 
- [ ] Cost projection at scale

For the architecture and the file map, see
[`README.md`](README.md).

## 3. Prerequisites Check

Before you start:

- [ ] **Python 3.11** is available (`python --version`).
- [ ] **`uv`** is installed (the project uses `uv`, not `pip` directly).
  See https://docs.astral.sh/uv/.
- [ ] **Git** is configured.
- [ ] A **Vocareum API key** (prefix `voc-`). The Vocareum Workspace
  provisions one for you — look for it in your Workspace's environment
  variables or under the course resources panel. The course pre-funds
  it; you do not need a personal OpenAI account
  or credit card. A clean run through the rubric on the first try will
  spend roughly $2–$5, leaving comfortable room for re-runs. The
  single most expensive command is `make eval-topk-sweep` (~$0.10);
  treat it as a once-per-submission deliverable rather than something
  to loop on. If you exhaust the budget, contact course support for a
  top-up. (If you happen to be working outside the Workspace with a
  personal OpenAI key, prefix `sk-`, the same $2–$5 estimate applies.)
- [ ] **Tracing**: the project uses **Arize Phoenix** running locally
  inside the FastAPI process — no signup, no Docker, no cloud account
  required. The Phoenix UI is served at http://localhost:6006 once
  `make serve` is up.

## 4. Workspace Setup

The [README](README.md) has the canonical Quick Start. From the project
root:

```bash
make setup            # uv sync — installs all deps
cp .env.example .env  # then fill in your keys (see below)
make load-data        # seed the vector DB from data/products/
make serve            # FastAPI on http://localhost:8080
```

**Udacity Workspace users**: run `make serve-proxy` instead of
`make serve`. The Workspace forwards browser requests under
`/proxy/<port>/`, so the FastAPI dev server (8080) and the embedded
Phoenix UI (6006) both need to know they're mounted under that
prefix; otherwise `/docs` and the Phoenix dashboard render blank in
the browser. Browser URLs are then:
- Swagger UI: `https://<your-workspace-host>/proxy/8080/docs`
- Phoenix UI: `https://<your-workspace-host>/proxy/6006/`

The smoke-test curls below are unaffected, since they hit
`localhost:8080` directly.

Your `.env` needs two values to work in the Vocareum Workspace:

```
OPENAI_API_KEY=voc-...                              # from the Workspace
OPENAI_BASE_URL=https://openai.vocareum.com/v1      # routes calls through the Vocareum proxy
```

The shipped `.env.example` already pre-sets `OPENAI_BASE_URL` to the
Vocareum endpoint, so copying it into `.env` is enough. The
`OPENAI_BASE_URL` line is what tells the OpenAI SDK to send requests
to Vocareum's proxy instead of `api.openai.com` directly — your
`voc-...` key only works against that proxy.

If you happen to be running the project outside the Workspace with a
personal OpenAI key (prefix `sk-...`), use `OPENAI_API_KEY=sk-...`
and either comment out the `OPENAI_BASE_URL` line in `.env` or set
it to an empty value to fall back to OpenAI's default endpoint. The
config layer coerces empty / whitespace-only values to `None`, so
either form works.

Tracing runs entirely in-process. To disable it (e.g. for tests or
debugging), set `TRACING_BACKEND=none`. Otherwise Phoenix launches at
http://localhost:6006 when `make serve` boots.

Smoke-test:

```bash
curl -X POST http://localhost:8080/query \
  -H 'Content-Type: application/json' \
  -d '{"question": "How heavy is the Selkirk AMPED S2?"}'
```

If you see a `QueryResponse` JSON with `answer`, `sources`,
`confidence`, `model`, `tokens`, `cost_usd`, and `trace_id`, the stack
is healthy.

### When do I need to re-run something?

The Workspace persists between sessions, so most setup is one-time.
Below is what's safe to re-run, what's wasteful but harmless, and
what triggers a re-run.

| Command | Re-run when… | Safe to run repeatedly? |
|---|---|---|
| `cp .env.example .env` | The Workspace was reset, or you accidentally deleted `.env`. | **No** — it overwrites your edited `.env` and erases your `OPENAI_API_KEY`. Only run on a fresh clone or after a Workspace reset. |
| `make setup` (`uv sync`) | `pyproject.toml` or `uv.lock` changed. | **Yes** — idempotent. Runs in <1 s when nothing changed. |
| `make install-guardrails-models` | The Workspace was reset, or HuggingFace cache (`~/.cache/huggingface/`) was cleared. | **Yes** — idempotent. Skips already-cached models in seconds. |
| `make load-data` | You edited `data/products/`, or `data/chroma/` was deleted. | **Yes** — `chromadb.upsert` is idempotent on `product_id`. **Caveat**: if you *removed* a product file, `make load-data` will not delete the orphaned row from Chroma. To get a fully clean state, delete `data/chroma/` first, then re-run `make load-data`. |
| `make serve` | The server crashed or the Workspace was reset. | **Yes** — but only one process can bind port 8080 at a time. If you re-run while another is up, the second invocation will fail with "address already in use". The server auto-reloads on changes under `src/`, so you don't need to restart for code edits. |
| `make verify` / `make test` | Anytime — read-only checks. | **Yes** — no side effects. |
| `make seed-cost-log` | You want the cost dashboard to have ≥50 rows for §8. | **Yes** — idempotent. No-ops if the log already has ≥50 entries. |
| `make seed-traces` | You want fresh trace evidence for §7. | **Yes** — appends 10 new traces per run; older traces stay in Phoenix. Costs ~$0.02 per run. |
| `make eval` | You want fresh RAGAS metrics for §5. | **Yes** — but each run costs ~$0.03 and takes ~12 min on the Vocareum proxy. Don't run in a loop. |
| `make eval-topk-sweep` | You want the §2 comparison table. | **Yes**, but it's the heaviest job in the project (~75 min, ~$0.10). Treat as a once-per-submission deliverable. |

**Workspace reset = full re-run.** If Vocareum resets your Workspace
(e.g., session expiry, manual reset), you lose `data/chroma/`,
`data/cost_log.jsonl`, the HuggingFace model cache, and your `.env`
edits. Walk the speedrun again from step 1.

**Manual file deletion** of `data/chroma/`, `data/cost_log.jsonl`, or
the contents of `data/inbox/failed/` is safe — re-running the relevant
make target rebuilds them. Don't delete `data/products/`, `prompts/`,
or anything under `src/` — those are starter assets, not regenerable
state.

### Architecture

The starter is a fully-working RAG service: every layer the course
teaches is wired in. Your job is not to rebuild it — your job is to
**operate, extend, and reason about** it the way an LLM Ops engineer
would on day one in a new role.

Read the architecture diagram in
[`README.md`](README.md) before you start the tasks
below. Pay particular attention to the **How to Extend Each Layer**
table — it tells you exactly which file to edit for the most common
extensions, and several of those are graded tasks.

A quick orientation: the request flow at `POST /query` composes input
guards → cache lookup → classifier → tiered router → traced RAG
pipeline → cost log → output guards → cache store. Each of those is
its own package under `src/`. The standalone wrappers
(`guarded_route_query`, `cached_route_query`) compose the same pieces
in isolation; the HTTP route reproduces the layering inline so the
boundaries are visible at the seam.

## 6. Your Tasks

For each deliverable, the format is:

- **What the starter ships**: what's already there.
- **Your task**: the graded work.
- **How to verify**: commands or checks to confirm your work is done.

### Task 1 — Populate the Vector Database (~30 min)

- **What the starter ships**: `data/products/` has 25 seed products.
  `make load-data` chunks and embeds them and upserts to Chroma.
  `data/products-template.md` has 5 ready-to-edit JSON skeletons
  spanning all four categories — copy a block, fill the
  `// FILL IN: …` placeholders, drop the comments, and save into
  `data/products/`.
- **Your task**: Add **at least 5 new product JSONs** to
  `data/products/`. Use the schema documented in
  `src/ingestion/watcher.py::REQUIRED_FIELDS` (or copy the
  templates in `data/products-template.md`). Re-run `make load-data`.
  Show that retrieval returns one of your new products for an
  unambiguous query.
- **How to verify**:
  ```bash
  make load-data
  curl -X POST http://localhost:8080/query \
    -H 'Content-Type: application/json' \
    -d '{"question": "TODO: a question only a new product can answer"}'
  # The response.sources should include your new product's doc_id.
  ```

### Task 2 — RAG Pipeline With Structured Output (~45 min)

- **What the starter ships**: `POST /query` returns a `QueryResponse`
  with all expected fields populated.
- **Your task** (two parts, both required):
  1. Capture one `POST /query` curl whose response is a full
     `QueryResponse` JSON — every field (`answer`, `sources`,
     `confidence`, `model`, `tokens`, `cost_usd`, `cached`,
     `trace_id`, `blocked_by`) populated, with `sources[]` carrying
     `doc_id`, `chunk_text`, and `similarity_score`.
  2. Run a `top_k` sweep at `top_k ∈ {3, 5, 10}`, report all four
     RAGAS metrics for each setting, name a recommended `top_k`, and
     cite **at least two per-metric deltas** from the sweep table to
     justify the recommendation.
- **Recommended path** (one command, ~5–10 min wall clock):
  ```bash
  make eval-topk-sweep   # runs RAGAS at top_k=3,5,10 and prints a comparison table
  ```
  The output is markdown sized for direct paste into WRITEUP §2.
- **Manual sweep** (if you want to see what the helper does
  internally): `make eval` runs the default `top_k=5`. To sweep
  manually, call `evaluate_pipeline(golden, top_k=N)` from a small
  scratch script — `top_k` is a parameter on both
  `evaluate_pipeline` and `build_eval_dataset` and threads through
  `run_pipeline`.

### Task 3 — LLM Gateway With Tiered Routing (~20 min)

- **What the starter ships**: A 2-tier classifier in
  `src/gateway/classifier.py` routing simple queries to
  `gpt-4o-mini` and complex queries to `gpt-4o`.
- **Your task**: Run a mix of simple ("what's the price of X?") and
  complex ("compare X and Y for a beginner with arm fatigue")
  questions. Capture the `model` field in each response and confirm
  the classifier is making sensible decisions. **Stand-out**: add a
  third tier (e.g., a budget tier) by extending
  `src/pricing.py::MODEL_PRICING` and updating
  `prompts/classifier.j2` to route to it.
- **How to verify** — use these three questions to span the
  classifier's decision space (one clearly simple, one clearly
  complex, one borderline):
  ```bash
  # Simple — single-fact lookup, expect gpt-4o-mini.
  curl -X POST http://localhost:8080/query \
    -H 'Content-Type: application/json' \
    -d '{"question":"What is the weight of the Selkirk AMPED S2?"}' | jq .model

  # Complex — multi-product comparison with subjective tradeoff,
  # expect gpt-4o.
  curl -X POST http://localhost:8080/query \
    -H 'Content-Type: application/json' \
    -d '{"question":"Compare the Selkirk Vanguard Power Air and the JOOLA Hyperion CFS 16 for a player with arm fatigue who wants tournament-grade power."}' | jq .model

  # Borderline — single product but a subjective compound qualifier.
  # The classifier could go either way; capture which it picked and
  # reason about why.
  curl -X POST http://localhost:8080/query \
    -H 'Content-Type: application/json' \
    -d '{"question":"Is the Engage Pursuit MX a forgiving choice for someone who plays casually on weekends?"}' | jq .model
  ```
- **Heads-up about the multi-layer pipeline**: if any of these curls
  returns `model=""` together with a `blocked_by` value mentioning
  `"hallucination"`, the classifier did route to a tier and the LLM
  did generate an answer — but the **output guard** (Task 6's
  hallucination scanner) caught a contradiction with the retrieved
  sources and rewrote the response to the canned refusal. That's the
  layer below the classifier doing its job, not a routing failure.
  Either re-run the curl (the LLM is stochastic, the next attempt may
  not hallucinate) or substitute a different borderline question.
  Note the `blocked_by` value in your §6 evidence; it's a free signal
  that the hallucination guard works end-to-end.

### Task 4 — Automated Data Ingestion (~20 min)

- **What the starter ships**: the inbox watcher runs **in-process**
  inside `make serve` — drop a product JSON in `data/inbox/` and it
  is auto-ingested into the same `chromadb.PersistentClient` the
  `/query` route reads, so new products are queryable within seconds
  with no restart. Bad files move to `data/inbox/failed/` with a
  sibling `.error.txt`. Two ready-to-drop examples live in
  `data/inbox-templates/` — `good.json` (valid; will be ingested) and
  `bad.json` (deliberately malformed; will be quarantined). The
  standalone `make watch` target is still available for offline batch
  ingestion (without the API up), but you do not need it for this task.
- **Your task**: With `make serve` running, drop **at least 3 valid**
  product JSONs and **at least 1 deliberately malformed** one (e.g.,
  missing the `price` field, or larger than 256 KB) into
  `data/inbox/`. The fastest path is to start from
  `data/inbox-templates/{good,bad}.json` and edit copies for variety.
  Confirm the valid products are ingested (queryable via `/query`)
  and the malformed one is quarantined with a `.error.txt`
  explaining why.
- **How to verify**:
  ```bash
  # Terminal A (already running):
  make serve
  # Terminal B:
  cp my_new_product.json data/inbox/
  cp my_broken_product.json data/inbox/
  ls data/inbox/failed/                # broken file ends up here
  cat data/inbox/failed/my_broken_product.json.error.txt
  curl -X POST http://localhost:8080/query \
    -H 'Content-Type: application/json' \
    -d '{"question": "(question targeting the new product)"}'
  ```

### Task 5 — Automated Evaluation Suite (~45 min)

- **What the starter ships**: `make eval` runs RAGAS over
  `data/golden_test_set.csv` and reports the four stable metrics:
  `faithfulness`, `answer_relevancy`, `context_recall`,
  `context_precision`.
- **Your task**: Run `make eval` and capture the aggregate metrics
  table in your writeup. Your §5 must include all four required
  elements (each is a separate fail trigger in the rubric):
  1. **Name the lowest-scoring metric** of the four.
  2. **Propose a plausible cause** grounded in the dataset or the
     pipeline (chunking, retrieval coverage, prompt phrasing, etc.).
  3. **Propose a regression threshold** for at least one named metric
     whose justification cites a descriptive statistic from your eval
     run (median, percentile, or range).
  4. **State the action triggered on violation** (re-run, rollback,
     investigate the most recent retrieval change, etc.).
- **How to verify**:
  ```bash
  make eval
  # capture aggregate metrics in your writeup
  ```
- **What a good threshold proposal looks like** — copy the *shape*,
  not the numbers:

  > We propose `faithfulness ≥ 0.75` as the regression threshold. In
  > our golden-set eval the median faithfulness across 30 questions
  > was 0.84 and the 10th percentile was 0.61. A threshold of 0.75
  > catches degradations of more than ~10 percentage points from
  > typical performance — large enough to indicate a real retrieval
  > or generation regression, small enough to avoid false alarms
  > from per-query stochasticity. **Action on violation:** re-run
  > with the same seed; if still failing, bisect the most recent
  > prompt or retrieval changes.

  A good proposal names the metric, cites the observed distribution
  (median + a tail percentile), justifies the cutoff against that
  distribution rather than a round number, and states what a
  violation triggers. Substitute your own metric and your own
  numbers.

### Task 6 — Input and Output Guardrails (~1.25 hours)

- **What the starter ships**: a **layered** input-guard pipeline at
  `src/guardrails/llm_guard/input_guards.py`. The HTTP route
  calls these by default, and they run two layers in sequence:
  1. A **regex pre-filter** at `src/guardrails/input_guards.py`
     — 8 prompt-injection patterns (`INJECTION_PATTERNS`) and 4
     sensitive-data patterns (`PII_PATTERNS`/`PII_REDACTIONS`). Fast,
     explainable, learner-extensible.
  2. **LLM Guard ML scanners** — DeBERTa for novel injection attacks
     and Microsoft Presidio for entities the regex doesn't enumerate
     (names, addresses).

  The output guard uses an **LLM-judge scanner**
  (`src/guardrails/llm_judge/output_guards.py`) that asks
  gpt-4o-mini whether each answer is supported by the retrieved
  source.
- **Your task**: Add **at least 3 new injection patterns** to
  `INJECTION_PATTERNS` in `src/guardrails/input_guards.py`, OR
  add a new sensitive-data type to `PII_PATTERNS` and `PII_REDACTIONS`
  (e.g., IP addresses, IBAN numbers). Patterns added to the regex
  module fire at the live route via the layered scanner. For each new
  pattern, prove it fires on at least one matching example and does
  NOT fire on at least one legitimate question.
- **How to verify**:
  ```bash
  # Add patterns, then:
  curl -X POST http://localhost:8080/query \
    -H 'Content-Type: application/json' \
    -d '{"question": "(input that should trigger a new pattern)"}' | jq .blocked_by
  curl -X POST http://localhost:8080/query \
    -H 'Content-Type: application/json' \
    -d '{"question": "What paddle is good for beginners?"}' | jq .blocked_by
  ```

#### Hallucination detection

The live `/query` route uses an **LLM-judge scanner** at
`src/guardrails/llm_judge/output_guards.py`: every response triggers an
extra gpt-4o-mini call asking *"does this answer follow from the
source?"* with a structured JSON verdict. On the project's golden
cohort the LLM judge achieves **FPR=0.00, TPR=1.00** — no grounded
answer blocked, every hallucination caught.

Trade-offs:

- **Latency**: +1 LLM call per `/query`, ~1–2s on top of the RAG call.
- **Cost**: ~$0.0002 per request. Cost log gets a second entry per
  request with `query_type="hallucination_check"` for honest accounting.
- **Fail-open**: any judge error (network, rate limit, malformed JSON
  response) returns `None` — the answer flows through unblocked, with a
  WARN log entry. The alternative — false-positive on a network blip —
  is worse for a learner demo.

The previous NLI-based scanner (`src/guardrails/llm_guard/output_guards.py`,
`FactualConsistency` from LLM Guard) is preserved as a teaching
reference. NLI on paragraph-level RAG output has a structural
false-positive problem (40% FPR at the best-tuned threshold), which is
what motivated the swap. The `GUARDRAILS_FACTUALITY_MIN_SCORE` setting
from REQ-018 still exists but is dormant — it only takes effect if you
manually switch the `check_hallucination` import in
`src/gateway/routes.py` back to the NLI module.

To explore the comparison yourself:

- `make eval-llm-judge` — runs the LLM judge against the golden +
  negative cohorts and prints the FPR/TPR/Youden's J table.
- `make tune-factuality` — runs the older NLI threshold sweep (you'll
  see why it doesn't work for product Q&A).

### Task 7 — Distributed Tracing (~20 min)

- **What the starter ships**: Every `POST /query` produces a Phoenix
  trace via `traced_pipeline` in `src/tracing/`. Each response
  carries a `trace_id` you can search on at http://localhost:6006.
  Traces land in the **`llm-ops-capstone`** Phoenix project, not the
  `default` project the UI opens on first load — switch projects via
  the picker in the top-left of the dashboard.
- **Your task**: Run **at least 10 distinct queries**. Open one trace
  in the Phoenix UI (or use `make show-traces` if your workspace
  doesn't expose port 6006). Identify the **slowest step** in the
  pipeline (retrieval? generation? classification?) and quantify the
  bottleneck — what fraction of total request latency is spent there?
- **How to verify**: Either a screenshot of the Phoenix dashboard
  with one trace expanded showing per-step latencies, **or** the
  markdown output of `make show-traces` showing the same trace data.
  Include in your writeup.

### Task 8 — Cost Monitoring, Per-Tier Summary, and Savings Analysis (~30 min)

This task collapses cost dashboard + savings analysis into one
deliverable. Three sub-parts, all required:

- **What the starter ships**: `data/cost_log.jsonl` is appended on
  every request. `GET /cost-dashboard` renders the totals as HTML.
  `scripts/cost_report.py` reads the same log, computes what each
  request would have cost on a single-model baseline (default
  `gpt-4o`), and reports absolute + percentage savings plus a
  per-tier breakdown.
- **Your task**:
  1. **Dashboard + log excerpt.** Get **≥50 entries** into
     `data/cost_log.jsonl`, open `/cost-dashboard`, and screenshot
     it. Paste a 5-line excerpt from `cost_log.jsonl` into the
     writeup to show the entry shape.
  2. **Per-tier summary.** Name, for each model tier present in the
     log, the **number of queries** that hit it and the **average
     per-query cost in dollars**. `make cost-report` prints this
     table; copy it into the writeup. (Missing the query count or
     per-query average for any visible tier fails the rubric row.)
  3. **Savings vs. baseline.** Run `make cost-report` and capture
     the absolute and percentage savings, **explicitly naming the
     baseline model** (the cost report prints it on the
     `Baseline (<model>): ...` line — copy it verbatim).
- **Recommended path to seed the log** (≈30 sec, $0):
  `make seed-cost-log` writes 50 realistic synthetic entries with
  the correct schema and a 70/20/10 simple/complex/judge mix.
  Idempotent — re-runs no-op if the log already has ≥50 rows. Real
  entries from any subsequent `/query` calls are appended on top, so
  this is purely additive.
- **Or do it for real**: run a 50-query bash loop against `/query`.
  Costs ~$0.10 in API spend and takes a few minutes wall-clock.
  ```bash
  for i in $(seq 1 50); do
    curl -X POST http://localhost:8080/query \
      -H 'Content-Type: application/json' \
      -d '{"question": "(rotate through a list)"}' >/dev/null
  done
  ```
- **How to verify**:
  ```bash
  wc -l data/cost_log.jsonl                  # ≥50
  open http://localhost:8080/cost-dashboard  # macOS — or curl + screenshot
  make cost-report                            # prints per-tier table + savings
  ```

### Task 9 — Documented, Reproducible Submission (~30 min)

This is the "is the writeup actually shippable?" check.

- **Your task**:
  1. **WRITEUP.md exists** at the project root with a section for
     each of the 9 required deliverables in numeric order, each
     containing a summary paragraph and the required evidence
     (curls, screenshots, metric tables, log excerpts).
  3. **Tests pass cleanly**: capture the tail of `make test` in the
     writeup showing **≥195 tests passing** and the tail of
     `make verify` showing **0 failed** checks.
  4. **No secrets committed**: `.env` is not tracked; no API keys
     anywhere in committed files. (A real Vocareum or OpenAI key in
     the repo is an instant fail — the reviewer will ask you to
     rotate it.)
- **How to verify**:
  ```bash
  make test       # tail should read "≥195 passed"
  make verify     # 0 failed
  git ls-files | grep -E '(^|/)\.env$'   # empty
  ```

## Stand-out Suggestions

These are not separately graded,
but a submission that picks one or two up and writes them up reads
as a stand-out project.

### Stand-out: Semantic Cache

- **What the starter ships**: A Chroma-backed semantic cache wired
  into the default HTTP route. Cache lookup and store are part of the
  composed request flow in `src/gateway/routes.py`. The cache
  lives in a `cache` collection on the same `PersistentClient` that
  backs the document corpus (`data/chroma/`).
- **Your task**: Run **6 paraphrased questions** about the same
  product (e.g., "How heavy is the Selkirk?", "What's the weight of
  the Selkirk AMPED?", "Selkirk AMPED weight please?"). Confirm at
  least 3 hit the cache (`response.cached == true`). Inspect cache
  contents with:
  ```bash
  uv run python -c "
  import chromadb
  c = chromadb.PersistentClient(path='data/chroma').get_or_create_collection('cache')
  print(f'cache entries: {c.count()}')
  for m in c.get(limit=10)['metadatas']:
      print(m['question'])
  "
  ```
- **Tuning if cache hits are low**: the similarity threshold defaults to
  **0.85** (lowered from 0.95 after an example-run only hit 1/6 paraphrases
  at the stricter value). If fewer than 3 of your paraphrases come back with
  `cached: true`, pass a lower `threshold=` to `lookup(...)` in the
  inspection script above, or edit the default in `src/cache/semantic.py`.
  Phrase your paraphrases so they share concrete tokens with the original
  question (product name, attribute) — embedding similarity rewards lexical
  overlap more than synonym substitution.
- **How to verify**: Six curl outputs (three with `cached: true`) and
  the cache-inspection output above showing the stored questions.

### Stand-out: Streaming/TTFT

- **What the starter ships**: `POST /query/stream` streams Server-Sent
  Events. `compare_ttft` in `src/optimization/streaming.py`
  runs the same query both blocking and streaming.
- **Your task**: Use `compare_ttft` programmatically (or via a small
  script) on **at least 3 questions**. Report the per-question and
  averaged TTFT improvement.
- **Pick uncached questions for the TTFT comparison**: `POST /query/stream`
  bypasses the semantic cache so every paraphrase actually generates tokens.
  Re-running a question on the blocking endpoint can therefore *beat*
  streaming because the blocking path returns a cached answer in
  milliseconds. Either pick 3 questions that have never been asked, or run
  `compare_ttft` against a fresh process where the cache has not been
  warmed.
- **How to verify**:
  ```bash
  uv run python -c '
  from src.optimization.streaming import compare_ttft
  for q in ["q1", "q2", "q3"]:
      print(q, compare_ttft(q))
  '
  ```

## 7. Submission Requirements

Your submission is a **git repository** containing:

1. **Your code changes** to the starter, on a branch you will share
   with the reviewer.
2. **`WRITEUP.md`** at the project root, addressing every required
   deliverable in order. For each, include:
   - One paragraph summarizing what you did.
   - The evidence the rubric requires (curl output, screenshots,
     metric tables, log excerpts).
   - Any tradeoffs or decisions you made and why.
3. **`make test` output** showing all tests still pass (≥195 passing).
4. **`make verify` output** showing the automated checks pass.

What **not** to commit:
- Your `.env` file or any real API keys.
- The full `data/cost_log.jsonl` if it contains tens of MB of data —
  trim to the last 200 entries or summarize.
- Generated artifacts that any reviewer can regenerate
  (`uv.lock` is fine to commit if you changed deps; otherwise leave it).

### Pre-submission checklist

Before you share your branch with the reviewer, walk this list. Every
item should be true:

- [ ] `WRITEUP.md` exists at the project root and addresses every
      required deliverable (1–9) in order.
- [ ] `make test` passes (≥195 tests). Output captured in `WRITEUP.md`.
- [ ] `make verify` reports `0 failed`. Output captured in `WRITEUP.md`.
- [ ] No real secrets committed (`.env` is in `.gitignore`; no keys in
      code, config, or writeup).
- [ ] `data/cost_log.jsonl` is trimmed to the last ~200 entries or
      summarized (don't ship tens of MB of synthetic logs).
- [ ] At least 5 new product JSONs in `data/products/` *or* documented
      ingestion through `data/inbox/` (Deliverable 1).
- [ ] All required steps have evidence in `WRITEUP.md`
      (curl outputs, screenshots, log excerpts, metric tables).
- [ ] If you attempted any stand-out work (semantic cache, streaming
      TTFT, third routing tier, cost projection at scale), its
      evidence is in `WRITEUP.md` too.
- [ ] Branch name and commit SHA are listed in your submission notes
      so the reviewer knows exactly what to clone.

## 8. Hints and Common Pitfalls

- **Phoenix UI shows "no traces" or an empty `default` project.** The
  app registers spans under the **`llm-ops-capstone`** project, not
  `default`. Use the project picker in the top-left of the Phoenix
  dashboard to switch. If you also see stale projects like
  `udacity-llm-ops` or a typo'd `llm-ops-captone` in the dropdown,
  those are remnants from prior runs persisted in `data/phoenix/` and
  can be ignored — your current traces are in `llm-ops-capstone`.
- **`make load-data` complains about an empty Chroma.** Chroma runs
  in-process via `chromadb.PersistentClient`. If `data/chroma/` is
  missing or unwritable, `make load-data` fails. Delete the directory
  and re-run to reset.
- **Vocareum returns `BadRequestError: Insufficient budget available.
  Reason: Exceeded budget 10 > X.X`.** Your Vocareum API key has a
  $10 lifetime cap and you've consumed it. This is **not** a code bug
  — the proxy returns a 400 before any tokens are billed, so the
  failed call costs you nothing. Contact course support for a top-up.
  While you wait, you can continue any work that doesn't make LLM
  calls (writing your WRITEUP, running `make test`, examining traces
  already in Phoenix). Reduce future burn by treating
  `make eval-topk-sweep` (~$0.10) as a once-per-submission deliverable
  and not running `make eval` (~$0.03) in a loop while iterating.
- **`make eval` / `make eval-topk-sweep` prints `TimeoutError` lines.** The
  Vocareum OpenAI proxy is shared, and tail latencies of 30–60 s for a
  single request are common under the parallelism RAGAS uses. RAGAS retries
  each timed-out call transparently, so a noisy log with dozens of
  `TimeoutError` warnings still produces complete metrics — one
  example-solutions run logged ~43 timeouts during the top-k sweep and
  still emitted a clean comparison table. Watch the final summary, not the
  intermediate warnings. If a metric comes back `NaN` (e.g.,
  `context_precision` at `top_k=10`), re-run that single configuration;
  persistent NaN points to genuine retrieval coverage issues, not the proxy.
- **First LLM Guard call hangs for several minutes.** The library
  downloads ~400 MB of HuggingFace transformer models (DeBERTa for
  injection, Presidio NER for PII, BanTopics zero-shot, NLI for
  factuality) on first use. Pre-cache them with
  `make install-guardrails-models`.
- **Brand names show up as `pii_redacted: person` in `/query`
  responses.** Asking about something like the Selkirk AMPED S2 returns
  a normal answer **and** `blocked_by: "pii_redacted: person"` in the
  same response. This is annotation, not a block — the request flowed
  through, the answer is real, and you should treat the response as
  successful. Presidio's NER model flags single capitalized tokens that
  match person-name distributions; brand names like "Selkirk", "Joola",
  and "Diadem" hit this pattern. The `/query` route calls
  `_annotate_pii` (not `_safe_response`) for PII detections, so the
  original answer is preserved. If the annotation becomes noisy in
  your own deployment, you can either drop `PERSON` from Presidio's
  entity list for product domains or add a brand-name allowlist to
  `Anonymize`'s vault — both follow-up exercises beyond the core
  curriculum.
- **Cost-log file grows large.** Each query is a JSON line. After a
  50-query run you'll have ~12 KB of log; that's normal. Don't delete
  the log between Task 8 and Task 9 — they share it.
- **Phoenix UI binds to `0.0.0.0:6006` by default.** Fine on a
  single-user GCP container, but on a multi-tenant or
  internet-reachable host, override `PHOENIX_HOST=127.0.0.1` (or put
  it behind an authenticating reverse proxy) before exposing the box.
- **Tests assume the conftest mocks all external SDKs.** Don't import
  any external SDK at module-import time outside `src/` —
  `tests/conftest.py` patches the constructors of `chromadb`,
  `openai`, `phoenix`, and `llm_guard` scanners before any
  test runs.
- **The classifier falls back to "complex" on bad JSON.** That's the
  safer (more capable, more expensive) default. If your routing
  decisions look skewed toward `gpt-4o`, check whether the classifier
  is actually returning JSON.
- **Forward-dependency rule.** Don't add an `import` from a "later"
  package to an "earlier" one. The fitness function in
  `tests/integration/test_dependency_graph.py` will fail.

Good luck. The system is real; the operational concerns are real.
Treat your writeup like a postmortem for a working production
service — that's the audience.
