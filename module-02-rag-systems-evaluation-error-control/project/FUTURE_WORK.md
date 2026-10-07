# Future Work: Stand-out Features and Improvement Backlog

This file tracks feature upgrades and improvements for the LLM FAQ service
that are planned but not yet done. Part 1 is the course's stand-out
suggestions, with their status. Part 2 is a backlog of issues found while
building and measuring the capstone. Evidence references point to
[`WRITEUP.md`](WRITEUP.md) and [`EVIDENCE.md`](EVIDENCE.md).

Last updated: 2026-10-07.

## Status at a glance

| # | Item | Status |
|---|---|---|
| S1 | Third routing tier (budget) | **Done.** See WRITEUP Appendix and §3. |
| S2 | Semantic cache: 6 paraphrases, cache inspection, threshold sweep | **To do** |
| S3 | Streaming / TTFT via `compare_ttft` | **To do** |
| S4 | Cost projection at scale | **Done** at the observed mix (WRITEUP Appendix). Revisit after S2 (cache hit rate). |
| B1–B12 | Improvement backlog (Part 2) | **To do**, prioritised below |

---

## Part 1 — Stand-out suggestions

These are not separately graded, but picking up one or two and writing them
up is what makes a submission stand out. When one is finished, add a
"Stand-out: …" subsection to the WRITEUP Appendix and log the raw output in
EVIDENCE.md.

### S1. Third routing tier: DONE

> Extend `src/pricing.py::MODEL_PRICING` with a budget tier and update
> `prompts/classifier.j2` so the classifier routes to it; show one query
> landing on each of the three tiers.

Delivered on 2026-10-07:

- **Tier:** a `budget` tier served by `gpt-4.1-nano` ($0.10 / $0.40 per 1M
  tokens).
- **Code:** `MODEL_BUDGET` in `.env` and `.env.example`, a 3-label
  classifier prompt with a "choose the higher tier" tie-break, `budget` in
  the router and the cost tracker, and tests.
- **Evidence:** one query per tier, plus 27/27 consistent classifier labels.

**Possible follow-ups:**

- Skip the classifier call for obvious single-value lookups using a cheap
  heuristic. The classifier costs about half a nano answer and adds about
  1.5 s.
- Flush or version the semantic cache when routing config changes. Cached
  responses keep reporting their old tier for up to the 1-hour TTL.

### S2. Semantic cache: TO DO

> Run 6 paraphrased questions about the same product and confirm at least 3
> hit the cache (`cached: true`); inspect the cache collection. Sweep the
> similarity threshold (0.85, 0.90, 0.95) and discuss the hit-rate vs.
> answer-quality tradeoff with a false-positive example.

**What the starter ships.** A Chroma-backed semantic cache wired into the
default `/query` route (`src/gateway/routes.py`). It lives in a `cache`
collection on the same `PersistentClient` as the corpus (`data/chroma/`).

- `src/cache/semantic.py::lookup(question, *, threshold=0.85)` is a cosine
  similarity lookup against the redacted question.
- `src/cache/semantic.py::store(question, response, *, ttl_s=3600)` stores
  the full `QueryResponse`. TTL is enforced lazily on read.

**Plan:**

1. **Send 6 paraphrases about one product** that share concrete tokens with
   the original (product name and attribute). Embedding similarity rewards
   lexical overlap more than synonyms. For example:
   - "What is the weight of the Selkirk AMPED S2?" (primes the cache)
   - "How heavy is the Selkirk AMPED S2?"
   - "What's the weight of the Selkirk AMPED?"
   - "Selkirk AMPED S2 weight please?"
   - "How much does the Selkirk AMPED S2 weigh?"
   - "Weight of the Selkirk AMPED S2 paddle?"

   Use a product that hasn't been asked about in the last hour, or the first
   question may itself be a cache hit.
2. **Record `cached` from each response.** The target is at least 3 with
   `cached: true`.
3. **Inspect the cache:**

   ```bash
   uv run python -c "
   import chromadb
   c = chromadb.PersistentClient(path='data/chroma').get_or_create_collection('cache')
   print(f'cache entries: {c.count()}')
   for m in c.get(limit=10)['metadatas']:
     print(m['question'])
   "
   ```

