"""Tests for src.ingestion.watcher."""

import json
from threading import Event
from unittest.mock import MagicMock, patch

import pytest

from src.ingestion import (
    REQUIRED_FIELDS,
    IngestionHandler,
    ingest_file,
    start_watcher,
    validate_product,
)
from src.ingestion.watcher import FIELD_MAX_LENGTHS, MAX_FILE_BYTES


@pytest.fixture
def good_product() -> dict:
    return {
        "product_id": "prod_999",
        "name": "Test Paddle",
        "category": "paddles",
        "brand": "Acme",
        "price": 99.99,
        "description": "A test paddle.",
        "specifications": {"weight": "8.0 oz"},
        "care_instructions": "Wipe clean.",
    }


# --- validate_product -------------------------------------------------------


def test_validate_product_passes_complete_product(good_product):
    assert validate_product(good_product) is None


@pytest.mark.parametrize("missing_field", sorted(REQUIRED_FIELDS))
def test_validate_product_flags_each_missing_required_field(good_product, missing_field):
    incomplete = {k: v for k, v in good_product.items() if k != missing_field}
    reason = validate_product(incomplete)
    assert reason is not None
    assert missing_field in reason


def test_validate_product_rejects_non_dict():
    assert validate_product("not a dict") == "product is not a JSON object"
    assert validate_product([1, 2, 3]) == "product is not a JSON object"


def test_validate_product_rejects_non_dict_specifications(good_product):
    good_product["specifications"] = "not a dict"
    assert validate_product(good_product) == "specifications must be an object"


@pytest.mark.parametrize("field,limit", sorted(FIELD_MAX_LENGTHS.items()))
def test_validate_product_rejects_oversized_text_fields(good_product, field, limit):
    """F-07 verification: per-field length caps reject long values."""
    good_product[field] = "x" * (limit + 1)
    reason = validate_product(good_product)
    assert reason is not None
    assert field in reason
    assert str(limit) in reason


# --- ingest_file ------------------------------------------------------------


