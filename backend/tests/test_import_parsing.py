from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.importer.focus_csv import ImportOptions, map_columns, parse_file
from app.importer.parsing import (
    ParseError,
    parse_bool,
    parse_duration,
    parse_tags,
    parse_timestamp,
    parse_type,
)

BERLIN = ZoneInfo("Europe/Berlin")


@pytest.mark.parametrize(
    "raw, utc, offset, assumed",
    [
        ("2026-09-01T09:00:00+02:00", datetime(2026, 9, 1, 7, tzinfo=UTC), 120, False),
        ("2026-09-01T07:00:00Z", datetime(2026, 9, 1, 7, tzinfo=UTC), 0, False),
        ("2026-09-01T07:00:00.123Z", datetime(2026, 9, 1, 7, 0, 0, 123000, tzinfo=UTC), 0, False),
        ("2026-09-01 09:00:00", datetime(2026, 9, 1, 7, tzinfo=UTC), 120, True),  # naive → settings tz
        ("2026-12-01 09:00", datetime(2026, 12, 1, 8, tzinfo=UTC), 60, True),  # winter time
        ("1756890000", datetime(2025, 9, 3, 9, 0, tzinfo=UTC), 120, True),  # epoch seconds
        ("1756890000000", datetime(2025, 9, 3, 9, 0, tzinfo=UTC), 120, True),  # epoch ms
        ("Sep 1, 2026 9:00 AM -0500", datetime(2026, 9, 1, 14, tzinfo=UTC), -300, False),
    ],
)
def test_parse_timestamp(raw, utc, offset, assumed):
    ts = parse_timestamp(raw, BERLIN)
    assert (ts.utc, ts.offset_minutes, ts.assumed_timezone) == (utc, offset, assumed)


@pytest.mark.parametrize("raw", ["not-a-date", "1899-01-01T00:00:00Z", "-5"])
def test_parse_timestamp_rejects(raw):
    with pytest.raises(ParseError):
        parse_timestamp(raw, BERLIN)


def test_parse_timestamp_empty_values():
    for raw in (None, "", "  ", "null", "NaN"):
        assert parse_timestamp(raw, BERLIN) is None


@pytest.mark.parametrize(
    "raw, seconds, number",
    [
        ("1500", None, 1500.0),
        ("25,5", None, 25.5),
        ("00:25:00", 1500.0, None),
        ("1:02:03", 3723.0, None),
        ("25:30", 1530.0, None),
        ("PT1H30M", 5400.0, None),
        ("1h 30m", 5400.0, None),
        ("25 min", 1500.0, None),
        ("90s", 90.0, None),
    ],
)
def test_parse_duration(raw, seconds, number):
    d = parse_duration(raw)
    assert (d.seconds, d.number) == (seconds, number)


@pytest.mark.parametrize("raw", ["-10", "a while", "12:xx"])
def test_parse_duration_rejects(raw):
    with pytest.raises(ParseError):
        parse_duration(raw)


def test_parse_bool_type_tags():
    assert [parse_bool(v) for v in ("true", "FALSE", "1", "no", "", None)] == [
        True,
        False,
        True,
        False,
        None,
        None,
    ]
    with pytest.raises(ParseError):
        parse_bool("maybe")
    assert [parse_type(v) for v in ("Work", "focus", "Short Break", "long_break", "", None)] == [
        "work",
        "work",
        "rest",
        "rest",
        None,
        None,
    ]
    with pytest.raises(ParseError):
        parse_type("meditation")
    assert parse_tags('["python", "quant"]') == ["python", "quant"]
    assert parse_tags("python, quant;  Python |sql") == ["python", "quant", "sql"]
    assert parse_tags("#german #vocab") == ["german", "vocab"]
    assert parse_tags("deep work") == ["deep work"]
    assert parse_tags("") == []


def test_column_mapping_is_format_insensitive():
    cols = map_columns(["ID", "Start Time", "end_time", "Duration", "total_paused_time", "Type", "Tags"])
    assert cols == {
        "external_id": "ID",
        "start_time": "Start Time",
        "end_time": "end_time",
        "duration": "Duration",
        "paused": "total_paused_time",
        "type": "Type",
        "tags": "Tags",
    }


def _csv(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode()


def test_minutes_inferred_from_timestamps():
    data = _csv(
        "startTime,duration,endTime,totalPausedTime",
        "2026-09-01T09:00:00Z,25,2026-09-01T09:30:00Z,5",
        "2026-09-01T10:00:00Z,50,2026-09-01T10:50:00Z,0",
    )
    result = parse_file(data, ImportOptions())
    assert result.duration_unit == "minutes (inferred from timestamps)"
    assert [(r.active_s, r.paused_s) for r in result.rows] == [(1500, 300), (3000, 0)]


def test_milliseconds_inferred_and_end_derived():
    data = _csv(
        "startTime,duration,totalPausedTime",
        "2026-09-01T09:00:00Z,1500000,60000",
        "2026-09-01T10:00:00Z,3000000,0",
    )
    result = parse_file(data, ImportOptions())
    assert result.duration_unit == "milliseconds (inferred from magnitude)"
    row = result.rows[0]
    assert row.active_s == 1500 and row.paused_s == 60
    assert row.end_utc == datetime(2026, 9, 1, 9, 26, tzinfo=UTC)
    assert any(w.startswith("end_time_derived") for w in row.warnings)


def test_paused_inferred_when_missing():
    data = _csv("startTime,duration,endTime", "2026-09-01T09:00:00Z,1500,2026-09-01T09:35:00Z")
    row = parse_file(data, ImportOptions()).rows[0]
    assert (row.active_s, row.paused_s) == (1500, 600)
    assert any(w.startswith("paused_inferred") for w in row.warnings)


def test_semicolon_delimiter_and_bom():
    data = "﻿startTime;endTime;type\n2026-09-01T09:00:00Z;2026-09-01T09:25:00Z;Work\n".encode()
    result = parse_file(data, ImportOptions())
    assert result.rows[0].valid and result.rows[0].active_s == 1500


def test_missing_required_columns():
    result = parse_file(_csv("id,notes", "1,hello"), ImportOptions())
    assert result.file_errors and result.rows == []
    result = parse_file(_csv("startTime,notes", "2026-09-01T09:00:00Z,hello"), ImportOptions())
    assert any("end time or a duration" in e for e in result.file_errors)
