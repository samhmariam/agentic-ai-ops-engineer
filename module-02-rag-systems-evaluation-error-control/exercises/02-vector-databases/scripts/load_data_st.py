"""MiniLM rebuild into a parallel ``scikit_docs_st`` collection.

Usage (from the starter root, after ``make load-data`` has cloned the corpus):
    PYTHONPATH=. uv run python scripts/load_data_st.py
    # or: make load-data-st

A Chroma collection's dimension is fixed by its first insert, so the
384-dim MiniLM vectors cannot go into the 1536-dim ``scikit_docs``
collection. This builds a separate collection from the same chunks
(``src.chunker.chunk_doc`` is embedder-agnostic) and leaves the OpenAI
collection intact for comparison. Cost: $0 — the model runs locally.
"""

import time
from pathlib import Path

from src import store
from src.chunker import chunk_doc
from src.corpus import load_corpus

COLLECTION = "scikit_docs_st"
REPO_CACHE_DIR = Path("data/scikit-learn-cache")
UPSERT_BATCH_SIZE = 500


def main() -> None:
    if not (REPO_CACHE_DIR / ".git").exists():
        raise SystemExit(f"{REPO_CACHE_DIR} missing — run `make load-data` first to clone the corpus.")

    start = time.monotonic()
    unique: dict[str, dict] = {}
    for section in load_corpus(REPO_CACHE_DIR, "manual"):
        for c in chunk_doc(section):
            unique.setdefault(c["chunk_id"], c)  # first-wins dedup, mirrors scripts/load_data.py
    chunks = list(unique.values())
    print(f"[load_data_st] parsed {len(chunks)} chunks in {time.monotonic() - start:.1f}s")

    # Imported here so the ~80 MB checkpoint loads only after the corpus parses.
    from scripts.embed_with_st import MODEL_NAME, embed_st

    embed_start = time.monotonic()
    texts = [c["text"] for c in chunks]
    embeddings = embed_st(texts)
    print(f"[load_data_st] embedded {len(chunks)} with {MODEL_NAME} in {time.monotonic() - embed_start:.1f}s")

    col = store.get_collection(COLLECTION)
    for i in range(0, len(chunks), UPSERT_BATCH_SIZE):
        batch = chunks[i : i + UPSERT_BATCH_SIZE]
        col.upsert(
            ids=[c["chunk_id"] for c in batch],
            documents=[c["text"] for c in batch],
            embeddings=embeddings[i : i + UPSERT_BATCH_SIZE],
            metadatas=[{"doc_id": c["chunk_id"]} for c in batch],
        )
    print(
        f"[load_data_st] upserted {len(chunks)} into '{COLLECTION}' "
        f"(count={col.count()}) in {time.monotonic() - start:.1f}s"
    )


if __name__ == "__main__":
    main()
