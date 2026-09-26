"""
Simulates a stream of new sales data arriving over time.

Each subsequent call appends the next chunk and emits a Prefect event.

Usage:
    python add_data.py            # 5 chunks by default
    python add_data.py --chunks 3
"""

import argparse
import os

import pandas as pd

CHUNKS_DIR = "data/chunks"
TRAIN_CSV = "data/train.csv"
STATE_FILE = "data/.chunk_state"
SOURCE_CSV = "sales_data.csv"
DROP_COLS = ["Order ID", "Date", "Manager"]
LABEL_COL = "high_volume"


def load_and_prepare() -> pd.DataFrame:
    df = pd.read_csv(SOURCE_CSV)

    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()

    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    df["month"] = df["Date"].dt.month
    df["day_of_week"] = df["Date"].dt.dayofweek

    from sklearn.preprocessing import LabelEncoder
    le = LabelEncoder()
    for col in ["Product", "Purchase Type", "Payment Method", "City"]:
        df[col] = le.fit_transform(df[col])

    df = df.drop(columns=DROP_COLS, errors="ignore")

    median_qty = df["Quantity"].median()
    df[LABEL_COL] = (df["Quantity"] > median_qty).astype(int)
    df = df.drop(columns=["Quantity"])

    return df.sample(frac=1, random_state=42).reset_index(drop=True)


def read_state() -> int:
    if not os.path.exists(STATE_FILE):
        return 0
    with open(STATE_FILE) as f:
        return int(f.read().strip())


def write_state(chunk_index: int) -> None:
    with open(STATE_FILE, "w") as f:
        f.write(str(chunk_index))


def setup_chunks(n_chunks: int) -> None:
    print("Loading and preparing sales_data.csv...")
    df = load_and_prepare()
    print(f"Total samples: {len(df)} — columns: {list(df.columns)}")

    os.makedirs(CHUNKS_DIR, exist_ok=True)
    chunk_size = len(df) // n_chunks
    for i in range(n_chunks):
        start = i * chunk_size
        end = start + chunk_size if i < n_chunks - 1 else len(df)
        df.iloc[start:end].to_csv(f"{CHUNKS_DIR}/chunk_{i + 1}.csv", index=False)
        print(f"  chunk_{i + 1}.csv — {end - start} rows")


def emit_new_data_event() -> None:
    try:
        from prefect.events import emit_event
        emit_event(
            event="new-data-available",
            resource={"prefect.resource.id": "sales-training-data"},
        )
        print("Prefect event 'new-data-available' emitted.")
    except Exception as exc:
        print(f"Could not emit Prefect event (is the server running?): {exc}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks", type=int, default=5)
    args = parser.parse_args()

    current = read_state()

    if current == 0:
        setup_chunks(args.chunks)
        chunk = pd.read_csv(f"{CHUNKS_DIR}/chunk_1.csv")
        os.makedirs("data", exist_ok=True)
        chunk.to_csv(TRAIN_CSV, index=False)
        write_state(1)
        print(f"\nInitialised data/train.csv with chunk_1 ({len(chunk)} rows).")
        emit_new_data_event()
        return

    next_chunk = current + 1
    next_path = f"{CHUNKS_DIR}/chunk_{next_chunk}.csv"
    if not os.path.exists(next_path):
        print(f"All chunks added (last was chunk_{current}). No more data to stream.")
        return

    existing = pd.read_csv(TRAIN_CSV)
    new_data = pd.read_csv(next_path)
    updated = pd.concat([existing, new_data], ignore_index=True)
    updated.to_csv(TRAIN_CSV, index=False)
    write_state(next_chunk)
    print(f"Added chunk_{next_chunk} -> data/train.csv now has {len(updated)} rows (was {len(existing)}).")
    emit_new_data_event()


if __name__ == "__main__":
    main()
