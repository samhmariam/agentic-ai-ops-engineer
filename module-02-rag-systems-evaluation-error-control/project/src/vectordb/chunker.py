"""Convert product JSON into text chunks suitable for embedding."""


def chunk_product(product: dict) -> list[dict]:
    """Turn a single product dict into a list of chunk dicts.

    Each chunk dict has:
        text     — human-readable text for embedding
        metadata — product_id, category, brand, name, price
    """
    specs = "\n".join(
        f"  {key}: {value}"
        for key, value in product.get("specifications", {}).items()
    )

    # Price must be in the embedded text — not just metadata — or the LLM
    # has no source material when learners ask "how much does X cost?".
    # Metadata is for the cost dashboard and downstream filtering, not RAG
    # context.
    text = (
        f"{product['name']}\n\n"
        f"{product['description']}\n\n"
        f"Price: ${product['price']:.2f} USD\n\n"
        f"Specifications:\n{specs}\n\n"
        f"Care instructions: {product.get('care_instructions', 'N/A')}"
    )

    metadata = {
        "product_id": product["product_id"],
        "category": product["category"],
        "brand": product["brand"],
        "name": product["name"],
        "price": product["price"],
    }

    return [{"text": text, "metadata": metadata}]
