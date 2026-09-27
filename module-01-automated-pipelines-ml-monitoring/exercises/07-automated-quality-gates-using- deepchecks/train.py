"""
ViT fine-tuning on the beans plant disease dataset with MLflow tracking.
"""

import mlflow
import mlflow.transformers
import torch
import yaml
from datasets import load_dataset
from mlflow.tracking import MlflowClient
from torch.optim import Adam
from torch.utils.data import DataLoader, Dataset
from transformers import AutoImageProcessor, AutoModelForImageClassification


def load_params():
    with open("params.yaml") as f:
        return yaml.safe_load(f)


class BeansDataset(Dataset):
    def __init__(self, examples, feature_extractor):
        self.examples = examples
        self.feature_extractor = feature_extractor

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        ex = self.examples[idx]
        inputs = self.feature_extractor(
            images=ex["image"].convert("RGB"), return_tensors="pt"
        )
        return {
            "pixel_values": inputs["pixel_values"].squeeze(0),
            "labels": torch.tensor(ex["labels"], dtype=torch.long),
        }


def load_data(params):
    cfg = params["dataset"]
    train_split = load_dataset(cfg["name"], split="train")
    val_split = load_dataset(cfg["name"], split="validation")
    num_labels = train_split.features["labels"].num_classes

    feature_extractor = AutoImageProcessor.from_pretrained(params["model"]["name"])
    train_ds = BeansDataset(list(train_split), feature_extractor)
    val_ds = BeansDataset(list(val_split), feature_extractor)
    return train_ds, val_ds, num_labels, feature_extractor


def train_epoch(model, loader, optimizer, device):
    model.train()
    total_loss, steps = 0.0, 0
    for batch in loader:
        pixel_values = batch["pixel_values"].to(device)
        labels = batch["labels"].to(device)
        optimizer.zero_grad()
        loss = model(pixel_values=pixel_values, labels=labels).loss
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
        steps += 1
    return total_loss / steps


def evaluate(model, loader, device):
    model.eval()
    correct, total = 0, 0
    with torch.no_grad():
        for batch in loader:
            pixel_values = batch["pixel_values"].to(device)
            labels = batch["labels"].to(device)
            preds = model(pixel_values=pixel_values).logits.argmax(dim=-1)
            correct += (preds == labels).sum().item()
            total += len(labels)
    return correct / total if total > 0 else 0.0


def main():
    params = load_params()
    tr = params["training"]
    mf = params["mlflow"]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    print(f"Loading beans dataset...")
    train_ds, val_ds, num_labels, feature_extractor = load_data(params)
    train_loader = DataLoader(train_ds, batch_size=tr["batch_size"], shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=tr["batch_size"])
    print(f"Train: {len(train_ds)} samples  Val: {len(val_ds)} samples  Classes: {num_labels}")

    print("Loading ViT model...")
    model = AutoModelForImageClassification.from_pretrained(
        params["model"]["name"],
        num_labels=num_labels,
        ignore_mismatched_sizes=True,
    ).to(device)

    # Freeze backbone
    # only train the classification head for speed
    for name, param in model.named_parameters():
        if "classifier" not in name:
            param.requires_grad = False

    optimizer = Adam(
        filter(lambda p: p.requires_grad, model.parameters()), lr=tr["learning_rate"]
    )

    mlflow.set_tracking_uri(mf["tracking_uri"])
    mlflow.set_experiment(mf["experiment_name"])

    with mlflow.start_run() as run:
        mlflow.log_params(
            {
                "model": params["model"]["name"],
                "num_labels": num_labels,
                "num_samples": len(train_ds),
                "learning_rate": tr["learning_rate"],
                "num_epochs": tr["num_epochs"],
                "frozen_backbone": True,
            }
        )
        for key, value in mf["tags"].items():
            mlflow.set_tag(key, value)

        print("Training classification head...")
        for epoch in range(tr["num_epochs"]):
            loss = train_epoch(model, train_loader, optimizer, device)
            acc = evaluate(model, val_loader, device)
            mlflow.log_metric("train_loss", loss, step=epoch)
            mlflow.log_metric("val_accuracy", acc, step=epoch)
            print(
                f"Epoch {epoch + 1}/{tr['num_epochs']}  loss={loss:.4f}  val_acc={acc:.4f}"
            )

        print("Logging and registering model...")
        mlflow.transformers.log_model(
            transformers_model={
                "model": model.to("cpu"),
                "image_processor": feature_extractor,
            },
            artifact_path=mf["model_artifact_name"],
            task="image-classification",
        )
        model_name = params["registry"]["model_name"]
        model_uri = f"runs:/{run.info.run_id}/{mf['model_artifact_name']}"
        mv = mlflow.register_model(model_uri, model_name)

        client = MlflowClient()
        client.set_registered_model_alias(model_name, "dev", mv.version)
        print(f"Registered as version {mv.version} with alias 'dev'.")

        print(f"Run complete. run_id={run.info.run_id}")
        return run.info.run_id


if __name__ == "__main__":
    main()
