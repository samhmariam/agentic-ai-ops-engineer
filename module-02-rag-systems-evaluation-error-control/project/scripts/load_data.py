"""Bootstrap the product corpus into Chroma.

Usage:
    uv run python scripts/load_data.py
    # or: make load-data
"""

import json
from pathlib import Path

from src.vectordb.chunker import chunk_product
from src.vectordb.embedder import embed
from src.vectordb.store import add


def main() -> None:
    products_dir = Path("data/products")
    files = sorted(products_dir.glob("*.json"))
    print(f"Loading {len(files)} products into Chroma...")

    all_texts, all_metadatas, all_ids = [], [], []

    for path in files:
        product = json.loads(path.read_text())
        chunks = chunk_product(product)
        for chunk in chunks:
            all_texts.append(chunk["text"])
            all_metadatas.append(chunk["metadata"])
            all_ids.append(chunk["metadata"]["product_id"])

    embeddings = embed(all_texts)
    add(documents=all_texts, embeddings=embeddings, metadatas=all_metadatas, ids=all_ids)

    print(f"Done — {len(all_ids)} chunks upserted.")


if __name__ == "__main__":
    main()
