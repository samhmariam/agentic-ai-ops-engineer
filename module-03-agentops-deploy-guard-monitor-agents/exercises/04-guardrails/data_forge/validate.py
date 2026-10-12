from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
EVAL_DIR = ROOT / "evaluation"

RESTORE_HINT = "  → Run: uv run python data_forge/generate_all.py to restore datasets."

VALID_REGIONS = {"west", "north", "south", "east", "center"}
VALID_ROLES = {"analyst", "broker"}


class DataValidationError(Exception):
    pass


def _load(name: str, subdir: Path = DATA_DIR) -> pd.DataFrame:
    path = subdir / name
    if not path.exists():
        raise DataValidationError(f"Missing file: {path}\n{RESTORE_HINT}")
    return pd.read_csv(path)


# ---------------------------------------------------------------------------
# Dataset checks
# ---------------------------------------------------------------------------

def check_no_duplicate_pks():
    pk_map = {
        "listings.csv": "listing_id",
        "supply_opportunities.csv": "supply_opportunity_id",
        "demand_leads.csv": "lead_id",
        "sales.csv": "sale_id",
        "users.csv": "user_id",
    }
    for fname, pk in pk_map.items():
        df = _load(fname)
        dupes = df[df.duplicated(subset=[pk], keep=False)]
        if not dupes.empty:
            raise DataValidationError(
                f"Duplicate PKs in {fname} ({pk}):\n{dupes[[pk]].head()}\n{RESTORE_HINT}"
            )


def check_no_null_pks():
    pk_map = {
        "listings.csv": "listing_id",
        "supply_opportunities.csv": "supply_opportunity_id",
        "demand_leads.csv": "lead_id",
        "sales.csv": "sale_id",
        "users.csv": "user_id",
    }
    for fname, pk in pk_map.items():
        df = _load(fname)
        nulls = df[df[pk].isna()]
        if not nulls.empty:
            raise DataValidationError(
                f"Null PKs in {fname} ({pk}): {len(nulls)} rows\n{RESTORE_HINT}"
            )


def check_neighborhood_fk():
    nbhds = set(_load("neighborhood_profiles.csv")["neighborhood"])
    for fname in ("listings.csv", "supply_opportunities.csv"):
        df = _load(fname)
        bad = df[~df["neighborhood"].isin(nbhds)]
        if not bad.empty:
            raise DataValidationError(
                f"Unknown neighborhoods in {fname}:\n{bad[['neighborhood']].drop_duplicates()}\n{RESTORE_HINT}"
            )


def check_agent_fk():
    user_ids = set(_load("users.csv")["user_id"])
    for fname in ("listings.csv", "demand_leads.csv"):
        df = _load(fname)
        bad = df[~df["assigned_agent_id"].isin(user_ids)]
        if not bad.empty:
            raise DataValidationError(
                f"Unknown assigned_agent_id in {fname}:\n{bad[['assigned_agent_id']].drop_duplicates()}\n{RESTORE_HINT}"
            )


def check_listings_count_matches_supply_snapshot():
    supply = _load("supply_snapshot.csv")
    listings = _load("listings.csv")
    active = listings[listings["status"] == "active"]
    errors = []
    for _, row in supply.iterrows():
        region, pt, beds = row["region"], row["property_type"], int(row["bedrooms"])
        expected = int(row["active_listings"])
        actual = len(active[
            (active["region"] == region)
            & (active["property_type"] == pt)
            & (active["bedrooms"] == beds)
        ])
        if actual != expected:
            errors.append(f"  {region}/{pt}/{beds}: expected {expected} active, got {actual}")
    if errors:
        raise DataValidationError(
            "listings.csv active count mismatch with supply_snapshot.csv:\n"
            + "\n".join(errors) + f"\n{RESTORE_HINT}"
        )


def check_sales_count_matches_demand_signals():
    demand = _load("demand_signals.csv")
    sales = _load("sales.csv")
    errors = []
    for _, row in demand.iterrows():
        region, pt, beds = row["region"], row["property_type"], int(row["bedrooms"])
        expected = int(row["recent_sales"])
        actual = len(sales[
            (sales["region"] == region)
            & (sales["property_type"] == pt)
            & (sales["bedrooms"] == beds)
        ])
        if actual != expected:
            errors.append(f"  {region}/{pt}/{beds}: expected {expected} sales, got {actual}")
    if errors:
        raise DataValidationError(
            "sales.csv count mismatch with demand_signals.csv:\n"
            + "\n".join(errors) + f"\n{RESTORE_HINT}"
        )


