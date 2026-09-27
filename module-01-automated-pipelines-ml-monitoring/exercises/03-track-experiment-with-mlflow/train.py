"""
FinBERT fine-tuning with HuggingFace Trainer + a custom MLflow callback.
"""

import mlflow
import mlflow.pytorch
import numpy as np
import yaml
from datasets import load_dataset
from sklearn.metrics import accuracy_score
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainerCallback,
    TrainerControl,
    TrainerState,
    TrainingArguments,
)


def load_params():
    with open("params.yaml") as f:
        return yaml.safe_load(f)


class MLflowCallback(TrainerCallback):
    """
    Hooks into the HuggingFace Trainer lifecycle and logs to MLflow.
    Read more on HF Callbacks: https://huggingface.co/docs/transformers/en/main_classes/callback#callbacks
    """

    def __init__(self, params):
        self.params = params

    def on_train_begin(
        self, args, state: TrainerState, control: TrainerControl, **kwargs
    ):
        cfg = self.params["mlflow"]
        mlflow.set_tracking_uri(cfg["tracking_uri"])
        mlflow.set_experiment(cfg["experiment_name"])
        mlflow.start_run()
        mlflow.log_params(
            {
                **self.params["training"],
                "max_length": self.params["model"]["max_length"],
                "num_samples": self.params["dataset"]["num_samples"],
                "model_name": self.params["model"]["name"],
            }
        )
        mlflow.set_tags(cfg.get("tags", {}))

    def on_epoch_end(
        self, args, state: TrainerState, control: TrainerControl, **kwargs
    ):
        for entry in reversed(state.log_history):
            if "loss" in entry:
                mlflow.log_metric("train_loss", entry["loss"], step=state.global_step)
                break

    def on_evaluate(
        self, args, state: TrainerState, control: TrainerControl, metrics=None, **kwargs
    ):
        if metrics is None:
            return
        for source, target in (
            ("eval_accuracy", "val_accuracy"),
            ("eval_loss", "val_loss"),
        ):
            if source in metrics:
                mlflow.log_metric(target, metrics[source], step=state.global_step)

    def on_train_end(
        self, args, state: TrainerState, control: TrainerControl, model=None, **kwargs
    ):
        mlflow.pytorch.log_model(
            model,
            artifact_path=self.params["mlflow"]["model_artifact_name"],
        )
        mlflow.end_run()


def load_data(params):
    cfg = params["dataset"]
    tokenizer = AutoTokenizer.from_pretrained(params["model"]["name"])

    dataset = load_dataset(cfg["name"], split="train")
    dataset = dataset.shuffle(seed=cfg["seed"]).select(range(cfg["num_samples"]))

    raw_labels = dataset[cfg["label_column"]]
    # Dataset uses -1/0/1; model expects 0/1/2 (negative/neutral/positive).
    unique_labels = sorted(set(raw_labels))
    label2id = {lbl: i for i, lbl in enumerate(unique_labels)}
    num_labels = len(unique_labels)
    dataset = dataset.map(
        lambda ex: {cfg["label_column"]: label2id[ex[cfg["label_column"]]]}
    )

    def tokenize(batch):
        return tokenizer(
            batch[cfg["text_column"]],
            truncation=True,
            padding="max_length",
            max_length=params["model"]["max_length"],
        )

    dataset = dataset.map(tokenize, batched=True)
    dataset = dataset.rename_column(cfg["label_column"], "labels")

    keep = ["input_ids", "attention_mask", "labels"]
    dataset = dataset.remove_columns([c for c in dataset.column_names if c not in keep])
    dataset.set_format("torch")

    split = dataset.train_test_split(test_size=cfg["val_split"], seed=cfg["seed"])
    return split["train"], split["test"], num_labels


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=-1)
    return {"accuracy": accuracy_score(labels, predictions)}


def main():
    params = load_params()
    tr = params["training"]

    print("Loading and tokenizing dataset...")
    train_ds, val_ds, num_labels = load_data(params)

    print("Loading model...")
    model = AutoModelForSequenceClassification.from_pretrained(
        params["model"]["name"],
        num_labels=num_labels,
        ignore_mismatched_sizes=True,
    )

    training_args = TrainingArguments(
        output_dir="outputs/hf_trainer",
        num_train_epochs=tr["num_epochs"],
        per_device_train_batch_size=tr["batch_size"],
        per_device_eval_batch_size=tr["batch_size"],
        learning_rate=tr["learning_rate"],
        eval_strategy="epoch",
        save_strategy="no",
        logging_steps=1,
        max_steps=tr.get("max_steps", -1),
        # Disable built-in integrations
        # We log via our own callback.
        report_to="none",
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        compute_metrics=compute_metrics,
        callbacks=[MLflowCallback(params)],
    )

    print("Training ...")
    trainer.train()


if __name__ == "__main__":
    main()