4. **Sweep the threshold** at 0.85, 0.90 and 0.95 by calling
   `lookup(q, threshold=…)` directly in a script, not by editing the default.
   For each paraphrase, record the similarity to the cached entry and whether
   it hits at each threshold.
5. **Find a false-positive example:** two questions that cross the threshold
   but need *different* answers. Good candidates differ only in the
   attribute ("weight" vs "price" of the same product), or are near-name
   products such as the "Franklin X-26" (`prod_011`) vs "Franklin X-40"
   (`prod_008`). Show the wrong cached answer that would be served.
6. **Discuss the tradeoff.** A lower threshold means more hits, so lower cost
   and latency, but a higher risk of serving the wrong answer. Recommend a
   value with evidence.

**How to verify:** six curl outputs (at least three with `cached: true`),
the cache-inspection output, and a threshold × hit-rate table.

**Known pitfalls:**

- **Any hit carries the original response,** including its `model`,
  `trace_id` and `cost_usd`. Cache hits write no cost-log line and no new
  trace.
- **The cache stores responses only after the output guards pass.** Blocked
  answers are never cached.
- **Use `http://127.0.0.1:8080`, not `localhost`, on Windows.** The
  `localhost` IPv6 fallback adds about 2 s per request on the client side.

### S3. Streaming / TTFT: TO DO

> Use `compare_ttft` on at least 3 uncached questions, report the
> per-question and averaged TTFT improvement, and discuss when streaming is
> not worth the plumbing.

**What the starter ships.** `POST /query/stream` (Server-Sent Events) in
`src/optimization/routes.py`. `src/optimization/streaming.py::compare_ttft(question,
model=None, top_k=5)` runs the same query in blocking and streaming mode. It
returns `{"blocking": {...}, "streaming": {...}, "ttft_improvement_ms": …}`,
where each mode has `ttft_ms`, `total_ms` and `total_tokens`.

**Plan:**

1. **Pick at least 3 questions that have never been asked.**
   `/query/stream` bypasses the semantic cache, but the blocking path does
   not. A warm cache would make blocking "win" in milliseconds. Mix answer
   lengths: one budget-length lookup and two long `gpt-4o`-style
   comparisons. TTFT gains should grow with answer length.
2. **Run:**

   ```bash
   uv run python -c '
   from src.optimization.streaming import compare_ttft
   for q in ["q1", "q2", "q3"]:
       print(q, compare_ttft(q))
   '
   ```

3. **Report** blocking TTFT, streaming TTFT, the improvement in ms and %
   per question, the average, and total time for both modes. Total time
   should be roughly equal; streaming only moves the *first* token earlier.
4. **Discuss when streaming isn't worth the plumbing:**
   - short single-value answers (the `budget` tier), where TTFT is about
     equal to total time
   - cache hits
   - clients that need the whole JSON (`sources`, `confidence`,
     `blocked_by`) before rendering
   - **output guards.** The hallucination judge and `BanTopics` need the
     complete answer, so a streamed answer is shown *before* it is checked.
     That is a real safety tradeoff for this pipeline.

**How to verify:** the `compare_ttft` output for 3 questions plus an
averaged table.

### S4. Cost projection at scale: DONE (revisit after S2)

Delivered in the WRITEUP Appendix for 10,000 queries/day at the observed
mix:

- **Tiered:** about $25.8/day (about $774/month), against **$48.5/day** for
  a `gpt-4o` baseline. That is about 47% savings.
- **Discussion covered:** rate limits (3 chat + 3 embedding calls per
  request), CPU-bound guard throughput, eval cadence, and alerting on the
  `complex` share.

**Follow-up:** once S2 gives a measured cache hit rate, add a
cache-adjusted scenario, because hits cost $0 in LLM spend. Also model
cache-collection growth, which Chroma currently never evicts except through
lazy TTL deletes on read.

---

## Part 2 — Improvement backlog

These are issues and opportunities found while measuring the system. Each
links to the evidence that surfaced it. Priority is a rough judgement of
impact against effort.

### Latency and observability

