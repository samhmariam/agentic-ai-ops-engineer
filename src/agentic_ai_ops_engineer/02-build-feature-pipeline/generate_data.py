"""Generates synthetic credit card datasets for the Feast feature store."""

import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

NUM_CARDHOLDERS = 100
TIMESTAMPS_PER_CARDHOLDER = 10
SEED = 42

np.random.seed(SEED)
os.makedirs("data", exist_ok=True)

base_time = datetime.now(tz=timezone.utc) - timedelta(days=TIMESTAMPS_PER_CARDHOLDER * 3)

transaction_rows = []
for cardholder_id in range(1, NUM_CARDHOLDERS + 1):
    for i in range(TIMESTAMPS_PER_CARDHOLDER):
        event_timestamp = base_time + timedelta(days=i * 3)
        transaction_rows.append({
            "cardholder_id": cardholder_id,
            "event_timestamp": event_timestamp,
            "transaction_amount": round(np.random.exponential(scale=150), 2),
            "transaction_frequency": int(np.random.poisson(lam=5)),
            "average_spend": round(np.random.normal(loc=200, scale=80), 2),
        })

transactions_df = pd.DataFrame(transaction_rows)
transactions_df["event_timestamp"] = pd.to_datetime(transactions_df["event_timestamp"], utc=True)
transactions_df.to_parquet("data/transactions.parquet", index=False)
print(f"Saved {len(transactions_df)} rows to data/transactions.parquet")
print(transactions_df.head())

activity_rows = []
for cardholder_id in range(1, NUM_CARDHOLDERS + 1):
    last_ts = None
    for i in range(TIMESTAMPS_PER_CARDHOLDER):
        event_timestamp = base_time + timedelta(days=i * 3)
        days_since_last = (event_timestamp - last_ts).days if last_ts else 0
        activity_rows.append({
            "cardholder_id": cardholder_id,
            "event_timestamp": event_timestamp,
            "days_since_last_transaction": days_since_last,
            "transaction_velocity": round(np.random.uniform(0.5, 10.0), 2),
        })
        last_ts = event_timestamp

activity_df = pd.DataFrame(activity_rows)
activity_df["event_timestamp"] = pd.to_datetime(activity_df["event_timestamp"], utc=True)
activity_df.to_parquet("data/cardholder_activity.parquet", index=False)
print(f"Saved {len(activity_df)} rows to data/cardholder_activity.parquet")
print(activity_df.head())