@pytest.fixture
def inbox(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    return inbox


@pytest.fixture
def failed(inbox):
    return inbox / "failed"


def _write_product(inbox, name: str, product: dict):
    path = inbox / name
    path.write_text(json.dumps(product))
    return path


def test_ingest_file_chunks_embeds_and_upserts_valid_product(inbox, failed, good_product):
    path = _write_product(inbox, "prod_999.json", good_product)

    with patch("src.ingestion.watcher.embed", return_value=[[0.1, 0.2]]) as embed_fn, \
         patch("src.ingestion.watcher.add") as add_fn:
        result = ingest_file(path, failed_dir=failed, debounce_s=0.0)

    assert result == "prod_999"
    embed_fn.assert_called_once()
    add_fn.assert_called_once()
    add_kwargs = add_fn.call_args.kwargs
    assert add_kwargs["ids"] == ["prod_999"]
    assert add_kwargs["metadatas"][0]["product_id"] == "prod_999"
    assert add_kwargs["metadatas"][0]["category"] == "paddles"

    # File still in inbox (we don't move successful files — let the
    # operator decide whether to clean up or archive)
    assert path.exists()


def test_ingest_file_quarantines_invalid_json(inbox, failed):
    path = inbox / "broken.json"
    path.write_text("{not valid json")

    with patch("src.ingestion.watcher.embed") as embed_fn, \
         patch("src.ingestion.watcher.add") as add_fn:
        result = ingest_file(path, failed_dir=failed, debounce_s=0.0)

    assert result is None
    embed_fn.assert_not_called()
    add_fn.assert_not_called()
    assert not path.exists()  # moved
    assert (failed / "broken.json").exists()
    error_file = failed / "broken.json.error.txt"
    assert error_file.exists()
    assert "invalid JSON" in error_file.read_text()


def test_ingest_file_quarantines_schema_violation(inbox, failed, good_product):
    bad = {k: v for k, v in good_product.items() if k != "price"}
    path = _write_product(inbox, "missing_price.json", bad)

    with patch("src.ingestion.watcher.embed") as embed_fn, \
         patch("src.ingestion.watcher.add") as add_fn:
        result = ingest_file(path, failed_dir=failed, debounce_s=0.0)

    assert result is None
    embed_fn.assert_not_called()
    add_fn.assert_not_called()
    assert not path.exists()
    assert (failed / "missing_price.json").exists()
    assert "price" in (failed / "missing_price.json.error.txt").read_text()


def test_ingest_file_skips_non_json(inbox, failed):
    path = inbox / "swapfile.tmp"
    path.write_text("anything")

    with patch("src.ingestion.watcher.embed") as embed_fn, \
         patch("src.ingestion.watcher.add") as add_fn:
        result = ingest_file(path, failed_dir=failed, debounce_s=0.0)

    assert result is None
    embed_fn.assert_not_called()
    add_fn.assert_not_called()
    assert path.exists()  # not moved
    assert not failed.exists()  # never created


def test_ingest_file_handles_missing_file(inbox, failed):
    path = inbox / "vanished.json"  # never created
    result = ingest_file(path, failed_dir=failed, debounce_s=0.0)
    assert result is None


def test_ingest_file_quarantines_oversized_file(inbox, failed):
    """F-07 verification: files larger than MAX_FILE_BYTES never reach json.loads."""
    path = inbox / "huge.json"
    # Pad past the cap with whitespace so the file is well-formed JSON
    # if it ever got parsed — proving the size check fires before parsing.
    payload = {"product_id": "x"}
    pad = " " * (MAX_FILE_BYTES + 1)
    path.write_text(json.dumps(payload) + pad)

    with patch("src.ingestion.watcher.embed") as embed_fn, \
         patch("src.ingestion.watcher.add") as add_fn:
        result = ingest_file(path, failed_dir=failed, debounce_s=0.0)

    assert result is None
    embed_fn.assert_not_called()
    add_fn.assert_not_called()
    assert not path.exists()  # quarantined
    error_text = (failed / "huge.json.error.txt").read_text()
    assert "exceeds" in error_text
    assert str(MAX_FILE_BYTES) in error_text


def test_ingest_file_quarantines_overlong_field(inbox, failed, good_product):
    """F-07 verification: field-level caps quarantine before embedding/upsert."""
    good_product["description"] = "x" * (FIELD_MAX_LENGTHS["description"] + 1)
    path = _write_product(inbox, "long_desc.json", good_product)

    with patch("src.ingestion.watcher.embed") as embed_fn, \
         patch("src.ingestion.watcher.add") as add_fn:
        result = ingest_file(path, failed_dir=failed, debounce_s=0.0)

    assert result is None
    embed_fn.assert_not_called()
    add_fn.assert_not_called()
    assert not path.exists()
    assert "description" in (failed / "long_desc.json.error.txt").read_text()


# --- IngestionHandler -------------------------------------------------------


def test_handler_on_created_calls_ingest_file(inbox, failed):
    handler = IngestionHandler(failed_dir=failed, debounce_s=0.1)
    event = MagicMock(is_directory=False, src_path=str(inbox / "x.json"))

    with patch("src.ingestion.watcher.ingest_file") as ingest:
        handler.on_created(event)

    ingest.assert_called_once()
    args = ingest.call_args
    assert args.kwargs["failed_dir"] == failed
    assert args.kwargs["debounce_s"] == 0.1


def test_handler_ignores_directory_events(inbox, failed):
    handler = IngestionHandler(failed_dir=failed)
    event = MagicMock(is_directory=True, src_path=str(inbox / "subdir"))

    with patch("src.ingestion.watcher.ingest_file") as ingest:
        handler.on_created(event)

    ingest.assert_not_called()


def test_handler_on_moved_uses_dest_path(inbox, failed):
    handler = IngestionHandler(failed_dir=failed)
    event = MagicMock(
        is_directory=False,
        src_path=str(inbox / "old.json"),
        dest_path=str(inbox / "new.json"),
    )

    with patch("src.ingestion.watcher.ingest_file") as ingest:
        handler.on_moved(event)

    assert str(ingest.call_args.args[0]) == str(inbox / "new.json")


def test_handler_swallows_unexpected_exceptions(inbox, failed, caplog):
    handler = IngestionHandler(failed_dir=failed)
    event = MagicMock(is_directory=False, src_path=str(inbox / "x.json"))

    with patch(
        "src.ingestion.watcher.ingest_file", side_effect=RuntimeError("boom")
    ):
        handler.on_created(event)  # should not raise

    assert "Unhandled error" in caplog.text


# --- start_watcher ----------------------------------------------------------


def test_start_watcher_starts_observer_and_stops_on_event(inbox, failed):
    stop_event = Event()
    stop_event.set()  # immediately stop

    fake_observer = MagicMock()
    with patch("src.ingestion.watcher.Observer", return_value=fake_observer):
        start_watcher(inbox_dir=inbox, failed_dir=failed, stop_event=stop_event)

    fake_observer.schedule.assert_called_once()
    fake_observer.start.assert_called_once()
    fake_observer.stop.assert_called_once()
    fake_observer.join.assert_called_once()


def test_start_watcher_creates_inbox_if_missing(tmp_path):
    inbox = tmp_path / "does-not-exist-yet"
    stop_event = Event()
    stop_event.set()

    with patch("src.ingestion.watcher.Observer", return_value=MagicMock()):
        start_watcher(inbox_dir=inbox, stop_event=stop_event)

    assert inbox.exists()
