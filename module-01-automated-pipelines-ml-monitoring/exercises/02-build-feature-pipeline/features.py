"""
Feast feature definitions.

Entity: cardholder_id

Feature views:
  - transaction_stats     : transaction_amount, transaction_frequency, average_spend
  - behavioral_features   : days_since_last_transaction, transaction_velocity
"""

from datetime import timedelta
from pathlib import Path

from feast import Entity, FeatureView, Field, FileSource
from feast.types import Float64, Int64

TRANSACTIONS_PATH = str(Path(__file__).parent / "data" / "transactions.parquet")
ACTIVITY_PATH = str(Path(__file__).parent / "data" / "cardholder_activity.parquet")

cardholder = Entity(name="cardholder_id", join_keys=["cardholder_id"])

transaction_source = FileSource(
    path=TRANSACTIONS_PATH,
    timestamp_field="event_timestamp",
)

activity_source = FileSource(
    path=ACTIVITY_PATH,
    timestamp_field="event_timestamp",
)

transaction_stats = FeatureView(
    name="transaction_stats",
    entities=[cardholder],
    ttl=timedelta(days=30),
    schema=[
        Field(name="transaction_amount", dtype=Float64),
        Field(name="transaction_frequency", dtype=Int64),
        Field(name="average_spend", dtype=Float64),
    ],
    source=transaction_source,
)

behavioral_features = FeatureView(
    name="behavioral_features",
    entities=[cardholder],
    ttl=timedelta(days=30),
    schema=[
        Field(name="days_since_last_transaction", dtype=Int64),
        Field(name="transaction_velocity", dtype=Float64),
    ],
    source=activity_source,
)
