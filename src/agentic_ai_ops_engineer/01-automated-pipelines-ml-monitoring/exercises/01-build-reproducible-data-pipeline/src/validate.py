import json
import os
import sys

import great_expectations as gx
import pandas as pd
import yaml


def load_params():
    with open("params.yaml") as f:
        return yaml.safe_load(f)


def build_suite(context, val):
    suite = gx.ExpectationSuite(name="sales_data_suite")

    suite = context.suites.add(suite)

    suite.add_expectation(
        gx.expectations.ExpectTableColumnsToMatchSet(
            column_set=val["expected_columns"], exact_match=False
        )
    )

    for col in val["non_null_columns"]:
        suite.add_expectation(
            gx.expectations.ExpectColumnValuesToNotBeNull(column=col)
        )

    for col, bounds in val["value_ranges"].items():
        suite.add_expectation(
            gx.expectations.ExpectColumnValuesToBeBetween(
                column=col, min_value=bounds["min"], max_value=bounds["max"]
            )
        )

    return suite


def run_validation(df, params):
    val = params["validation"]
    report_path = params["paths"]["report"]

    context = gx.get_context(mode="ephemeral")

    data_source = context.data_sources.add_pandas(name="sales_data")
    data_asset = data_source.add_dataframe_asset(name="training_dataframe")
    batch_definition = data_asset.add_batch_definition_whole_dataframe(
        name="training_batch"
    )

    suite = build_suite(context, val)
    validation_def = gx.ValidationDefinition(
        name="sales_data_validation", data=batch_definition, suite=suite
    )
    validation_definition = context.validation_definitions.add(validation_def)
    result = validation_definition.run(batch_parameters={"dataframe": df})

    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(result.to_json_dict(), f, indent=2)

    return result


if __name__ == "__main__":
    params = load_params()
    df = pd.read_csv(params["paths"]["processed_train"])
    print(f"Validating {len(df)} rows from training set...")

    result = run_validation(df, params)

    if not result.success:
        print("Validation FAILED. Inspect the report for details.")
        sys.exit(1)

    print("Validation passed.")
