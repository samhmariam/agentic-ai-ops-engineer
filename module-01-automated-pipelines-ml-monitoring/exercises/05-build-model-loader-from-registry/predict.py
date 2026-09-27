"""
Loads the Production model from the MLflow registry
and runs inference on a sample image from the beans dataset.

Usage:
    python predict.py
    python predict.py --image path/to/image.jpg
"""

import argparse

import mlflow
import mlflow.transformers
import yaml

from mlflow.tracking import MlflowClient


def load_params():
    with open("params.yaml") as f:
        return yaml.safe_load(f)


def load_production_model(tracking_uri: str, model_name: str):
    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient()
    version = client.get_model_version_by_alias(model_name, "production").version
    model_uri = f"models:/{model_name}/{version}"
    print(f"Loading model from: {model_uri}  (version {version})")
    return mlflow.transformers.load_model(model_uri)


def predict(model, image):
    predictions = model(image)
    return predictions[0]["label"]


def main(image_path=None):
    params = load_params()
    mf = params["mlflow"]
    model_name = params["registry"]["model_name"]

    print(f"Loading Production model '{model_name}' from registry...")

    model = load_production_model(mf["tracking_uri"], model_name)

    if image_path is None:
        from datasets import load_dataset

        dataset = load_dataset(
            params["dataset"]["name"], split=params["dataset"]["split"]
        )
        sample = dataset[0]
        image = sample["image"]
        true_label = dataset.features["labels"].names[sample["labels"]]
        print(f"Using sample image. True label: {true_label}")
    else:
        from PIL import Image

        image = Image.open(image_path)
        true_label = "unknown"

    predicted_label = predict(model, image)
    print(f"Predicted label: {predicted_label}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=str, default=None)
    args = parser.parse_args()
    main(args.image)