def check_sales_listing_fk():
    listings = _load("listings.csv")
    sales = _load("sales.csv")
    valid_ids = set(listings["listing_id"])
    # Only check generated listing_ids (not historical placeholder LST-HIST-* rows)
    real_sales = sales[~sales["listing_id"].str.startswith("LST-HIST-")]
    bad = real_sales[~real_sales["listing_id"].isin(valid_ids)]
    if not bad.empty:
        raise DataValidationError(
            f"Unknown listing_id in sales.csv:\n{bad[['sale_id', 'listing_id']].head()}\n{RESTORE_HINT}"
        )


def check_sales_lead_fk():
    leads = _load("demand_leads.csv")
    sales = _load("sales.csv")
    valid_ids = set(leads["lead_id"])
    real_sales = sales[~sales["lead_id"].str.startswith("LEAD-HIST-")]
    bad = real_sales[~real_sales["lead_id"].isin(valid_ids)]
    if not bad.empty:
        raise DataValidationError(
            f"Unknown lead_id in sales.csv:\n{bad[['sale_id', 'lead_id']].head()}\n{RESTORE_HINT}"
        )


def check_sales_type_matches_listing_type():
    listings = _load("listings.csv")
    sales = _load("sales.csv")
    listing_type_map = listings.set_index("listing_id")["listing_type"].to_dict()
    real_sales = sales[~sales["listing_id"].str.startswith("LST-HIST-")]
    errors = []
    for _, row in real_sales.iterrows():
        expected_type = listing_type_map.get(row["listing_id"])
        if expected_type and row["sale_type"] != expected_type:
            errors.append(f"  sale {row['sale_id']}: sale_type={row['sale_type']} but listing is {expected_type}")
    if errors:
        raise DataValidationError(
            "sale_type/listing_type mismatch in sales.csv:\n"
            + "\n".join(errors[:5]) + f"\n{RESTORE_HINT}"
        )


def check_users_composition():
    users = _load("users.csv")
    analysts = len(users[users["role"] == "analyst"])
    brokers = len(users[users["role"] == "broker"])
    if analysts != 4:
        raise DataValidationError(
            f"users.csv: expected 4 analysts, got {analysts}\n{RESTORE_HINT}"
        )
    if brokers != 10:
        raise DataValidationError(
            f"users.csv: expected 10 brokers, got {brokers}\n{RESTORE_HINT}"
        )
    invalid_regions = users[users["role"] == "broker"][
        ~users[users["role"] == "broker"]["region_access"].apply(
            lambda x: all(r in VALID_REGIONS for r in x.split("|"))
        )
    ]
    if not invalid_regions.empty:
        raise DataValidationError(
            f"Invalid region_access values in users.csv:\n{invalid_regions[['user_id', 'region_access']]}\n{RESTORE_HINT}"
        )


# ---------------------------------------------------------------------------
# Eval suite checks
# ---------------------------------------------------------------------------

def check_eval_scenario_count():
    df = _load("eval_scenarios.csv", EVAL_DIR)
    if len(df) != 80:
        raise DataValidationError(
            f"eval_scenarios.csv: expected 80 rows, got {len(df)}\n{RESTORE_HINT}"
        )


def check_eval_no_duplicate_ids():
    df = _load("eval_scenarios.csv", EVAL_DIR)
    dupes = df[df.duplicated(subset=["scenario_id"], keep=False)]
    if not dupes.empty:
        raise DataValidationError(
            f"Duplicate scenario_id in eval_scenarios.csv:\n{dupes['scenario_id'].tolist()}\n{RESTORE_HINT}"
        )


def check_eval_no_conflicting_scenarios():
    df = _load("eval_scenarios.csv", EVAL_DIR)
    key_cols = ["user_id", "query_override", "region", "property_type", "bedrooms"]
    conflicts = (
        df.groupby(key_cols)["expected_result"]
        .nunique()
        .reset_index()
    )
    bad = conflicts[conflicts["expected_result"] > 1]
    if not bad.empty:
        raise DataValidationError(
            f"Conflicting expected_result for same scenario key:\n{bad}\n{RESTORE_HINT}"
        )


