.PHONY: help setup serve serve-proxy watch eval load-data install-guardrails-models verify test show-traces tune-factuality eval-llm-judge seed-cost-log seed-traces eval-topk-sweep harvest-evidence cost-report

# Make `src` importable for scripts run via `uv run python scripts/...`.
# (Pytest gets this from `pythonpath = ["."]` in pyproject.toml; scripts don't.)
export PYTHONPATH := .

# Force uv to copy packages from its cache into the venv instead of hardlinking.
# uv's default is hardlink, which is faster on a single filesystem but emits a
# "warning: failed to hardlink file from ..." line and falls back to copy when
# the cache and venv live on different mounts. That happens commonly on the
# Vocareum Workspace ($HOME and the uv cache are different volumes), and the
# warning is confusing for learners. Setting copy here trades a few seconds of
# install time for a clean console.
export UV_LINK_MODE := copy

# Cap RAGAS executor concurrency on `make eval` and `make eval-topk-sweep`.
# Defaults to 1 because the Vocareum proxy throttles parallel judge calls
# under sustained load — observed 8× slowdown and `nan` metric cells on a
# 2026-05-15 dry run with the RAGAS default of 16 workers. Serialization
# trades wall-clock time for completeness. Override with
# `make eval EVAL_MAX_WORKERS=8` on uncontended endpoints where speed matters.
EVAL_MAX_WORKERS ?= 1

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install dependencies with uv
	uv sync

serve: ## Run FastAPI development server
	# --reload-dir scopes the file-watcher to src/ only. Watching the whole
	# project root reload-loops the first time llm-guard's Anonymize scanner
	# triggers spaCy model installs into .venv/.
	uv run uvicorn src.gateway.app:app --reload --reload-dir src --port 8080

serve-proxy: ## Run FastAPI dev server for Udacity Workspace (sets /proxy prefixes so /docs and the Phoenix UI work in the browser)
	# Udacity Workspace forwards browser requests under /proxy/<port>/ but
	# strips that prefix before they reach the app. Both FastAPI (8080)
	# and the embedded Phoenix UI (6006) need to be told they're mounted
	# under that prefix so their HTML/JS bundles fetch assets from the
	# right place:
	#   --root-path /proxy/8080         → Swagger UI at /docs loads its openapi.json
	#   PHOENIX_HOST_ROOT_PATH=/proxy/6006 → Phoenix UI loads its JS/static assets
	# These flags are informational only; the servers still listen on
	# unprefixed paths internally, so all curl-based smoke tests, scripts,
	# and the OTel exporter (localhost:6006/v1/traces) work unchanged.
	# Use plain `make serve` for local development.
	PHOENIX_HOST_ROOT_PATH=/proxy/6006 \
	uv run uvicorn src.gateway.app:app --reload --reload-dir src --port 8080 --root-path /proxy/8080

watch: ## Start file-watcher
	uv run python scripts/start_watcher.py

eval: ## Run evaluation suite (serialized by default; override with EVAL_MAX_WORKERS=N)
	uv run python scripts/run_eval.py --max-workers=$(EVAL_MAX_WORKERS)

load-data: ## Load product data into vector DB
	uv run python scripts/load_data.py

install-guardrails-models: ## Pre-download LLM Guard transformer models (~700MB; optional)
	# Mirrors what `src/guardrails/llm_guard/{input,output}_guards.py`
	# instantiate at module import. Anonymize is overridden to
	# `dslim/bert-base-NER` (MIT) to avoid the CC-BY-NC Ai4Privacy
	# default; keep this in sync with input_guards.py. FactualConsistency
	# is omitted on purpose — the live /query route uses the LLM judge
	# (src/guardrails/llm_judge/) and the NLI scanner is lazy-loaded only
	# when the comparison module explicitly invokes it.
	# Routes through src.guardrails.llm_guard.input_guards so the
	# ALL_SUPPORTED_LANGUAGES monkey-patch (English-only) runs before
	# Anonymize spins up Presidio's nlp_engine. Importing llm_guard
	# directly here would re-trigger the zh_core_web_sm + spacy-pkuseg
	# auto-download.
	uv run python -c "from src.guardrails.llm_guard.input_guards import _injection_scanner, _anonymize_scanner; from src.guardrails.llm_guard.output_guards import _topic_scanner"
	# spaCy NER model (en_core_web_sm) is declared as a URL-pinned
	# wheel in pyproject.toml, so `uv sync` installs it directly.
	# No `python -m spacy download` needed here.

test: ## Run the unit + integration test suite
	uv run pytest tests/ -q

verify: ## Run the capstone verification checklist
	uv run python scripts/verify_capstone.py

show-traces: ## Export recent Phoenix traces as markdown (rubric §7 fallback)
	uv run python scripts/show_traces.py

tune-factuality: ## Empirically tune the FactualConsistency threshold against the golden + negative cohorts
	uv run python scripts/tune_factuality_threshold.py

eval-llm-judge: ## Calibrate the LLM-judge hallucination scanner against the golden + negative cohorts
	uv run python scripts/eval_llm_judge.py

seed-cost-log: ## Seed data/cost_log.jsonl with 50 realistic synthetic entries (idempotent, $0)
	uv run python scripts/seed_cost_log.py

seed-traces: ## Run 10 diverse /query calls and print rubric §7 markdown + slowest-step (requires `make serve`)
	uv run python scripts/seed_traces.py

eval-topk-sweep: ## Run RAGAS at top_k=3,5,10 and print a §2 comparison table (~3× the cost of make eval; serialized by default)
	uv run python scripts/eval_topk_sweep.py --max-workers=$(EVAL_MAX_WORKERS)

cost-report: ## Run the cost savings analysis report (rubric §9 — tiered vs. baseline)
	uv run python scripts/cost_report.py

harvest-evidence: ## Cross-cutting WRITEUP harness — runs every §1–§11 evidence step, writes WRITEUP-draft.md
	uv run python scripts/harvest_evidence.py
