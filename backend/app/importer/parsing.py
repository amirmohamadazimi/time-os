"""Tolerant value parsers for exported data. Pure functions; no database access."""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from dateutil import parser as dateutil_parser

TRUE_VALUES = {"true", "t", "yes", "y", "1"}
FALSE_VALUES = {"false", "f", "no", "n", "0"}
WORK_TYPES = {"work", "focus", "pomodoro", "session", "deepwork", "study"}
REST_TYPES = {"rest", "break", "shortbreak", "longbreak", "pause", "relax"}

_HMS = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)$")
_ISO_DURATION = re.compile(
    r"^P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$"
)
_HUMAN = re.compile(
    r"^(?:(\d+(?:\.\d+)?)\s*h(?:ours?|rs?)?)?\s*(?:(\d+(?:\.\d+)?)\s*m(?:in(?:utes?|s)?)?)?\s*(?:(\d+(?:\.\d+)?)\s*s(?:ec(?:onds?|s)?)?)?$"
)
_NUMBER = re.compile(r"^-?\d+(?:[.,]\d+)?$")


class ParseError(ValueError):
    pass


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if value == "" or value.lower() in {"null", "none", "nan", "n/a", "-"}:
        return None
    return value


@dataclass(frozen=True)
class ParsedTimestamp:
    utc: datetime
    offset_minutes: int
    assumed_timezone: bool  # local offset came from settings, not from the data


def parse_timestamp(raw: str | None, default_tz: ZoneInfo) -> ParsedTimestamp | None:
    """ISO 8601 (with Z/offset or naive), common date-time formats, or Unix epoch (s or ms)."""
    value = clean(raw)
    if value is None:
        return None
    if _NUMBER.match(value):
        number = float(value.replace(",", "."))
        if number <= 0:
            raise ParseError(f"not a valid epoch timestamp: {value}")
        seconds = number / 1000 if number > 1e11 else number  # 1e11 s is year 5138; 1e11 ms is 1973
        try:
            utc = datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise ParseError(f"epoch out of range: {value}") from exc
        local = utc.astimezone(default_tz)
        return ParsedTimestamp(utc, _offset(local), assumed_timezone=True)
    text = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = dateutil_parser.parse(value)
        except (ValueError, OverflowError) as exc:
            raise ParseError(f"unrecognised timestamp: {value}") from exc
    if parsed.year < 1990 or parsed.year > 2100:
        raise ParseError(f"timestamp year out of range: {value}")
    assumed = parsed.tzinfo is None or parsed.utcoffset() is None
    if assumed:
        parsed = parsed.replace(tzinfo=default_tz)
    return ParsedTimestamp(parsed.astimezone(UTC), _offset(parsed), assumed_timezone=assumed)


def _offset(dt: datetime) -> int:
    off = dt.utcoffset()
    return int(off.total_seconds() // 60) if off else 0


@dataclass(frozen=True)
class ParsedDuration:
    seconds: float | None  # set when the format carried its own unit (01:25:00, PT25M, 25m)
    number: float | None  # bare number whose unit is inferred file-wide


def parse_duration(raw: str | None) -> ParsedDuration | None:
    value = clean(raw)
    if value is None:
        return None
    if _NUMBER.match(value):
        number = float(value.replace(",", "."))
        if number < 0:
            raise ParseError(f"negative duration: {value}")
        return ParsedDuration(None, number)
    if m := _HMS.match(value):
        h, mnt, s = m.groups()
        return ParsedDuration(int(h or 0) * 3600 + int(mnt) * 60 + float(s), None)
    if (m := _ISO_DURATION.match(value.upper())) and any(m.groups()):
        d, h, mnt, s = (float(x) if x else 0.0 for x in m.groups())
        return ParsedDuration(d * 86400 + h * 3600 + mnt * 60 + s, None)
    if (m := _HUMAN.match(value.lower())) and any(m.groups()):
        h, mnt, s = (float(x) if x else 0.0 for x in m.groups())
        return ParsedDuration(h * 3600 + mnt * 60 + s, None)
    raise ParseError(f"unrecognised duration: {value}")


def parse_bool(raw: str | None) -> bool | None:
    value = clean(raw)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in TRUE_VALUES:
        return True
    if lowered in FALSE_VALUES:
        return False
    raise ParseError(f"not a boolean: {value}")


def parse_type(raw: str | None) -> str | None:
    """'work' or 'rest'; None when missing. Raises for unknown values."""
    value = clean(raw)
    if value is None:
        return None
    key = re.sub(r"[\s_-]", "", value.lower())
    if key in WORK_TYPES:
        return "work"
    if key in REST_TYPES:
        return "rest"
    raise ParseError(f"unknown session type: {value}")


def parse_tags(raw: str | None, max_len: int = 50, max_tags: int = 30) -> list[str]:
    value = clean(raw)
    if value is None:
        return []
    parts: list[str]
    if value.startswith("["):
        try:
            loaded = json.loads(value)
            parts = [str(x) for x in loaded] if isinstance(loaded, list) else [value]
        except json.JSONDecodeError:
            parts = re.split(r"[,;|]", value.strip("[]"))
    elif re.search(r"[,;|]", value):
        parts = re.split(r"[,;|]", value)
    elif "#" in value:
        parts = value.split()
    else:
        parts = [value]
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        tag = part.strip().strip("'\"").lstrip("#").strip()[:max_len]
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    return out[:max_tags]
