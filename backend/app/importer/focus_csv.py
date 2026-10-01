"""Parse a focus-session CSV export into validated, normalised rows. Pure: no database access.

Expected (case/format-insensitive) columns: id, startTime, duration, endTime, totalPausedTime,
completed, stopped, type, notes, tags. Only a start time plus either an end time or a duration
is required; everything else is optional.
"""

import csv
import io
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.importer.parsing import (
    ParsedDuration,
    ParseError,
    clean,
    parse_bool,
    parse_duration,
    parse_tags,
    parse_timestamp,
    parse_type,
)

DurationUnit = Literal["auto", "seconds", "milliseconds", "minutes"]
UNIT_FACTORS = {"seconds": 1.0, "milliseconds": 0.001, "minutes": 60.0}

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "external_id": ("id", "sessionid", "uuid"),
    "start_time": ("starttime", "start", "startedat", "startdate", "begin", "begintime"),
    "end_time": ("endtime", "end", "endedat", "enddate", "finishtime", "stoptime"),
    "duration": ("duration", "durations", "length", "activeduration", "focusduration", "focustime"),
    "paused": ("totalpausedtime", "pausedtime", "paused", "pausetime", "pausedduration", "pauseduration"),
    "completed": ("completed", "complete", "iscompleted"),
    "stopped": ("stopped", "isstopped", "interrupted"),
    "type": ("type", "sessiontype", "kind", "mode"),
    "notes": ("notes", "note", "comment", "comments", "description"),
    "tags": ("tags", "tag", "labels", "label"),
}


@dataclass(frozen=True)
class ImportOptions:
    default_timezone: str = "UTC"
    duration_unit: DurationUnit = "auto"
    long_active_minutes: int = 240
    long_pause_minutes: int = 120
    implausible_elapsed_hours: int = 16
    duplicate_tolerance_seconds: int = 60


@dataclass
class ParsedRow:
    row_number: int
    raw: dict[str, str | None]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    external_id: str | None = None
    start_utc: datetime | None = None
    end_utc: datetime | None = None
    tz_offset_minutes: int = 0
    active_s: int | None = None
    paused_s: int = 0
    type: str = "work"
    end_reason: str = "unknown"
    notes: str | None = None
    tags: list[str] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)
    exclude_from_stats: bool = False
    duplicate_of: str | None = None  # set by duplicate detection
    # intermediate parse results
    _duration: ParsedDuration | None = None
    _paused: ParsedDuration | None = None
    _assumed_tz: bool = False

    @property
    def valid(self) -> bool:
        return not self.errors

    def error(self, code: str, detail: str = "") -> None:
        self.errors.append(f"{code}: {detail}" if detail else code)

    def warn(self, code: str, detail: str = "") -> None:
        self.warnings.append(f"{code}: {detail}" if detail else code)


@dataclass
class ParseResult:
    rows: list[ParsedRow]
    columns: dict[str, str]  # canonical name -> header in the file
    duration_unit: str
    file_errors: list[str]


def _norm_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def map_columns(headers: list[str]) -> dict[str, str]:
    by_norm = {_norm_header(h): h for h in headers if h}
    mapping: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in by_norm:
                mapping[canonical] = by_norm[alias]
                break
    return mapping


def decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(encoding)
            if "\x00" not in text:
                return text
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _dialect(sample: str) -> type[csv.Dialect] | csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def parse_file(data: bytes, options: ImportOptions) -> ParseResult:
    text = decode(data)
    tz = ZoneInfo(options.default_timezone)
    reader = csv.reader(io.StringIO(text, newline=""), _dialect(text[:20000]))
    try:
        headers = [h.strip() for h in next(reader)]
    except StopIteration:
        return ParseResult([], {}, options.duration_unit, ["empty_file: no header row"])
    columns = map_columns(headers)
    file_errors = []
    if "start_time" not in columns and "end_time" not in columns:
        file_errors.append("missing_column: no start time column (e.g. startTime)")
    if "end_time" not in columns and "duration" not in columns:
        file_errors.append("missing_column: need an end time or a duration column")
    if file_errors:
        return ParseResult([], columns, options.duration_unit, file_errors)

    rows: list[ParsedRow] = []
    for index, cells in enumerate(reader, start=2):  # spreadsheet numbering: header is row 1
        if not any(c.strip() for c in cells):
            continue
        raw = {h: (cells[i] if i < len(cells) else None) for i, h in enumerate(headers)}
        if len(cells) > len(headers):
            raw["__extra__"] = ",".join(cells[len(headers) :])
        row = ParsedRow(row_number=index, raw=raw)
        if len(cells) != len(headers):
            row.error("malformed_row", f"expected {len(headers)} fields, found {len(cells)}")
        _parse_fields(row, columns, tz)
        rows.append(row)

    unit = options.duration_unit if options.duration_unit != "auto" else infer_unit(rows)
    for row in rows:
        _derive(row, UNIT_FACTORS[unit.split(" ")[0]], options)
    _mark_in_file_duplicates(rows, options.duplicate_tolerance_seconds)
    return ParseResult(rows, columns, unit, [])