def check_eval_valid_column_values():
    df = _load("eval_scenarios.csv", EVAL_DIR)
    errors = []
    valid_baselines = {"v02", "v03", "v04"}
    valid_types = {"normal", "guardrail_input", "guardrail_tool", "guardrail_output"}
    valid_results = {"pass", "blocked"}

    bad_bl = df[~df["version_baseline"].isin(valid_baselines)]
    if not bad_bl.empty:
        errors.append(f"Invalid version_baseline: {bad_bl['version_baseline'].unique()}")

    bad_t = df[~df["type"].isin(valid_types)]
    if not bad_t.empty:
        errors.append(f"Invalid type: {bad_t['type'].unique()}")

    bad_r = df[~df["expected_result"].isin(valid_results)]
    if not bad_r.empty:
        errors.append(f"Invalid expected_result: {bad_r['expected_result'].unique()}")

    if errors:
        raise DataValidationError(
            "Invalid column values in eval_scenarios.csv:\n"
            + "\n".join(errors) + f"\n{RESTORE_HINT}"
        )


def check_eval_user_id_fk():
    df = _load("eval_scenarios.csv", EVAL_DIR)
    users = _load("users.csv")
    valid_ids = set(users["user_id"]) | {""}  # empty = guest
    non_empty = df[df["user_id"].notna() & (df["user_id"] != "")]
    bad = non_empty[~non_empty["user_id"].isin(valid_ids)]
    if not bad.empty:
        raise DataValidationError(
            f"Unknown user_id in eval_scenarios.csv:\n{bad[['scenario_id', 'user_id']].head()}\n{RESTORE_HINT}"
        )


def check_eval_blocked_has_reason():
    df = _load("eval_scenarios.csv", EVAL_DIR)
    blocked = df[df["expected_result"] == "blocked"]
    missing = blocked[blocked["expected_reason"].isna() | (blocked["expected_reason"] == "")]
    if not missing.empty:
        raise DataValidationError(
            f"Blocked scenarios missing expected_reason:\n{missing['scenario_id'].tolist()}\n{RESTORE_HINT}"
        )


def check_eval_normal_has_must_contain():
    df = _load("eval_scenarios.csv", EVAL_DIR)
    normal_pass = df[(df["type"] == "normal") & (df["expected_result"] == "pass")]
    missing = normal_pass[normal_pass["must_contain"].isna() | (normal_pass["must_contain"] == "")]
    if not missing.empty:
        raise DataValidationError(
            f"Normal pass scenarios missing must_contain:\n{missing['scenario_id'].tolist()}\n{RESTORE_HINT}"
        )


def check_eval_type_distribution():
    df = _load("eval_scenarios.csv", EVAL_DIR)
    v02_count = len(df[df["version_baseline"] == "v02"])
    if v02_count != 20:
        raise DataValidationError(
            f"eval_scenarios.csv: expected 20 v02 regression rows, got {v02_count}\n{RESTORE_HINT}"
        )
    for sc_type in ("guardrail_input", "guardrail_tool", "guardrail_output"):
        count = len(df[df["type"] == sc_type])
        if count < 10:
            raise DataValidationError(
                f"eval_scenarios.csv: {sc_type} has only {count} rows (minimum 10)\n{RESTORE_HINT}"
            )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    ("no duplicate PKs",                  check_no_duplicate_pks),
    ("no null PKs",                        check_no_null_pks),
    ("neighborhood FK integrity",          check_neighborhood_fk),
    ("agent FK integrity",                 check_agent_fk),
    ("listings count = supply_snapshot",   check_listings_count_matches_supply_snapshot),
    ("sales count = demand_signals",       check_sales_count_matches_demand_signals),
    ("sales.listing_id FK",               check_sales_listing_fk),
    ("sales.lead_id FK",                  check_sales_lead_fk),
    ("sale_type matches listing_type",     check_sales_type_matches_listing_type),
    ("users composition",                  check_users_composition),
    ("eval: 80 rows",                      check_eval_scenario_count),
    ("eval: no duplicate scenario_ids",    check_eval_no_duplicate_ids),
    ("eval: no conflicting scenarios",     check_eval_no_conflicting_scenarios),
    ("eval: valid column values",          check_eval_valid_column_values),
    ("eval: user_id FK",                  check_eval_user_id_fk),
    ("eval: blocked rows have reason",     check_eval_blocked_has_reason),
    ("eval: normal pass rows have must_contain", check_eval_normal_has_must_contain),
    ("eval: type distribution",            check_eval_type_distribution),
]


def run_all() -> bool:
    failures = []
    for name, fn in ALL_CHECKS:
        try:
            fn()
        except DataValidationError as e:
            failures.append((name, str(e)))

    if failures:
        print(f"VALIDATION FAILED — {len(failures)}/{len(ALL_CHECKS)} checks failed:\n")
        for name, msg in failures:
            print(f"✗ {name}\n  {msg}\n")
        return False

    print(f"All {len(ALL_CHECKS)} data integrity checks passed.")
    return True


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
