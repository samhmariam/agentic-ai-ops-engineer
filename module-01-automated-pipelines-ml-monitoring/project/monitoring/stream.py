"""
Production monitoring stream for FinBERT sentiment API.

Reads headlines from data/stream.csv, sends them to the /predict endpoint,
and logs aggregated metrics to MLflow every WINDOW_SIZE predictions.

Each observation window logs:
    - Sentiment distribution (% positive, % negative, % neutral)
    - Average confidence score
    - Average latency (ms)

Run from the project root:
    python monitoring/stream.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import mlflow
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

# API_HOST may be the server bind address 0.0.0.0, which is not a valid
# client destination on every platform (e.g. Windows); use localhost then.
_api_host = os.getenv("API_HOST", "localhost")
if _api_host == "0.0.0.0":
    _api_host = "localhost"
API_URL = f"http://{_api_host}:{os.getenv('API_PORT', 8000)}"
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
MLFLOW_EXPERIMENT_NAME = os.getenv("MLFLOW_EXPERIMENT_NAME", "finbert-evaluation")
WINDOW_SIZE = 50  # number of predictions per observation window
SLEEP_MS = 100    # delay between requests to simulate real traffic (ms)
SENTIMENTS = ("positive", "negative", "neutral")
STREAM_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "stream.csv"
)


def predict(text: str) -> dict:
    response = requests.post(
        f"{API_URL}/predict",
        json={"text": text},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()

def log_window(window: list[dict], window_idx: int) -> None:
    """Log aggregated metrics for one observation window to MLflow."""
    n = len(window)
    if n == 0:
        return

    labels = [str(r["sentiment"]).lower() for r in window]
    metrics = {
        f"pct_{sentiment}": 100 * labels.count(sentiment) / n
        for sentiment in SENTIMENTS
    }
    metrics["avg_confidence"] = sum(r["confidence"] for r in window) / n
    metrics["avg_latency_ms"] = sum(r["latency_ms"] for r in window) / n
    metrics["window_size"] = n

    mlflow.log_metrics(metrics, step=window_idx)
    print(
        f"Window {window_idx}: n={n} "
        + " ".join(f"{s}={metrics[f'pct_{s}']:.1f}%" for s in SENTIMENTS)
        + f" conf={metrics['avg_confidence']:.3f}"
        + f" latency={metrics['avg_latency_ms']:.1f}ms"
    )


def main():
    headlines = pd.read_csv(STREAM_PATH)["text"].dropna().astype(str).tolist()
    print(f"Loaded {len(headlines)} headlines from {STREAM_PATH}")

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)

    with mlflow.start_run(run_name="production-monitoring"):
        mlflow.log_params(
            {
                "api_url": API_URL,
                "n_headlines": len(headlines),
                "window_size": WINDOW_SIZE,
                "sleep_ms": SLEEP_MS,
            }
        )

        window: list[dict] = []
        window_idx = 0
        n_errors = 0

        for text in headlines:
            try:
                window.append(predict(text))
            except requests.RequestException as e:
                n_errors += 1
                print(f"Prediction failed: {type(e).__name__}: {e}")

            if len(window) == WINDOW_SIZE:
                log_window(window, window_idx)
                window = []
                window_idx += 1

            time.sleep(SLEEP_MS / 1000)

        # Flush the final partial window so no predictions are dropped.
        if window:
            log_window(window, window_idx)
            window_idx += 1

        mlflow.log_metrics({"total_errors": n_errors, "total_windows": window_idx})
        print(f"Done: {window_idx} windows logged, {n_errors} failed requests")


if __name__ == "__main__":
    main()
