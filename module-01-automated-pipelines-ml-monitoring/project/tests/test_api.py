"""
Integration tests for the Sentiment Analysis API.
"""

import pytest
from fastapi.testclient import TestClient

VALID_SENTIMENTS = {"positive", "negative", "neutral"}

HEADLINES = [
    "The company reported record profits this quarter.",
    "Shares plunged after the firm missed earnings expectations.",
    "The central bank left interest rates unchanged.",
]


def assert_valid_prediction(item: dict, text: str) -> None:
    assert set(item) == {"text", "sentiment", "confidence", "latency_ms"}
    assert item["text"] == text
    assert item["sentiment"] in VALID_SENTIMENTS
    assert isinstance(item["confidence"], float)
    assert 0.0 <= item["confidence"] <= 1.0
    assert isinstance(item["latency_ms"], float)
    assert item["latency_ms"] >= 0.0


@pytest.mark.parametrize("text", HEADLINES)
def test_predict_returns_valid_response(client: TestClient, text):
    response = client.post("/predict", json={"text": text})

    assert response.status_code == 200
    assert_valid_prediction(response.json(), text)


def test_predict_batch(client: TestClient):
    response = client.post("/predict/batch", json={"texts": HEADLINES})

    assert response.status_code == 200
    results = response.json()
    assert isinstance(results, list)
    assert len(results) == len(HEADLINES)
    for item, text in zip(results, HEADLINES):
        assert_valid_prediction(item, text)


def test_predict_batch_empty_list_returns_422(client: TestClient):
    response = client.post("/predict/batch", json={"texts": []})

    assert response.status_code == 422
