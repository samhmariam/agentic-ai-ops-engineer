# WRITEUP — Production LLM FAQ Service

> **How to use this template.** Copy this file to `WRITEUP.md` (drop
> the `.template`) and fill in each section with the evidence the
> rubric requires. Keep evidence inline (curl outputs, screenshots,
> log excerpts) — a reviewer should be able to grade your submission
> from this file alone.
>
> **Recommended path:** with `make serve` running in another terminal,
> run `make harvest-evidence` to generate `WRITEUP-draft.md` with §1–§8
> mostly pre-populated. Copy that draft into `WRITEUP.md` and fill in
> the analysis blocks the harvester leaves as `<!-- TODO: learner — … -->`
> placeholders (the §2 top-k recommendation, the §5 threshold proposal,
> the §7 slowest-step analysis, the §8 baseline-cost interpretation,
> plus the §1 curl using one of YOUR new products). The harvester
> captures pure-evidence sections; the writing remains yours.
>
> Aim for ~1,500–3,000 words. Longer is fine if you include images.
> Each `## Deliverable N` section maps to one row of
> [`rubric.md`](rubric.md).

## Setup snapshot

- Python: `python --version`
- Branch / commit: `git rev-parse --short HEAD` (the commit your
  reviewer should clone)
- Test suite: `make test` (paste the final line — should be ≥195
  passing)
- Verify: `make verify` (paste the "Automated: X passed, 0 failed"
  line)

## Substitutions from the proposal

The starter ships with three substitutions vs. the proposal text. If
you used the as-shipped stack (the default), just say so. If you swapped
back to the proposal stack (Redis Stack / Langfuse / Guardrails AI),
explain what you changed and why.

| Layer | Proposal | Starter default | Your choice |
|-------|----------|------------------|--------------|
| Cache | Redis Stack | Chroma collection | _your choice_ |
| Tracing | Langfuse Cloud | Phoenix in-process | _your choice_ |
| Guardrails | Guardrails AI | LLM Guard + LLM judge | _your choice_ |

---

## Deliverable 1 — Vector Store Populated

> **Rubric:** at least 5 new product JSONs in `data/products/` (or proof
> of equivalent ingestion through `data/inbox/`). Output of one `POST
> /query` whose `sources[].doc_id` matches at least one of the new
> products.

- New products added (list filenames or `doc_id`s):
- One curl response showing retrieval includes a new product:

```json
// paste POST /query response with `sources[*].doc_id` matching one of your additions
```

## Deliverable 2 — RAG Pipeline With Structured Output + Top-k Sweep

> **Rubric:** one `POST /query` response showing every `QueryResponse`
> field; one top-k sweep covering `top_k ∈ {3, 5, 10}` with all four
> RAGAS metrics per setting; a recommended `top_k` value whose
> justification cites at least two per-metric deltas from the sweep
> table.

### Part A — Structured-output curl

A representative `POST /query` response with every field populated
(`answer`, `sources`, `confidence`, `model`, `tokens`, `cost_usd`,
`cached`, `trace_id`, `blocked_by`), and `sources[*]` containing
`doc_id`, `chunk_text`, and `similarity_score`:

```json
// paste here
```

### Part B — Top-k sweep

Output of `make eval-topk-sweep`:

| top_k | faithfulness | answer_relevancy | context_recall | context_precision |
|------:|-------------:|-----------------:|---------------:|------------------:|
|     3 | ?.??? | ?.??? | ?.??? | ?.??? |
|     5 | ?.??? | ?.??? | ?.??? | ?.??? |
|    10 | ?.??? | ?.??? | ?.??? | ?.??? |

- **Recommended `top_k`:** ___
- **Per-metric deltas cited** (at least two):
  - Δ <metric_a> from top_k=__ to top_k=__: ___
  - Δ <metric_b> from top_k=__ to top_k=__: ___
- **Why this `top_k`** (one paragraph weighing the deltas — e.g.,
  recall improves at top_k=10 but precision drops, so we accept the
  precision hit because hallucinations are bounded by §6 guardrails):

## Deliverable 3 — Tiered Model Routing

> **Rubric:** three or more `POST /query` outputs covering at least
> one simple-fact and one complex / multi-product question; the
> `model` field differs across captured outputs; the writeup names
> the classification each query received.

| Query | classification | model |
|-------|---------------|-------|
| ... (simple)     | simple   | gpt-4o-mini |
| ... (complex)    | complex  | gpt-4o |
| ... (borderline) | _your call_ | _captured_ |

(Pull these from `data/cost_log.jsonl` or from `POST /query`
responses.)

## Deliverable 4 — Automated Data Ingestion + Quarantine

> **Rubric:** two artifacts — a successful ingestion (new product
> visible in `POST /query` `sources`) and a quarantined failure with
> `<name>.error.txt`.

- Successful ingestion: drop a valid JSON in `data/inbox/`, then run a
  `POST /query` whose `sources` cites the new product. Paste both
  files / responses.
- Quarantined failure: drop a malformed JSON, then paste the
  `data/inbox/failed/<name>.error.txt` content.

## Deliverable 5 — Automated Evaluation Suite + Threshold

> **Rubric:** `make eval` aggregate table with all four RAGAS metrics;
> name the lowest-scoring metric and propose a plausible cause;
> propose a regression threshold for at least one named metric whose
> justification cites a descriptive statistic (median / percentile /
> range) from the eval run and states the action triggered on
> violation.

### Aggregate metrics

```
faithfulness:      ?.???
answer_relevancy:  ?.???
context_recall:    ?.???
context_precision: ?.???
```

