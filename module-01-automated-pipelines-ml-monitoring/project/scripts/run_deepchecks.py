"""
Model quality check (drift) using deepchecks

Run:
    python scripts/run_deepchecks.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd
import yaml
from deepchecks.nlp import TextData
from deepchecks.nlp.checks import PredictionDrift, PropertyDrift
from dotenv import load_dotenv

from app.utils import load_classifier

load_dotenv()

PROPERTIES = ["Sentiment", "Subjectivity", "Text Length", "Average Word Length"]


def load_params() -> dict:
    with open("params.yaml") as f:
        return yaml.safe_load(f)["deepchecks"]


def run_predictions(classifier, texts: list[str]) -> list[str]:
    results = classifier(texts, batch_size=32)
    return [r["label"] for r in results]


def main():
    params = load_params()
    property_drift_threshold = params["property_drift_threshold"]
    prediction_drift_threshold = params["prediction_drift_threshold"]

    print("Loading production model...")

    classifier = load_classifier()

    stream_df = pd.read_csv("data/stream.csv")
    test_df = pd.read_csv("data/test.csv")

    stream_texts = stream_df["text"].tolist()
    test_texts = test_df["text"].tolist()

    stream_dataset = TextData(
        raw_text=stream_texts, task_type="text_classification", name="stream"
    )
    test_dataset = TextData(
        raw_text=test_texts, task_type="text_classification", name="test"
    )
    # Fast TextBlob/statistics-based properties only; the default set also
    # downloads extra transformer models (Toxicity, Fluency, Formality).
    for dataset in (stream_dataset, test_dataset):
        dataset.calculate_builtin_properties(include_properties=PROPERTIES)

    # --- NLP property drift: test (reference) vs stream (current) ---
    property_result = PropertyDrift().run(
        train_dataset=test_dataset, test_dataset=stream_dataset
    )
    print("\nProperty drift scores:")
    for name, values in property_result.value.items():
        print(f"  {name}: {values['Drift score']:.4f} ({values['Method']})")

    sentiment_drift = property_result.value["Sentiment"]["Drift score"]
    if sentiment_drift > property_drift_threshold:
        print(
            f"\n[FAIL] Sentiment property drift {sentiment_drift:.4f} exceeds "
            f"threshold {property_drift_threshold}"
        )
        sys.exit(1)
    print(
        f"[PASS] Sentiment property drift {sentiment_drift:.4f} <= "
        f"threshold {property_drift_threshold}"
    )

    # --- Prediction drift ---
    print("\nRunning predictions on test and stream data...")
    test_predictions = run_predictions(classifier, test_texts)
    stream_predictions = run_predictions(classifier, stream_texts)

    prediction_result = PredictionDrift().run(
        train_dataset=test_dataset,
        test_dataset=stream_dataset,
        train_predictions=test_predictions,
        test_predictions=stream_predictions,
        model_classes=sorted(set(test_predictions) | set(stream_predictions)),
    )
    prediction_drift = prediction_result.value["Drift score"]
    print(
        f"Prediction drift score: {prediction_drift:.4f} "
        f"({prediction_result.value['Method']})"
    )

    if prediction_drift > prediction_drift_threshold:
        print(
            f"\n[FAIL] Prediction drift {prediction_drift:.4f} exceeds "
            f"threshold {prediction_drift_threshold}"
        )
        sys.exit(1)
    print(
        f"[PASS] Prediction drift {prediction_drift:.4f} <= "
        f"threshold {prediction_drift_threshold}"
    )
    print("\nAll deepchecks drift checks passed.")


if __name__ == "__main__":
    main()