def _get(row: ParsedRow, columns: dict[str, str], key: str) -> str | None:
    header = columns.get(key)
    return row.raw.get(header) if header else None


def _parse_fields(row: ParsedRow, columns: dict[str, str], tz: ZoneInfo) -> None:
    row.external_id = clean(_get(row, columns, "external_id"))
    for key, attr in (("start_time", "start_utc"), ("end_time", "end_utc")):
        try:
            ts = parse_timestamp(_get(row, columns, key), tz)
        except ParseError as exc:
            row.error(f"invalid_{key}", str(exc))
            continue
        if ts is not None:
            setattr(row, attr, ts.utc)
            if key == "start_time" or row.start_utc is None:
                row.tz_offset_minutes = ts.offset_minutes
                row._assumed_tz = ts.assumed_timezone
    for key, attr in (("duration", "_duration"), ("paused", "_paused")):
        try:
            setattr(row, attr, parse_duration(_get(row, columns, key)))
        except ParseError as exc:
            row.error(f"invalid_{key}", str(exc))
    flags = {}
    for key in ("completed", "stopped"):
        try:
            flags[key] = parse_bool(_get(row, columns, key))
        except ParseError as exc:
            row.warn("invalid_boolean", str(exc))
            flags[key] = None
    if flags["completed"] and flags["stopped"]:
        row.warn("conflicting_flags", "both completed and stopped are true; treated as completed")
    row.end_reason = "completed" if flags["completed"] else "stopped" if flags["stopped"] else "unknown"
    try:
        session_type = parse_type(_get(row, columns, "type"))
        if session_type is None and "type" in columns:
            row.warn("type_missing", "treated as work")
        row.type = session_type or "work"
    except ParseError as exc:
        row.error("unknown_type", str(exc))
    row.notes = clean(_get(row, columns, "notes"))
    row.tags = parse_tags(_get(row, columns, "tags"))


def infer_unit(rows: list[ParsedRow]) -> str:
    """Choose one unit for bare-number durations across the whole file.

    Rows with both timestamps vote: the unit that best reproduces the elapsed (or
    elapsed-minus-paused) time wins. Without such rows, fall back to magnitude.
    """
    errors: dict[str, list[float]] = {u: [] for u in UNIT_FACTORS}
    numbers: list[float] = []
    for row in rows:
        if row._duration is None or row._duration.number is None:
            continue
        numbers.append(row._duration.number)
        if row.start_utc and row.end_utc and row.end_utc > row.start_utc:
            elapsed = (row.end_utc - row.start_utc).total_seconds()
            for unit, factor in UNIT_FACTORS.items():
                paused = 0.0
                if row._paused is not None:
                    paused = (
                        row._paused.seconds
                        if row._paused.seconds is not None
                        else row._paused.number * factor
                    )
                candidate = row._duration.number * factor
                err = min(abs(elapsed - paused - candidate), abs(elapsed - candidate)) / elapsed
                errors[unit].append(err)
    if errors["seconds"]:
        best = min(UNIT_FACTORS, key=lambda u: statistics.median(errors[u]))
        return f"{best} (inferred from timestamps)"
    if not numbers:
        return "seconds"
    median = statistics.median(numbers)
    if median > 100_000:
        return "milliseconds (inferred from magnitude)"
    if median <= 300:
        return "minutes (inferred from magnitude)"
    return "seconds (inferred from magnitude)"


def _seconds(parsed: ParsedDuration | None, factor: float) -> float | None:
    if parsed is None:
        return None
    return parsed.seconds if parsed.seconds is not None else parsed.number * factor


