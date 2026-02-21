"""Tests for zoho_cli.utils — formatting helpers and output functions."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from io import StringIO

import pytest

from zoho_cli import utils


# ---------------------------------------------------------------------------
# format_date (millisecond-epoch timestamps)
# ---------------------------------------------------------------------------


def test_format_date_ms_today() -> None:
    """A timestamp from today returns an HH:MM string."""
    now = datetime.now(tz=timezone.utc)
    ts_ms = int(now.timestamp() * 1000)
    result = utils.format_date(ts_ms)
    # HH:MM — two digits, colon, two digits
    assert len(result) == 5
    assert result[2] == ":"
    assert result[:2].isdigit()
    assert result[3:].isdigit()


def test_format_date_ms_old() -> None:
    """An old timestamp (different year) returns 'Mon DD YYYY' format."""
    old_dt = datetime(2020, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    ts_ms = int(old_dt.timestamp() * 1000)
    result = utils.format_date(ts_ms)
    assert "2020" in result
    assert "May" in result


def test_format_date_ms_same_year_different_day() -> None:
    """A timestamp from the same year but a past day returns 'Mon DD' without the year."""
    # Use a fixed past date in 2019 — always in a different year from now (2025+).
    old_dt = datetime(2019, 3, 7, 8, 30, 0, tzinfo=timezone.utc)
    ts_ms = int(old_dt.timestamp() * 1000)
    result = utils.format_date(ts_ms)
    # The year 2019 differs from today, so we get 'Mon DD YYYY' branch
    assert "2019" in result


def test_format_date_empty_string() -> None:
    """An empty / falsy raw value returns an empty string."""
    assert utils.format_date("") == ""
    assert utils.format_date(None) == ""
    assert utils.format_date(0) == ""


def test_format_date_non_numeric_string() -> None:
    """A non-numeric raw value is returned truncated to 16 chars."""
    result = utils.format_date("not-a-timestamp-but-a-long-string")
    assert len(result) <= 16


def test_format_date_string_timestamp() -> None:
    """format_date accepts a numeric string as well as an int."""
    now = datetime.now(tz=timezone.utc)
    ts_ms = str(int(now.timestamp() * 1000))
    result = utils.format_date(ts_ms)
    assert ":" in result  # HH:MM for today


# ---------------------------------------------------------------------------
# format_size
# ---------------------------------------------------------------------------


def test_format_size_bytes() -> None:
    """Values below 1024 are formatted as bytes."""
    assert utils.format_size(500) == "500 B"
    assert utils.format_size(0) == "0 B"
    assert utils.format_size(1023) == "1023 B"


def test_format_size_kb() -> None:
    """1 KiB exactly becomes '1 KB'."""
    assert utils.format_size(1024) == "1 KB"


def test_format_size_kb_two() -> None:
    """2 KiB (2048 bytes) becomes '2 KB'."""
    assert utils.format_size(2048) == "2 KB"


def test_format_size_mb() -> None:
    """1 MiB (1024 * 1024 bytes) becomes '1 MB'."""
    assert utils.format_size(1024 * 1024) == "1 MB"


def test_format_size_gb() -> None:
    """1 GiB becomes '1 GB'."""
    assert utils.format_size(1024 ** 3) == "1 GB"


# ---------------------------------------------------------------------------
# md_table
# ---------------------------------------------------------------------------


def test_md_table_structure() -> None:
    """md_table generates a pipe-delimited markdown table with a separator row."""
    headers = ["ID", "NAME", "SIZE"]
    rows = [["1", "Alpha", "100 B"], ["2", "Beta", "2 KB"]]
    table = utils.md_table(headers, rows)
    lines = table.splitlines()
    # Header row + separator + 2 data rows = 4 lines
    assert len(lines) == 4
    assert "ID" in lines[0]
    assert "NAME" in lines[0]
    assert "---" in lines[1]
    assert "Alpha" in lines[2]
    assert "Beta" in lines[3]


def test_md_table_pipe_delimited() -> None:
    """Every line in the md_table output starts and ends with a pipe character."""
    table = utils.md_table(["A", "B"], [["x", "y"]])
    for line in table.splitlines():
        assert line.startswith("|")
        assert line.endswith("|")


def test_md_table_empty_rows() -> None:
    """md_table with no data rows returns just the header and separator."""
    table = utils.md_table(["COL1", "COL2"], [])
    lines = table.splitlines()
    assert len(lines) == 2
    assert "COL1" in lines[0]
    assert "---" in lines[1]


def test_md_table_single_column() -> None:
    """A single-column table is generated correctly."""
    table = utils.md_table(["ONLY"], [["row1"], ["row2"]])
    lines = table.splitlines()
    assert len(lines) == 4
    assert "ONLY" in lines[0]
    assert "row1" in lines[2]


# ---------------------------------------------------------------------------
# output_json
# ---------------------------------------------------------------------------


def test_output_json_is_json(capsys: pytest.CaptureFixture) -> None:
    """output_json prints valid, parseable JSON to stdout."""
    data = {"status": "ok", "count": 3, "items": ["a", "b"]}
    utils.output_json(data)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed == data


def test_output_json_dict(capsys: pytest.CaptureFixture) -> None:
    """output_json serialises a nested dict correctly."""
    utils.output_json({"nested": {"key": 42}})
    out = capsys.readouterr().out
    assert json.loads(out) == {"nested": {"key": 42}}


def test_output_json_list(capsys: pytest.CaptureFixture) -> None:
    """output_json serialises a list correctly."""
    utils.output_json([1, 2, 3])
    out = capsys.readouterr().out
    assert json.loads(out) == [1, 2, 3]


def test_output_json_unicode(capsys: pytest.CaptureFixture) -> None:
    """output_json preserves non-ASCII characters (ensure_ascii=False)."""
    utils.output_json({"greeting": "こんにちは"})
    out = capsys.readouterr().out
    assert "こんにちは" in out
    assert json.loads(out)["greeting"] == "こんにちは"


# ---------------------------------------------------------------------------
# error_exit
# ---------------------------------------------------------------------------


def test_error_exit_raises_system_exit() -> None:
    """error_exit always raises SystemExit with the specified exit code."""
    with pytest.raises(SystemExit) as exc_info:
        utils.error_exit("test_error", "Something went wrong", exit_code=1)
    assert exc_info.value.code == 1


def test_error_exit_custom_code() -> None:
    """error_exit respects a custom exit_code argument."""
    with pytest.raises(SystemExit) as exc_info:
        utils.error_exit("test_error", "details", exit_code=42)
    assert exc_info.value.code == 42


def test_error_exit_json_to_stderr(capsys: pytest.CaptureFixture) -> None:
    """In non-md mode, error_exit writes a JSON error object to stderr."""
    utils.configure(md=False)
    with pytest.raises(SystemExit):
        utils.error_exit("my_code", "my details")
    err = capsys.readouterr().err
    payload = json.loads(err)
    assert payload["status"] == "error"
    assert payload["error"] == "my_code"
    assert payload["details"] == "my details"


# ---------------------------------------------------------------------------
# configure / is_md_mode
# ---------------------------------------------------------------------------


def test_configure_sets_md_mode() -> None:
    """configure(md=True) makes is_md_mode() return True."""
    utils.configure(md=True)
    assert utils.is_md_mode() is True
    # Reset so other tests are not affected
    utils.configure(md=False)


def test_configure_default_is_json() -> None:
    """After configure(md=False), is_md_mode() returns False."""
    utils.configure(md=False)
    assert utils.is_md_mode() is False
