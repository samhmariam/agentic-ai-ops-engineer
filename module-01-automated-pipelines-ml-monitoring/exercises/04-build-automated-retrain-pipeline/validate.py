"""
Compares the latest trained model against the best model seen so far.
Returns True if the new model is better and should be saved, False otherwise.
"""

import mlflow
import yaml
from mlflow.tracking import MlflowClient


def load_params():
    with open("params.yaml") as f:
        return yaml.safe_load(f)


def get_runs(client, experiment_name):
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        raise RuntimeError(f"Experiment '{experiment_name}' does not exist.")

    runs = []
    page_token = None
    while True:
        page = client.search_runs(
            experiment_ids=[experiment.experiment_id],
            order_by=["attributes.start_time DESC"],
            page_token=page_token,
        )
        runs.extend(page)
        page_token = page.token
        if not page_token:
            break

    if not runs:
        raise RuntimeError(f"No runs found in experiment '{experiment_name}'.")
    return runs


def main():
    params = load_params()
    mf = params["mlflow"]

    mlflow.set_tracking_uri(mf["tracking_uri"])
    client = MlflowClient()

    runs = get_runs(client, mf["experiment_name"])

    latest_accuracy = runs[0].data.metrics["val_accuracy"]
    best_previous_accuracy = max(
        (run.data.metrics["val_accuracy"] for run in runs[1:]),
        default=float("-inf"),
    )
    return latest_accuracy > best_previous_accuracy


if __name__ == "__main__":
    main()
