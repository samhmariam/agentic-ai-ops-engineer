"""
Continuous training flow
"""

import shutil

import yaml
from prefect import flow, task
from prefect.cache_policies import NO_CACHE
from prefect.events import DeploymentEventTrigger

import train
import validate


def load_params():
    with open("params.yaml") as f:
        return yaml.safe_load(f)


@task(cache_policy=NO_CACHE)
def train_model() -> str:
    return train.main()


@task(cache_policy=NO_CACHE)
def validate_model() -> bool:
    return validate.main()


@task(cache_policy=NO_CACHE)
def save_model() -> None:
    """Copies the candidate model to the final output path."""
    params = load_params()
    src = params["paths"]["model_candidate"]
    dst = params["paths"]["model_output"]
    shutil.copy2(src, dst)
    print(f"Model saved to {dst}.")


@flow(name="continuous-training-flow", log_prints=True)
def continuous_training_flow():
    train_model()
    if validate_model():
        save_model()
    else:
        print("Candidate did not improve validation accuracy; keeping the current model.")


if __name__ == "__main__":
    continuous_training_flow.serve(
        name="continuous-training-deployment",
        limit=1,
        triggers=[
            DeploymentEventTrigger(
                expect={"new-data-available"},
                match={"prefect.resource.id": "sales-training-data"},
            )
        ],
    )
