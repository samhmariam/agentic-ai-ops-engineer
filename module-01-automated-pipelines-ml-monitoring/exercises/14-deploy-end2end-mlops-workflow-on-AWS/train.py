"""
Training script for SageMaker HuggingFace estimator.

SageMaker injects:
  SM_CHANNEL_TRAIN: path to train.json
  SM_CHANNEL_VALID: path to valid.json
  SM_MODEL_DIR: where to save the trained model
"""

import os

import pandas as pd
from datasets import Dataset
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)

MODEL_NAME = "baptle/FinBERT_market_based"


def main():
    train_path = os.environ.get("SM_CHANNEL_TRAIN", "processing/output/train")
    model_dir  = os.environ.get("SM_MODEL_DIR", "/tmp/finbert-solution")

    print(f"Loading train data from {train_path}...")
    train_df = pd.read_json(f"{train_path}/train.json", lines=True)

    train_dataset = Dataset.from_pandas(train_df).select(range(min(200, len(train_df))))

    print(f"Loading tokenizer: {MODEL_NAME}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

    def tokenize(example):
        return tokenizer(example["Title"], truncation=True, padding="max_length", max_length=128)

    train_dataset = train_dataset.map(tokenize, batched=True)
    train_dataset = train_dataset.rename_column("label", "labels")
    train_dataset.set_format(type="torch", columns=["input_ids", "attention_mask", "labels"])

    print(f"Loading model: {MODEL_NAME}")
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, num_labels=3)

    training_args = TrainingArguments(
        output_dir=model_dir,
        per_device_train_batch_size=8,
        num_train_epochs=1,
        save_strategy="no",
        logging_dir="/opt/ml/output/logs",
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
    )

    print("Training...")
    trainer.train()
    trainer.save_model(model_dir)
    tokenizer.save_pretrained(model_dir)
    print(f"Model saved to {model_dir}")


if __name__ == "__main__":
    main()
