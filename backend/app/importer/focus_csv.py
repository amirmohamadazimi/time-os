"""Parse a focus-session CSV export into validated, normalised rows. Pure: no database access.

Expected (case/format-insensitive) columns: id, startTime, duration, endTime, totalPausedTime,
completed, stopped, type, notes, tags. Only a start time plus either an end time or a duration
is required; everything else is optional.

Multi-section exports (FocusMeter writes ``Name: sessions``, ``Name: timeblocks``, … blocks in
one file) are split first: the ``sessions`` block is imported, and ``timeblocks`` (the app's own
running intervals per session) supply the exact active time and pause count when present.
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


SECTION_HEADER = re.compile(r"^\s*Name:\s*(\S[^,]*?)\s*,*\s*$")
DurationMeaning = Literal["actual", "planned"]


@dataclass(frozen=True)
class ImportOptions:
    default_timezone: str = "UTC"
    duration_unit: DurationUnit = "auto"
    long_active_minutes: int = 240
    long_pause_minutes: int = 120
    implausible_elapsed_hours: int = 16
    duplicate_tolerance_seconds: int = 60
    short_session_seconds: int = 60


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
    planned_s: int | None = None
    pause_count: int | None = None
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
    _reported_s: float | None = None  # the duration column, in seconds
    _times_given: bool = False  # both timestamps came from the file (neither was derived)

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
    duration_meaning: DurationMeaning = "actual"
    sections: list[str] = field(default_factory=list)  # names, for multi-section exports


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


def split_sections(text: str) -> dict[str, str] | None:
    """``{"sessions": csv_text, …}`` for a multi-section export, else None."""
    lines = text.splitlines()
    first = next((line for line in lines if line.strip()), "")
    if not SECTION_HEADER.match(first):
        return None
    sections: dict[str, list[str]] = {}
    current: list[str] = []
    for line in lines:
        match = SECTION_HEADER.match(line)
        if match:
            current = sections.setdefault(match.group(1).strip().lower(), [])
        else:
            current.append(line)
    return {name: "\n".join(body).strip("\n") for name, body in sections.items()}


def _timeblocks(text: str | None) -> dict[str, tuple[float, int]]:
    """session id -> (sum of block durations as written, number of blocks)."""
    if not text:
        return {}
    reader = csv.DictReader(io.StringIO(text, newline=""))
    by_norm = {_norm_header(h): h for h in reader.fieldnames or [] if h}
    sid, dur = by_norm.get("sessionid"), by_norm.get("duration")
    if not sid or not dur:
        return {}
    out: dict[str, tuple[float, int]] = {}
    for rec in reader:
        key, value = clean(rec.get(sid)), clean(rec.get(dur))
        try:
            seconds = float(value) if value is not None else None
        except ValueError:
            seconds = None
        if key is None or seconds is None or seconds < 0:
            continue
        total, count = out.get(key, (0.0, 0))
        out[key] = (total + seconds, count + 1)
    return out


def parse_file(data: bytes, options: ImportOptions) -> ParseResult:
    text = decode(data)
    tz = ZoneInfo(options.default_timezone)
    sections = split_sections(text)
    blocks: dict[str, tuple[float, int]] = {}
    if sections is not None:
        if not sections:
            return ParseResult([], {}, options.duration_unit, ["empty_file: no sections"])
        blocks = _timeblocks(sections.get("timeblocks"))
        text = sections.get("sessions") or next(iter(sections.values()))
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
        return ParseResult([], columns, options.duration_unit, file_errors, sections=list(sections or {}))

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
    factor = UNIT_FACTORS[unit.split(" ")[0]]
    for row in rows:
        _derive(row, factor, options, blocks.get(row.external_id or ""))
    meaning = duration_meaning(rows)
    for row in rows:
        _apply_duration_meaning(row, meaning)
    _mark_in_file_duplicates(rows, options.duplicate_tolerance_seconds)
    return ParseResult(rows, columns, unit, [], meaning, list(sections or {}))


def _get(row: ParsedRow, columns: dict[str, str], key: str) -> str | None:
    header = columns.get(key)
    return row.raw.get(header) if header else None


def _parse_fields(row: ParsedRow, columns: dict[str, str], tz: ZoneInfo) -> None:
    row.external_id = clean(_get(row, columns, "external_id"))
    for key, attr in (("start_time", "start_utc"), ("end_time", "end_utc")):
        value = clean(_get(row, columns, key))
        if key == "end_time" and value is not None and (value == "0" or value.startswith("1970-01-01")):
            # Apps write the Unix epoch as the end of a session that was still running at export.
            row.error("unfinished_session", "no end time yet: the session was still running when exported")
            continue
        try:
            ts = parse_timestamp(value, tz)
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


def _derive(
    row: ParsedRow, factor: float, options: ImportOptions, blocks: tuple[float, int] | None = None
) -> None:
    duration = _seconds(row._duration, factor)
    paused = _seconds(row._paused, factor)
    row._reported_s = duration
    row._times_given = row.start_utc is not None and row.end_utc is not None
    if any(e.startswith("unfinished_session") for e in row.errors):
        return
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
    if blocks is not None:
        # The app's own running intervals: more exact than end - start - paused, which misses time a
        # finished timer sat waiting for the user.
        block_active = min(blocks[0] * factor, elapsed)
        if abs(block_active - active) > max(60.0, 0.02 * elapsed):
            row.warn(
                "active_from_timeblocks",
                f"timestamps imply {active:.0f}s active, the app's timer blocks {block_active:.0f}s; "
                "timer blocks used",
            )
        active, paused = block_active, elapsed - block_active
        row.pause_count = max(blocks[1] - 1, 0)
    row.active_s = int(round(active))
    row.paused_s = int(round(paused))

    if elapsed == 0:
        row.quality_flags.append("zero_length")
    elif active < options.short_session_seconds:
        row.quality_flags.append("too_short")
    if active > options.long_active_minutes * 60:
        row.quality_flags.append("long_active")
    if paused > options.long_pause_minutes * 60:
        row.quality_flags.append("long_pause")
    if elapsed > options.implausible_elapsed_hours * 3600:
        row.quality_flags.append("implausible_elapsed")
    for flag in row.quality_flags:
        row.warn(flag)
    flags = set(row.quality_flags)
    # A long elapsed time explained by pauses is fine; only a long *active* time means the timer ran away.
    row.exclude_from_stats = bool(
        {"zero_length", "too_short"} & flags or {"implausible_elapsed", "long_active"} <= flags
    )


def duration_meaning(rows: list[ParsedRow]) -> DurationMeaning:
    """Is the duration column the time actually worked, or the timer's planned target?

    Pomodoro-style apps (FocusMeter, …) export the target: completed sessions match it, stopped
    sessions fall short of it. Decided once per file from rows with both timestamps.
    """

    def tolerance(row: ParsedRow) -> float:
        return max(60.0, 0.05 * (row.active_s or 0))

    measured = [r for r in rows if r.valid and r._times_given and r._reported_s is not None]
    completed = [r for r in measured if r.end_reason == "completed"]
    stopped = [r for r in measured if r.end_reason == "stopped"]
    if len(completed) < 3 or len(stopped) < 3:
        return "actual"
    matches = sum(abs(r._reported_s - r.active_s) <= tolerance(r) for r in completed) / len(completed)
    short = sum(r._reported_s > r.active_s + tolerance(r) for r in stopped) / len(stopped)
    return "planned" if matches >= 0.9 and short >= 0.8 else "actual"


def _apply_duration_meaning(row: ParsedRow, meaning: DurationMeaning) -> None:
    if not row.valid or row._reported_s is None or row.active_s is None:
        return
    if meaning == "planned":
        row.planned_s = int(round(row._reported_s)) if row._reported_s > 0 else None
        return
    if not row._times_given:
        return
    elapsed = row.active_s + row.paused_s
    tolerance = max(60.0, 0.05 * elapsed)
    if abs(row._reported_s - row.active_s) > tolerance and abs(row._reported_s - elapsed) > tolerance:
        row.warn(
            "duration_mismatch",
            f"reported duration {row._reported_s:.0f}s vs active {row.active_s}s from timestamps; "
            "timestamps used",
        )


class SessionIndex:
    """Finds the same session recorded twice: same type, start and active duration within a tolerance,
    and overlapping in time. Overlap matters: two real sessions a few seconds apart (accidental taps)
    have similar starts and durations but cannot overlap, because only one timer runs at a time."""

    def __init__(self, tolerance_s: int):
        self.tol = max(tolerance_s, 0)
        self.bucket = max(self.tol, 1)
        self._items: dict[int, list[tuple[datetime, datetime, int | None, str, str]]] = {}

    def add(self, start: datetime, end: datetime, active_s: int | None, type_: str, label: str) -> None:
        key = int(start.timestamp()) // self.bucket
        self._items.setdefault(key, []).append((start, end, active_s, type_, label))

    def find(self, start: datetime, end: datetime, active_s: int | None, type_: str) -> str | None:
        key = int(start.timestamp()) // self.bucket
        slack = timedelta(seconds=1)
        for k in (key - 1, key, key + 1):
            for other_start, other_end, other_active, other_type, label in self._items.get(k, ()):
                if other_type != type_ or abs((other_start - start).total_seconds()) > self.tol:
                    continue
                if start > other_end + slack or other_start > end + slack:
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
        match = index.find(row.start_utc, row.end_utc, row.active_s, row.type)
        if match:
            row.duplicate_of = f"{match} (same start and duration)"
            continue
        index.add(row.start_utc, row.end_utc, row.active_s, row.type, f"row {row.row_number}")
