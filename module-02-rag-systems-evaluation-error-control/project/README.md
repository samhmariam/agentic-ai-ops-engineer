# ThirdShotHub LLM FAQ Service

A production-style RAG product Q&A service for a pickleball e-commerce
catalog. This is the Module 02 capstone of the Agentic AI Ops Engineer
nanodegree.

| Document | What it holds |
|---|---|
| [`WRITEUP.md`](WRITEUP.md) | The submission: Deliverables 1–9 with evidence, decisions and tradeoffs |
| [`EVIDENCE.md`](EVIDENCE.md) | The raw evidence log behind the writeup |
| [`FUTURE_WORK.md`](FUTURE_WORK.md) | Planned stand-out features and the improvement backlog |
| [`INSTRUCTIONS.md`](INSTRUCTIONS.md) | Course task instructions |

## Project Summary

You're an LLM Operations Engineer at ThirdShotHub, a mid-size e-commerce
company specializing in pickleball gear and apparel that's replacing its
static FAQ page with an LLM-powered product Q&A service.

The existing FAQ page is outdated, doesn't scale, and can't answer questions
about specific products. Customer support tickets are piling up with
questions that could be answered straight from product documentation.

Your job is to build a production-ready RAG-based FAQ service that answers
customer questions using the product catalog, routes queries cost-efficiently
between model tiers, maintains measurable answer quality, and updates
automatically as new products are added.

The system has to handle real-world concerns: off-topic queries, PII in
customer messages, hallucinated product features, and cost management across
multiple LLM providers.

## Architecture at a Glance

```text
                   ┌────────────────────────────────────────────────┐
   HTTP request    │                FastAPI app                     │
   ──────────────► │  src/gateway/app.py                            │
                   │    │                                           │
                   │    ├── POST /query    src/gateway/routes.py    │
                   │    ├── POST /query/stream                      │
                   │    │                  src/optimization/routes.py
                   │    └── GET  /cost-dashboard                    │
                   │                       src/cost/dashboard.py    │
                   └────────────────────────────────────────────────┘
                                          │
   POST /query flow (composed in routes.py):                        ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ 1. detect_prompt_injection      src/guardrails/input_guards.py   │
   │       └── short-circuit on match → safe response (blocked_by)    │
   │ 2. detect_pii (redact)          src/guardrails/input_guards.py   │
   │ 3. cache_lookup                 src/cache/semantic.py            │
   │       └── on hit: return cached response                         │
   │ 4. classify (gpt-4o-mini)       src/gateway/classifier.py        │
   │ 5. select_model + traced_pipeline  src/gateway/router.py +       │
   │                                 src/tracing/phoenix_backend.py   │
   │ 6. retrieve (Chroma)            src/rag/retriever.py             │
   │ 7. generate (OpenAI chat)       src/rag/generator.py             │
   │ 8. log_request (cost)           src/cost/tracker.py              │
   │ 9. check_hallucination + is_off_topic                            │
   │                                 src/guardrails/output_guards.py  │
   │ 10. cache_store                 src/cache/semantic.py            │
   └──────────────────────────────────────────────────────────────────┘

   Sidecar process (independent of HTTP):
                            ┌────────────────────────────────────┐
                            │ data/inbox/*.json  →  watcher.py   │
                            │   src/ingestion/watcher.py         │
                            │   chunks → embeds → upserts to     │
                            │   Chroma; quarantines bad files    │
                            └────────────────────────────────────┘
```

### As built: where the code differs from the diagram

The diagram above is the reference architecture. The code on `main`
differs in these details, checked against the imports in
`src/gateway/routes.py` and `src/gateway/app.py` on 2026-10-07:

| Step | Diagram | As built |
|---|---|---|
| 1–2 Input guards | `src/guardrails/input_guards.py` | `routes.py` imports the **layered** `src/guardrails/llm_guard/input_guards.py`. The regex pre-filter in `src/guardrails/input_guards.py` runs first (14 `INJECTION_PATTERNS`, including 3 added in Deliverable 6). On a miss it falls through to DeBERTa (`PromptInjection`) for injection and Presidio (`Anonymize`) for PII. |
| 4 Classify | `gpt-4o-mini`, 2 tiers | Still `gpt-4o-mini`, but with **3 tiers**: `budget` → `gpt-4.1-nano`, `simple` → `gpt-4o-mini`, `complex` → `gpt-4o`, mapped by `MODEL_*` in `.env` (Deliverable 3 stand-out). |
| 9 Output guards | `src/guardrails/output_guards.py` | `routes.py` imports from `src/guardrails/llm_judge/output_guards.py`. `check_hallucination` is a `gpt-4o-mini` judge, with an extra cost-log row (`hallucination_check`). `is_off_topic` is LLM Guard `BanTopics`, a zero-shot RoBERTa model. The older NLI scanner in `src/guardrails/llm_guard/output_guards.py` is kept as a reference. |
| Watcher | Sidecar process, independent of HTTP | Started **in-process** by the FastAPI `lifespan` in `src/gateway/app.py`, so `data/inbox/` drops land in the same Chroma client `/query` reads, with no restart. `make watch` (`scripts/start_watcher.py`) remains for offline batch ingestion. |
| Tracing scope | Step 5 | Only steps 6–7 sit inside the `rag_query` root span. The classifier, judge and cache embeddings appear as separate root traces, and the guards are untraced (Deliverable 7; backlog B3 in `FUTURE_WORK.md`). |

## Running it

Run all commands from this directory. They need a `.env` copied from
`.env.example` with `OPENAI_API_KEY` set; `OPENAI_BASE_URL` defaults to the
Vocareum endpoint.

```bash
make load-data   # chunk, embed and upsert data/products/*.json into Chroma
make serve       # FastAPI on :8080 + in-process inbox watcher + Phoenix on :6006
make test        # 242 tests
make verify      # automated capstone checks
make eval        # RAGAS over data/golden_test_set.csv
make cost-report # tiered vs gpt-4o baseline savings
```

**On Windows without GNU `make`,** run each target's recipe directly, with
`PYTHONPATH=.` and `PYTHONUTF8=1` set. For example, `make test` becomes
`uv run pytest tests/ -q`. See `EVIDENCE.md` → *Environment notes* for the
other local settings.
