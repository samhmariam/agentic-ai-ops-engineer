"""Tests for src.vectordb.chunker."""

from src.vectordb import chunk_product


def _product() -> dict:
    return {
        "product_id": "prod_999",
        "name": "Test Paddle",
        "category": "paddles",
        "brand": "Acme",
        "price": 99.99,
        "description": "A test paddle.",
        "specifications": {"weight": "8.0 oz", "core": "polypropylene"},
        "care_instructions": "Wipe clean.",
    }


def test_chunk_product_returns_one_chunk_with_text_and_metadata():
    chunks = chunk_product(_product())

    assert len(chunks) == 1
    chunk = chunks[0]
    assert "text" in chunk and "metadata" in chunk


def test_chunk_text_includes_name_description_specs_and_care():
    text = chunk_product(_product())[0]["text"]

    assert "Test Paddle" in text
    assert "A test paddle." in text
    assert "weight: 8.0 oz" in text
    assert "core: polypropylene" in text
    assert "Wipe clean." in text


def test_chunk_text_includes_price():
    """Price must be in the embedded text so the LLM can answer cost queries.

    Storing price only in metadata (which is filterable but not part of the
    RAG context window) leaves the model with no source material when a
    learner asks "what's the price of X?". The chunk text is the LLM's
    ground truth, so price has to live there.
    """
    text = chunk_product(_product())[0]["text"]

    assert "$99.99" in text


def test_chunk_metadata_carries_product_fields():
    metadata = chunk_product(_product())[0]["metadata"]

    assert metadata["product_id"] == "prod_999"
    assert metadata["name"] == "Test Paddle"
    assert metadata["category"] == "paddles"
    assert metadata["brand"] == "Acme"
    assert metadata["price"] == 99.99


def test_chunk_handles_missing_care_instructions():
    product = _product()
    del product["care_instructions"]
    text = chunk_product(product)[0]["text"]

    assert "N/A" in text
