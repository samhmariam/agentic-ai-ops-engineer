"""
Evaluates a pre-trained ViT on the beans plant disease dataset.

Usage:
    python evaluate.py
"""

import mlflow
import mlflow.transformers
import yaml
from datasets import load_dataset
from mlflow.tracking import MlflowClient
from transformers import pipeline


def load_params():
    with open("params.yaml") as f:
        return yaml.safe_load(f)


def main():
    params = load_params()
    mf = params["mlflow"]

    print(f"Loading model: {params['model']['name']}...")
    pipe = pipeline(params["model"]["task"], model=params["model"]["name"])

    print(f"Loading beans {params['dataset']['split']} split...")
    dataset = load_dataset(params["dataset"]["name"], split=params["dataset"]["split"])
    label_names = dataset.features["labels"].names
    print(f"Classes: {label_names}  —  {len(dataset)} samples")

    mlflow.set_tracking_uri(mf["tracking_uri"])
    mlflow.set_experiment(mf["experiment_name"])

    with mlflow.start_run() as run:
        mlflow.log_params(
            {
                "model": params["model"]["name"],
                "dataset": params["dataset"]["name"],
                "split": params["dataset"]["split"],
                "num_samples": len(dataset),
                "num_classes": len(label_names),
            }
        )

        print("Evaluating...")
        correct = 0
        for example in dataset:
            predictions = pipe(example["image"])
            top_label = predictions[0]["label"]
            true_label = label_names[example["labels"]]
            if top_label == true_label:
                correct += 1

        accuracy = correct / len(dataset)
        mlflow.log_metric("accuracy", accuracy)

        print(f"\nAccuracy : {accuracy:.4f}")
        print(f"Run ID   : {run.info.run_id}")

        model_info = mlflow.transformers.log_model(
            transformers_model=pipe,
            artifact_path=mf["model_artifact_name"],
            task=params["model"]["task"],   
            registered_model_name=params["registry"]["model_name"],
        )

        if accuracy > params["registry"]["threshold"]:
            client = MlflowClient()
            client.set_registered_model_alias(
                name=params["registry"]["model_name"],
                alias="production",
                version=model_info.registered_model_version,
            )

        return run.info.run_id


if __name__ == "__main__":
    main()