| ID | Improvement | Evidence | Priority |
|---|---|---|---|
| B1 | **Make the `BanTopics` off-topic guard cheaper.** It is the slowest step end to end: 26.6% of latency on average, up to 40% on long answers, because it is a CPU zero-shot RoBERTa that scales with answer length. Options: score a truncated answer, run it concurrently with the hallucination judge, fold the off-topic check into the judge prompt, or use a GPU. | WRITEUP §7 | High |
| B2 | **Embed the question once per request.** It is currently embedded three times (cache lookup, retrieval, cache store), which costs 18.8% of latency. Pass one vector through all three. | WRITEUP §7 | High |
| B3 | **Use one root span per request with labelled children.** Wrap the `/query` handler in a root span with `classification`, `retrieval`, `generation` and `guard` child spans. Today one request produces 5 disconnected traces, and about 35% of latency is untraced. Also drop or fix `rag_generation`, which is opened after the pipeline returns and always shows 0.0 ms. | WRITEUP §7 | Medium |
| B4 | **Run the classifier concurrently with the cache lookup,** or skip it for obvious lookups. It adds about 1.5 s per request. | WRITEUP §7, §3 | Medium |

### Retrieval and evaluation quality

| ID | Improvement | Evidence | Priority |
|---|---|---|---|
| B5 | **Add a structured path for superlative and catalog-wide questions** ("cheapest", "widest", "most expensive", "which paddles have X"). Top-5 embedding similarity misses the answer chunk: rows 20, 27 and 29 score 0 precision and 0 recall. Use metadata filtering or sorting (price is already in chunk metadata), or a SQL-style tool. | WRITEUP §5 | High |
| B6 | **Keep the golden set current.** Row 6 ("What shoes do you carry?") still lists 3 shoes, but the catalog now has 5. Update ground truth whenever the catalog changes, ideally in the ingestion PR. | WRITEUP §5 | Medium |
| B7 | **Adjust context_precision scoring for comparisons.** RAGAS judges each chunk alone, so two-product comparisons score 0 even with perfect retrieval (rows 3 and 22). Consider multi-product chunks, or report comparison questions separately. | WRITEUP §5 | Low |
| B8 | **Wire the §5 thresholds into CI** (context_precision mean ≥ 0.66, faithfulness mean ≥ 0.80), diffing per-row results against `data/eval/eval_results_2026-10-07.json`. Re-baseline after B5 and B6. | WRITEUP §5 | Medium |

### Guardrail accuracy

| ID | Improvement | Evidence | Priority |
|---|---|---|---|
| B9 | **Fix the DeBERTa false positive.** It blocks the legitimate follow-up "Can you repeat the price of the paddle you mentioned above?" (`risk_score=1.000`). Regex can't fix this because the layers are OR-ed. Tune the threshold, or add an allow-list layer, with a measured false-positive and true-positive study. | WRITEUP §6 | Medium |
| B10 | **Fix the Presidio false positive on brand names.** "Goodyear" in "Which pickleball shoe has a Goodyear rubber outsole?" is tagged as a PERSON and redacted (`blocked_by: "pii_redacted: person"`). Add a deny-list of catalog brands, or use a confidence threshold for PERSON. | EVIDENCE §1 | Low |
| B11 | **Review LLM-judge errors.** The judge rejected a correct claim that two paddles are both 8.0 in wide (FPR 0.03 in `make eval-llm-judge`). It also blocked "Which paddle has a raw Toray T700 carbon fiber face?", which hasn't been checked yet. Collect judge false positives into a regression set. | WRITEUP §6 | Low |

### Cost accounting

| ID | Improvement | Evidence | Priority |
|---|---|---|---|
| B12 | **Make cost reporting like-for-like.** Log classifier calls (about $0.000056 each, currently invisible). Add a `cost_report.py` option to keep `hallucination_check` rows at their actual model in the baseline. As shipped, the report shows 68.9% savings, against about 47% like for like. | WRITEUP §8 | Medium |

### Suggested order

1. **S2 and S3 first.** They are cheap, self-contained stand-outs with no
   production code changes.
2. **Then B2 and B1,** the largest latency wins.
3. **Then B5 + B6 + B8,** fixing retrieval quality and then locking it in
   with CI thresholds.
4. **The rest as needed.**
