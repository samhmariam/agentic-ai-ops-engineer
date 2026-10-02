"""Offline checks for the recall@5 harness (Exercises 2 + 3).

The live runs need a populated Chroma collection (and an OpenAI key for
the ``scikit_docs`` side), so these tests pin the parts that decide the
score without either: subset selection, hit-any scoring, the seeded-chunk
skip, and that the MiniLM rebuild produces the same chunk ids as
``make load-data`` (otherwise the two collections aren't comparable).
"""

from collections import Counter
from pathlib import Path

from scripts.load_data import chunk_section
from scripts.recall_at_5 import SUBSET_SIZE, hit_any, load_subset, top1_unseeded
from src import corpus
from src.chunker import chunk_doc

STARTER_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_doctree.rst"


def test_subset_is_balanced_twelve() -> None:
    picked = load_subset(STARTER_ROOT / "data" / "golden_set.csv")
    assert len(picked) == 12
    assert Counter(r["query_type"] for r in picked) == Counter(SUBSET_SIZE)


def test_hit_any_matches_section_prefix() -> None:
    expected = ["modules.preprocessing", "modules.clustering"]
    assert hit_any(["modules.clustering.k-means.p1"], expected)
    assert not hit_any(["modules.svm.kernels"], expected)
    assert not hit_any(["modules.svm"], [""])  # empty prefixes never match


def test_top1_skips_seeded_chunks() -> None:
    assert top1_unseeded(["seeded.near_dup.x", "modules.ensemble.p0"]) == "modules.ensemble.p0"
    assert top1_unseeded(["seeded.a", "seeded.b"]) is None


def test_chunk_doc_ids_match_load_data() -> None:
    doctree = corpus._parse_rst(FIXTURE)
    sections = list(corpus.iter_sections_in_doctree(doctree, Path("doc/modules/cross_validation.rst")))
    st_ids = [c["chunk_id"] for s in sections for c in chunk_doc(s)]
    openai_ids = [c["doc_id"] for s in sections for c in chunk_section(s)]
    assert st_ids == openai_ids
