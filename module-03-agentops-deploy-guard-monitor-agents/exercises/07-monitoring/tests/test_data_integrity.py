import sys
from pathlib import Path

import pytest

# Allow importing data_forge without installing it
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_forge.validate import (
    DataValidationError,
    check_agent_fk,
    check_eval_blocked_has_reason,
    check_eval_no_conflicting_scenarios,
    check_eval_no_duplicate_ids,
    check_eval_normal_has_must_contain,
    check_eval_scenario_count,
    check_eval_type_distribution,
    check_eval_user_id_fk,
    check_eval_valid_column_values,
    check_listings_count_matches_supply_snapshot,
    check_neighborhood_fk,
    check_no_duplicate_pks,
    check_no_null_pks,
    check_sales_count_matches_demand_signals,
    check_sales_lead_fk,
    check_sales_listing_fk,
    check_sales_type_matches_listing_type,
    check_users_composition,
)

RESTORE_HINT = "Run: uv run python data_forge/generate_all.py to restore datasets."


def _run(check_fn):
    try:
        check_fn()
    except DataValidationError as e:
        pytest.fail(f"{e}\n{RESTORE_HINT}")


def test_no_duplicate_pks():
    _run(check_no_duplicate_pks)


def test_no_null_pks():
    _run(check_no_null_pks)


def test_neighborhood_fk_integrity():
    _run(check_neighborhood_fk)


def test_agent_fk_integrity():
    _run(check_agent_fk)


def test_listings_count_matches_supply_snapshot():
    _run(check_listings_count_matches_supply_snapshot)


def test_sales_count_matches_demand_signals():
    _run(check_sales_count_matches_demand_signals)


def test_sales_listing_fk():
    _run(check_sales_listing_fk)


def test_sales_lead_fk():
    _run(check_sales_lead_fk)


def test_sales_type_matches_listing_type():
    _run(check_sales_type_matches_listing_type)


def test_users_composition():
    _run(check_users_composition)


def test_eval_scenario_count():
    _run(check_eval_scenario_count)


def test_eval_no_duplicate_ids():
    _run(check_eval_no_duplicate_ids)


def test_eval_no_conflicting_scenarios():
    _run(check_eval_no_conflicting_scenarios)


def test_eval_valid_column_values():
    _run(check_eval_valid_column_values)


def test_eval_user_id_fk():
    _run(check_eval_user_id_fk)


def test_eval_blocked_has_reason():
    _run(check_eval_blocked_has_reason)


def test_eval_normal_has_must_contain():
    _run(check_eval_normal_has_must_contain)


def test_eval_type_distribution():
    _run(check_eval_type_distribution)
