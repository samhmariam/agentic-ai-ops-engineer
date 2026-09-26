import os

import pandas as pd
import yaml
from sklearn.preprocessing import LabelEncoder


def load_params():
    with open("params.yaml") as f:
        return yaml.safe_load(f)


def preprocess(df, categorical_cols, drop_cols):
    # Drop columns that are not useful for modeling.
    df = df.drop(columns=drop_cols, errors="ignore")

    # Strip leading/trailing whitespace from all string columns.
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()

    df["Date"] = pd.to_datetime(df["Date"])
    df["month"] = df["Date"].dt.month
    df["day_of_week"] = df["Date"].dt.dayofweek
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

    label_encoder = LabelEncoder()
    for col in categorical_cols:
        df[col] = label_encoder.fit_transform(df[col])

    # Drop duplicate rows and rows with missing values.
    before = len(df)
    df = df.drop_duplicates().dropna()
    removed = before - len(df)
    if removed:
        print(f"Removed {removed} duplicate/null rows")

    return df


if __name__ == "__main__":
    params = load_params()
    pp = params["preprocessing"]
    splits = [
        (params["paths"]["raw_train"], params["paths"]["processed_train"]),
        (params["paths"]["raw_test"], params["paths"]["processed_test"]),
    ]

    for raw_path, processed_path in splits:
        df = pd.read_csv(raw_path)
        df = preprocess(df, pp["categorical_columns"], pp["drop_columns"])
        os.makedirs(os.path.dirname(processed_path), exist_ok=True)
        df.to_csv(processed_path, index=False)
        print(f"Saved {len(df)} rows to {processed_path}")
