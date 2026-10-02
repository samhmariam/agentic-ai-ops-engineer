.PHONY: help setup clean load-data seed-difficulty recall load-data-st recall-st test

# Make `src` importable for scripts and tests run via `uv run python ...`.
export PYTHONPATH := .

# Force uv to copy packages from its cache into the venv instead of hardlinking.
# uv's default is hardlink, which emits a "failed to hardlink" warning and falls
# back to copy when the cache and venv live on different mounts.
export UV_LINK_MODE := copy

# Never let uv download a managed Python interpreter — the shared venv at the
# repo root (or the Workspace image's system Python) already provides one.
export UV_PYTHON_DOWNLOADS := never

# Udacity Workspace (Vocareum) marker: sessions mount the course repo at
# /workspace. Overridable for testing (make setup WORKSPACE=/some/dir).
WORKSPACE ?= /workspace

# Every recipe runs through `uv run --no-project`: uv resolves the shared venv
# and never installs anything.

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Verify the shared environment provides this exercise's dependencies
	@printf '%s\n' \
		'import os' \
		'_s = os.dup(2); os.dup2(os.open(os.devnull, os.O_WRONLY), 2)  # mute onnxruntime C++ init warning (fd-2, matches src/store.py)' \
		'try:' \
		'    import chromadb, openai, tiktoken, docutils, pydantic_settings, dotenv, sentence_transformers, pytest' \
		'finally:' \
		'    os.dup2(_s, 2)  # restore stderr so a genuine ImportError traceback is still visible' \
		| uv run --no-project python - \
		&& echo "OK: environment ready" \
		|| { echo ""; \
		     echo "Dependencies missing. Nothing was installed."; \
		     if [ -d "$(WORKSPACE)" ]; then \
		       echo "This Udacity Workspace should already provide them — do not install anything; please report this."; \
		     else \
		       echo "Add them to the repo-root pyproject.toml with 'uv add' and re-run."; \
		     fi; \
		     exit 1; }

clean: ## Remove generated artifacts (corpus caches + Chroma) for a from-scratch load-data
	rm -rf data/chroma data/scikit-learn-cache data/embedding_cache.jsonl data/CORPUS_VERSION

load-data: ## Ex1 — ingest scikit-learn docs into the `scikit_docs` Chroma collection
	uv run --no-project python scripts/load_data.py

seed-difficulty: ## Upsert 8 deliberately-confusing chunks — run after load-data
	uv run --no-project python scripts/seed_difficulty.py

recall: ## Ex2 — recall@5 + hit@1 on the 12-question golden subset (OpenAI embedder)
	uv run --no-project python scripts/recall_at_5.py

load-data-st: ## Ex3 — rebuild the corpus into `scikit_docs_st` with local MiniLM (run after load-data)
	uv run --no-project python scripts/load_data_st.py

recall-st: ## Ex3 — recall@5 + hit@1 against `scikit_docs_st` (MiniLM embedder)
	uv run --no-project python scripts/recall_at_5_st.py

test: ## Run the unit tests
	uv run --no-project pytest tests/ -q
