# Module 05 — Feature Store with Feast

Feast is an open-source **feature store**: a system that manages the storage and retrieval of ML features. It separates feature engineering from model training and serving, ensuring that the exact same features used during training are available at inference time.

---

## 1. Generate the raw data

Run `generate_data.py` to create a synthetic credit card transaction dataset. This represents the raw historical data that Feast will use as a feature source.

```bash
python generate_data.py
```

The script saves 1000 rows (100 cardholders × 10 timestamps) to `data/transactions.parquet`. Each row contains feature values per cardholder at a specific point in time.

---

## 2. Understand `feature_store.yaml`

This file tells Feast where to store its metadata and data:

```yaml
registry: data/registry.db     # where Feast stores feature definitions
provider: local                 # run everything locally
online_store:
  type: sqlite
  path: data/online_store.db   # low-latency store for real-time serving
```

- **Offline store**: the source of historical features (here, the local parquet file). Used for point-in-time correct training data retrieval.
- **Online store**: a low-latency database (here, SQLite) populated via materialization. Used at inference time for real-time feature serving.
- **Registry**: a metadata store that tracks all feature definitions, entities, and data sources registered with `feast apply`.

---

## 3. Complete `features.py`

In `features.py` you declare the objects that Feast needs to locate and serve features. No data is moved at this stage.

- **Entity** (`cardholder_id`): the primary key that identifies what we are making predictions about. Feast uses it to join features across feature views.
- **FileSource**: tells Feast where the raw data lives and which column is the event timestamp.
- **FeatureView `transaction_stats`**: defines a named group of features  (`transaction_amount`, `transaction_frequency`, `average_spend`) and links them to the entity and source.
- **FeatureView `behavioral_features`**: a second feature view grouping `days_since_last_transaction` and `transaction_velocity`.

---

## 4. Register features with `feast apply`

`feast apply` reads `features.py` and writes all definitions (entities, sources, feature views) to the registry. 

```bash
feast apply
```

Verify both feature views are registered by launching the Feast UI:

```bash
feast ui
```

Read more about `feast apply` [here](https://docs.feast.dev/master/reference/feast-cli-commands#apply).

---

## 5. Build a training dataset with point-in-time correctness

Complete `get_training_data.py` to retrieve historical features and save the training dataset, then run it.

```bash
python get_training_data.py
```

The entity DataFrame (20 cardholders with fraud labels and timestamps) is provided.

Feast performs a **point-in-time join**: for each entity row, it looks up the most recent feature values *at or before* that timestamp from the offline store.

This guarantees **no data leakage** (i.e., features from the future are never used to train the model).

---

## 6. Materialize features into the online store

Before serving features in real time, you must **materialize** them. Feast copies the latest feature values from the offline store (parquet) into the online store (SQLite) for low-latency access.

```bash
feast materialize-incremental $(date -u +"%Y-%m-%dT%H:%M:%S")
```

Only features up to the current timestamp are loaded.

Read more about materialization [here](https://docs.feast.dev/master/getting-started/concepts/data-ingestion#batch-data-ingestion).

---

## 7. Retrieve online features

Complete `get_online_features.py` and run it to retrieve features for a set of cardholders in real time, simulating what a fraud detection API would do at inference time.

```bash
python get_online_features.py
```

Unlike historical retrieval, online serving returns the **latest** feature value for each entity with low latency, making it suitable for real-time model predictions.