### Analysis (all four bullets required)

- **Lowest-scoring metric:** ___
- **Plausible cause** (grounded in the dataset or the pipeline —
  chunking, retrieval coverage, prompt phrasing, judge model
  behavior, etc.): ___
- **Regression threshold for [metric]:** [value], justified by
  [descriptive stat from this run — e.g., "median was 0.84 across
  30 questions, 10th percentile was 0.61, so a 0.75 cutoff catches
  ≥10pp degradations without false alarms on per-query stochasticity"]
- **Action on violation:** ___ (re-run with same seed / rollback the
  latest prompt change / bisect the most recent retrieval change /
  page on-call / etc.)

## Deliverable 6 — Input and Output Guardrails

> **Rubric:** add at least 3 new patterns to `INJECTION_PATTERNS` or
> a new sensitive-data type to `PII_PATTERNS`/`PII_REDACTIONS`. Per
> added pattern, include paired curls: one that triggers it
> (`blocked_by` populated) and one that should not.

- Patterns added (list with one-line description each):
- Paired curl examples per added pattern:

```bash
# Pattern X — should fire
curl -X POST http://localhost:8080/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"<input that should trigger>"}' | jq .blocked_by
# Expected: "prompt_injection: ..." or "pii_redacted: ..."

# Pattern X — should NOT fire
curl -X POST http://localhost:8080/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"<legitimate question>"}' | jq .blocked_by
# Expected: null
```

## Deliverable 7 — Distributed Tracing

> **Rubric:** ≥10 `POST /query` requests; one Phoenix screenshot
> (`llm-ops-capstone` project, retrieval + classification +
> generation spans visible and labeled) OR `make show-traces`
> markdown; name the slowest pipeline step and quantify it as a
> fraction of total request latency.

- Either a Phoenix screenshot (with one trace expanded) **or** the
  `make show-traces` markdown output for ≥10 queries.
- Slowest step in your traces:
  - Step name: ___
  - Latency: ___ ms
  - Fraction of total request latency: ___ % (computed from the span
    durations)
  - One sentence on why it's the slowest (cache effect, model size,
    prompt length, etc.): ___

## Deliverable 8 — Cost Monitoring, Per-Tier Summary, and Savings

> **Rubric:** `data/cost_log.jsonl` ≥50 entries with a 5-line excerpt
> + `/cost-dashboard` screenshot; per-tier summary table (query count
> + average per-query cost in dollars for every tier visible in the
> log); `make cost-report` output with absolute savings, percentage
> savings, **and a named baseline model**.

### Part A — Cost log + dashboard

- Total entries: `wc -l data/cost_log.jsonl` → ___
- 5-line excerpt:

```
// paste 5 lines from data/cost_log.jsonl
```

- Screenshot (or paste) of `GET /cost-dashboard`:

### Part B — Per-tier summary

| Model tier | Query count | Avg cost / query (USD) |
|------------|------------:|-----------------------:|
| gpt-4o-mini | __ | $__ |
| gpt-4o | __ | $__ |
| (judge — if present) | __ | $__ |

(Copy directly from `make cost-report` — the "Per-tier summary"
block prints the table verbatim.)

### Part C — Savings vs. baseline

`scripts/cost_report.py` output:

```
// paste — must include the "Baseline (<model>): ..." line
```

- **Baseline model used:** ___ (copy the name from the cost-report output)
- **Absolute savings:** $___
- **Percentage savings:** ___ %
- One sentence interpreting the savings (e.g., "the 70/20/10 mix
  favors gpt-4o-mini heavily, so most of the savings comes from
  the simple-question class"): ___

## Deliverable 9 — Submission Quality

> **Rubric:** `WRITEUP.md` exists with a section per required
> deliverable in numeric order; `make test` ≥195 passing; `make verify`
> 0 failed; no `.env` or API keys committed.

- Tail of `make test`:

```
// paste — should end with "N passed" where N ≥ 195
```

- Tail of `make verify`:

```
// paste — should end with "Automated: X passed, 0 failed"
```

- `.env` is gitignored (paste output of `git ls-files | grep -E '(^|/)\.env$'`,
  which should be empty): ___
- No API keys appear in committed files (a quick `git grep -E 'voc-[A-Za-z0-9]|sk-[A-Za-z0-9]'`
  returns nothing): ___

---

## Appendix — Stand-out Work (optional)

The rubric grades nine required rows; the work below is not
separately graded but distinguishes a stand-out submission. Fill in
only what you tackled; remove the rest.

### Stand-out: Semantic Cache

> Six paraphrased queries showing ≥3 cache hits, plus the cache
> contents.

- Six paraphrased queries with their `cached` field per response:
- `chromadb.PersistentClient(path='data/chroma').get_or_create_collection('cache').count()`:
- `.get(limit=10)['metadatas']` excerpt:

### Stand-out: Streaming / TTFT

> `compare_ttft` output for at least 3 queries with TTFT improvement
> percentage.

```
// paste compare_ttft output
```

### Stand-out: Third Routing Tier

> Show one query landing on each of the three tiers after extending
> `MODEL_PRICING` and `prompts/classifier.j2`.

### Stand-out: Cost Projection at Scale

> Model a higher-volume scenario (e.g., 10,000 queries/day at the
> observed tier mix) and discuss what would change at scale (rate
> limits, cache pressure, eval cadence, on-call cost ceilings).

---

## Lessons learned (optional)

> Reflect on which layer was the hardest to extend and what you
> would do differently in a real production system (cost ceilings,
> auth, multi-tenancy, etc.). One or two paragraphs.
