"""
Evaluation script

Local usage:
    python evaluate.py --model-dir /tmp/finbert-model \
                       --test-dir processing/output/test \
                       --output-dir /tmp/eval-output

SageMaker injects paths automatically via /opt/ml/processing/.
"""

import argparse
import json
import os
import subprocess
import sys
import tarfile

if os.path.exists("/opt/ml/processing"):
    subprocess.run([
        sys.executable, "-m", "pip", "install",
        "numpy>=1.24.0,<2.0.0",
        "pyarrow>=14.0.0,<16.0.0",
        "transformers>=4.26.0,<5.0.0",
        "datasets>=2.14.0,<3.0.0",
    ], check=True)

import pandas as pd
import torch
from datasets import Dataset
from sklearn.metrics import accuracy_score, classification_report
from transformers import AutoModelForSequenceClassification, AutoTokenizer

parser = argparse.ArgumentParser()
_in_sm = os.path.exists("/opt/ml/processing")
parser.add_argument("--model-dir",  default="/opt/ml/processing/model"      if _in_sm else os.environ.get("SM_MODEL_DIR", "/tmp/finbert-model"))
parser.add_argument("--test-dir",   default="/opt/ml/processing/test"       if _in_sm else "processing/output/test")
parser.add_argument("--output-dir", default="/opt/ml/processing/evaluation" if _in_sm else "/tmp/eval-output")
args = parser.parse_args()

model_input_dir = args.model_dir
test_path       = args.test_dir
output_dir      = args.output_dir

# Extract model.tar.gz if present (SageMaker delivers it this way)
tar_path = os.path.join(model_input_dir, "model.tar.gz")
if os.path.exists(tar_path):
    print("Extracting model artifact...")
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(model_input_dir)

print("Loading model and tokenizer...")
model     = AutoModelForSequenceClassification.from_pretrained(model_input_dir)
tokenizer = AutoTokenizer.from_pretrained(model_input_dir)

print("Loading test data...")
test_df      = pd.read_json(f"{test_path}/test.json", lines=True)
test_dataset = Dataset.from_pandas(test_df)

def tokenize(example):
    return tokenizer(example["Title"], truncation=True, padding="max_length", max_length=128)

test_dataset = test_dataset.map(tokenize, batched=True)
test_dataset.set_format(type="torch", columns=["input_ids", "attention_mask", "label"])

predictions, true_labels = [], []
model.eval()

with torch.no_grad():
    for item in test_dataset:
        outputs = model(
            input_ids=item["input_ids"].unsqueeze(0),
            attention_mask=item["attention_mask"].unsqueeze(0),
        )
        predictions.append(torch.argmax(outputs.logits, dim=1).item())
        true_labels.append(item["label"].item())

accuracy = float(accuracy_score(true_labels, predictions))
print(f"\nAccuracy: {accuracy:.4f}")
print(classification_report(true_labels, predictions))

os.makedirs(output_dir, exist_ok=True)
with open(os.path.join(output_dir, "evaluation.json"), "w") as f:
    json.dump({"metrics": {"accuracy": {"value": accuracy}}}, f, indent=2)

print(f"Evaluation saved to {output_dir}/evaluation.json")
