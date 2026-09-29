"""
Evaluates the trained MLP classifier for fairness across gender subgroups.

Run:
    python check_fairness.py
"""

import json
import sys
from functools import partial

import joblib
import numpy as np
import pandas as pd
from fairlearn.metrics import (
    MetricFrame,
    demographic_parity_difference,
    equalized_odds_difference,
)
from sklearn.metrics import accuracy_score, precision_score, recall_score

# Maximum allowed differences for this exercise.
DPD_THRESHOLD = 0.10
EOD_THRESHOLD = 0.10

# Load the model and already-scaled test features saved by train.py.
print("Loading model and test data...")

model = joblib.load("model.joblib")["model"]
X_test = np.load("X_test.npy")
y_test = np.load("y_test.npy")
sf_test = pd.read_csv("sf_test.csv")["gender"]

y_pred = model.predict(X_test)
overall_acc = accuracy_score(y_test, y_pred)
print(f"Overall accuracy: {overall_acc:.4f}")

metrics = {
    "accuracy": accuracy_score,
    "precision": partial(precision_score, zero_division=0),
    "recall": partial(recall_score, zero_division=0),
}

mf = MetricFrame(
    metrics=metrics,
    y_true=y_test,
    y_pred=y_pred,
    sensitive_features=sf_test,
)
print("\nMetrics by gender:")
print(mf.by_group)

dpd = demographic_parity_difference(y_test, y_pred, sensitive_features=sf_test)
eod = equalized_odds_difference(y_test, y_pred, sensitive_features=sf_test)
print(json.dumps({
    "demographic_parity_difference": float(dpd),
    "equalized_odds_difference": float(eod),
    "dpd_threshold": DPD_THRESHOLD,
    "eod_threshold": EOD_THRESHOLD,
}, indent=2))

if dpd > DPD_THRESHOLD or eod > EOD_THRESHOLD:
    print("Fairness gate failed: at least one difference exceeds its threshold.")
    sys.exit(1)

print("Fairness gate passed: both differences are within their thresholds.")
sys.exit(0)
