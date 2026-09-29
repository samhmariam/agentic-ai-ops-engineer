"""
Train the MLP classifier and save the model + test data to disk.
Run:
    python train.py
"""

import joblib
import numpy as np
import pandas as pd
from fairlearn.datasets import fetch_diabetes_hospital
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import LabelEncoder, StandardScaler

print("Loading dataset...")
data = fetch_diabetes_hospital(as_frame=True)
X, y = data.data, data.target

# Preserve gender separately for fairness evaluation.
sensitive_feature = X["gender"].copy()
# Exclude protected attributes and the original readmission outcome.
X = X.drop(columns=["gender", "race", "readmitted"])

# Encode each nonnumeric feature with its own label mapping.
for column in X.select_dtypes(exclude="number").columns:
    X[column] = LabelEncoder().fit_transform(X[column])


X = X.astype(float)

# Encode target labels
y = LabelEncoder().fit_transform(y)

# Split features, targets, and gender together to preserve row alignment.
X_train, X_test, y_train, y_test, sf_train, sf_test = train_test_split(
    X, y, sensitive_feature, test_size=0.2, random_state=42
)

scaler = StandardScaler()
X_train = scaler.fit_transform(X_train)
X_test = scaler.transform(X_test)

print("Training MLP...")
model = MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=100, random_state=42)
model.fit(X_train, y_train)

joblib.dump({"model": model, "scaler": scaler}, "model.joblib")
np.save("X_test.npy", X_test)
np.save("y_test.npy", y_test)
sf_test.reset_index(drop=True).to_csv("sf_test.csv", index=False)

print("Saved: model.joblib, X_test.npy, y_test.npy, sf_test.csv")
