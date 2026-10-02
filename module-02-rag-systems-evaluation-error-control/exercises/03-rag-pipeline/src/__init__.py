"""ScikitDocs starter — shared infrastructure for Course 2 implementation modules.

The system is organised one file (or package) per capability:
- `generator.py` — prompt rendering + OpenAI generation
- `store.py`, `embedder.py`, `chunker.py` — vector store + embeddings + chunking
- `pipeline.py` — end-to-end RAG composition
- `pricing.py` — per-request cost computation

Read `INTERFACES.md` (repo root for this starter) for the frozen
function contracts. Read `CONSTANTS.md` for the 21 invariants.
"""