def _derive(row: ParsedRow, factor: float, options: ImportOptions) -> None:
    duration = _seconds(row._duration, factor)
    paused = _seconds(row._paused, factor)
    if row.start_utc is None and row.end_utc is not None and duration is not None:
        row.start_utc = row.end_utc - timedelta(seconds=duration + (paused or 0))
        row.warn("start_time_derived", "computed from end time and duration")
    if row.start_utc is None:
        if not any(e.startswith("invalid_start_time") for e in row.errors):
            row.error("missing_start_time")
        return
    if row.end_utc is None:
        if duration is None:
            if not any(e.startswith(("invalid_end_time", "invalid_duration")) for e in row.errors):
                row.error("missing_end_and_duration", "need an end time or a duration")
            return
        row.end_utc = row.start_utc + timedelta(seconds=duration + (paused or 0))
        row.warn("end_time_derived", "computed from start time, duration and paused time")
    if row._assumed_tz:
        row.warn("assumed_timezone", f"no offset in data; used {options.default_timezone}")

    elapsed = (row.end_utc - row.start_utc).total_seconds()
    if elapsed < 0:
        row.error("end_before_start", f"end is {abs(elapsed):.0f}s before start")
        return
    if paused is None:
        paused = 0.0
        if duration is not None and duration < elapsed - max(60.0, 0.02 * elapsed):
            paused = elapsed - duration
            row.warn(
                "paused_inferred", f"no paused time given; inferred {paused:.0f}s from elapsed - duration"
            )
    if paused > elapsed + 1:
        row.error("paused_exceeds_elapsed", f"paused {paused:.0f}s > elapsed {elapsed:.0f}s")
        return
    paused = min(paused, elapsed)
    active = elapsed - paused
    if duration is not None:
        tolerance = max(60.0, 0.05 * elapsed)
        if abs(duration - active) > tolerance and abs(duration - elapsed) > tolerance:
            row.warn(
                "duration_mismatch",
                f"reported duration {duration:.0f}s vs active {active:.0f}s from timestamps; timestamps used",
            )
    row.active_s = int(round(active))
    row.paused_s = int(round(paused))

    if elapsed == 0:
        row.quality_flags.append("zero_length")
    if active > options.long_active_minutes * 60:
        row.quality_flags.append("long_active")
    if paused > options.long_pause_minutes * 60:
        row.quality_flags.append("long_pause")
    if elapsed > options.implausible_elapsed_hours * 3600:
        row.quality_flags.append("implausible_elapsed")
    for flag in row.quality_flags:
        row.warn(flag)
    row.exclude_from_stats = bool({"zero_length", "implausible_elapsed"} & set(row.quality_flags))


class SessionIndex:
    """Finds sessions of the same type whose start (and active duration) match within a tolerance."""

    def __init__(self, tolerance_s: int):
        self.tol = max(tolerance_s, 0)
        self.bucket = max(self.tol, 1)
        self._items: dict[int, list[tuple[datetime, int | None, str, str]]] = {}

    def add(self, start: datetime, active_s: int | None, type_: str, label: str) -> None:
        key = int(start.timestamp()) // self.bucket
        self._items.setdefault(key, []).append((start, active_s, type_, label))

    def find(self, start: datetime, active_s: int | None, type_: str) -> str | None:
        key = int(start.timestamp()) // self.bucket
        for k in (key - 1, key, key + 1):
            for other_start, other_active, other_type, label in self._items.get(k, ()):
                if other_type != type_ or abs((other_start - start).total_seconds()) > self.tol:
                    continue
                if active_s is None or other_active is None or abs(active_s - other_active) <= self.tol:
                    return label
        return None


def _mark_in_file_duplicates(rows: list[ParsedRow], tol: int) -> None:
    seen_ids: dict[str, int] = {}
    index = SessionIndex(tol)
    for row in rows:
        if not row.valid:
            continue
        if row.external_id:
            if row.external_id in seen_ids:
                row.duplicate_of = f"row {seen_ids[row.external_id]} (same id)"
                continue
            seen_ids[row.external_id] = row.row_number
        match = index.find(row.start_utc, row.active_s, row.type)
        if match:
            row.duplicate_of = f"{match} (same start and duration)"
            continue
        index.add(row.start_utc, row.active_s, row.type, f"row {row.row_number}")
