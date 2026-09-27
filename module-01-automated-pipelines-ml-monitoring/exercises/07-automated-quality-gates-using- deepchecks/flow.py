"""
Continuous training flow with model registry promotion.
"""

import mlflow
import yaml
from mlflow.tracking import MlflowClient
from prefect import flow, task


def load_params():
    with open("params.yaml") as f:
        return yaml.safe_load(f)


@task(name="Train", log_prints=True)
def train_model() -> str:
    import train

    return train.main()


@task(name="Validate", log_prints=True)
def validate_model() -> bool:
    import validate

    return validate.main()


@task(name="Promote to Production", log_prints=True)
def promote_model() -> None:
    params = load_params()
    reg = params["registry"]

    mlflow.set_tracking_uri(params["mlflow"]["tracking_uri"])
    client = MlflowClient()

    # Get the @dev version (registered by train.py)
    dev = client.get_model_version_by_alias(reg["model_name"], "dev")

    # Add description and tags
    client.update_registered_model(name=reg["model_name"], description=reg["description"])
    for key, value in reg["tags"].items():
        client.set_model_version_tag(reg["model_name"], dev.version, key, value)

    # Promote @dev to @production
    client.set_registered_model_alias(reg["model_name"], "production", dev.version)
    print(f"Version {dev.version} alias set to '@production'.")


@flow(name="continuous-training-flow", log_prints=True)
def continuous_training_flow():
    train_model()
    passed = validate_model()
    if passed:
        promote_model()
    else:
        print("Validation failed. Model not promoted to production.")


if __name__ == "__main__":
    continuous_training_flow()
