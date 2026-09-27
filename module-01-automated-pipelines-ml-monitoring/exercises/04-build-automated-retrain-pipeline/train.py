"""
Sales MLP training with MLflow tracking.
"""

import os

import mlflow
import pandas as pd
import torch
import torch.nn as nn
import yaml
from torch.optim import Adam
from torch.utils.data import DataLoader, TensorDataset


def load_params():
    with open("params.yaml") as f:
        return yaml.safe_load(f)


class SalesMLP(nn.Module):
    def __init__(self, input_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def load_data(params):
    cfg = params["dataset"]
    df = pd.read_csv("data/train.csv")
    df = df.sample(frac=1, random_state=cfg["seed"]).reset_index(drop=True)

    feature_cols = [c for c in df.columns if c != cfg["label_column"]]
    X = torch.tensor(df[feature_cols].values, dtype=torch.float32)
    y = torch.tensor(df[cfg["label_column"]].values, dtype=torch.float32)

    split = int(len(df) * (1 - cfg["val_split"]))
    train_ds = TensorDataset(X[:split], y[:split])
    val_ds = TensorDataset(X[split:], y[split:])
    return train_ds, val_ds, X.shape[1]


def train_epoch(model, loader, optimizer, criterion, device):
    model.train()
    total_loss, steps = 0.0, 0
    for X_batch, y_batch in loader:
        X_batch, y_batch = X_batch.to(device), y_batch.to(device)
        optimizer.zero_grad()
        loss = criterion(model(X_batch), y_batch)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
        steps += 1
    return total_loss / steps


def evaluate(model, loader, device):
    model.eval()
    correct, total = 0, 0
    with torch.no_grad():
        for X_batch, y_batch in loader:
            X_batch, y_batch = X_batch.to(device), y_batch.to(device)
            preds = (torch.sigmoid(model(X_batch)) >= 0.5).float()
            correct += (preds == y_batch).sum().item()
            total += len(y_batch)
    return correct / total if total > 0 else 0.0


def main():
    params = load_params()
    tr = params["training"]
    mf = params["mlflow"]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    print("Loading data from data/train.csv...")
    train_ds, val_ds, input_dim = load_data(params)
    train_loader = DataLoader(train_ds, batch_size=tr["batch_size"], shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=tr["batch_size"])
    print(f"Train: {len(train_ds)} samples  Val: {len(val_ds)} samples")

    model = SalesMLP(input_dim).to(device)
    optimizer = Adam(model.parameters(), lr=tr["learning_rate"])
    criterion = nn.BCEWithLogitsLoss()

    mlflow.set_tracking_uri(mf["tracking_uri"])
    mlflow.set_experiment(mf["experiment_name"])

    with mlflow.start_run() as run:
        mlflow.log_params({
            "learning_rate": tr["learning_rate"],
            "batch_size": tr["batch_size"],
            "num_epochs": tr["num_epochs"],
            "train_samples": len(train_ds),
            "input_dim": input_dim,
        })
        for key, value in mf["tags"].items():
            mlflow.set_tag(key, value)

        print("Training...")
        for epoch in range(tr["num_epochs"]):
            loss = train_epoch(model, train_loader, optimizer, criterion, device)
            acc = evaluate(model, val_loader, device)
            mlflow.log_metric("train_loss", loss, step=epoch)
            mlflow.log_metric("val_accuracy", acc, step=epoch)
            print(f"Epoch {epoch + 1}/{tr['num_epochs']}  loss={loss:.4f}  val_acc={acc:.4f}")

        os.makedirs("outputs", exist_ok=True)
        torch.save(model.state_dict(), params["paths"]["model_candidate"])
        run_id = run.info.run_id
        print(f"Run complete. Candidate saved to {params['paths']['model_candidate']}  run_id={run_id}")
        return run_id


if __name__ == "__main__":
    main()
