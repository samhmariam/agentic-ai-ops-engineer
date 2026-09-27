import os

import pandas as pd
import yaml
from sklearn.model_selection import train_test_split


def load_params():
    with open("params.yaml") as f:
        return yaml.safe_load(f)


def ingest(source_path, train_path, test_path, test_size, random_state):
    df = pd.read_csv(source_path)

    train, test = train_test_split(
        df, test_size=test_size, random_state=random_state, shuffle=True
    )

    os.makedirs(os.path.dirname(train_path), exist_ok=True)
    train.to_csv(train_path, index=False)
    test.to_csv(test_path, index=False)

    print(f"Train : {len(train)} rows → {train_path}")
    print(f"Test  : {len(test)} rows  → {test_path}")


if __name__ == "__main__":
    params = load_params()
    ingest(
        source_path=params["paths"]["source"],
        train_path=params["paths"]["raw_train"],
        test_path=params["paths"]["raw_test"],
        test_size=params["ingest"]["test_size"],
        random_state=params["ingest"]["random_state"],
    )
