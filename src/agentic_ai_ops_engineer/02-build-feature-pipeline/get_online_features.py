"""
Retrieves online features for a given cardholder and measures latency
"""

import time

import pandas as pd
from feast import FeatureStore

CARDHOLDER_ID = 42
FEATURES = [
    "transaction_stats:transaction_amount",
    "transaction_stats:transaction_frequency",
    "transaction_stats:average_spend",
    "behavioral_features:days_since_last_transaction",
    "behavioral_features:transaction_velocity",
]

if __name__ == "__main__":
    store = FeatureStore(repo_path=".")

    start = time.perf_counter()
    response = store.get_online_features(
        features=FEATURES,
        entity_rows=[{"cardholder_id": CARDHOLDER_ID}],
    )
    latency_ms = (time.perf_counter() - start) * 1000
    online_features = response.to_df()

    print(f"Online features for cardholder {CARDHOLDER_ID}:")
    print(online_features.to_string(index=False))
    print(f"Online feature retrieval latency: {latency_ms:.2f} ms")

    transactions = pd.read_parquet("data/transactions.parquet")
    baseline = (
        transactions.loc[transactions["cardholder_id"] == CARDHOLDER_ID]
        .sort_values("event_timestamp")
        .tail(1)
    )

    print("\nLatest transaction baseline:")
    if baseline.empty:
        print(f"No transactions found for cardholder {CARDHOLDER_ID}.")
    else:
        print(baseline.to_string(index=False))
