"""Deterministic productivity metrics over a session DataFrame (see frame.py). Pure functions."""

from datetime import date, datetime, timedelta

import pandas as pd

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
# Sessions that ended because the user moved on (skip/switch) say nothing about completion.
COMPLETION_REASONS = ("completed", "stopped", "unknown")


def _minutes(seconds: float) -> float:
    return round(float(seconds) / 60, 1)


def completion_rate(df: pd.DataFrame) -> float | None:
    eligible = df[df["end_reason"].isin(COMPLETION_REASONS)]
    if eligible.empty:
        return None
    return round(float((eligible["end_reason"] == "completed").mean()), 3)


def interrupted_mask(df: pd.DataFrame) -> pd.Series:
    return (df["paused_s"] > 0) | (df["pause_count"].fillna(0) > 0)


def summary(work: pd.DataFrame, rest: pd.DataFrame) -> dict:
    durations = work["active_s"]
    days = work["local_date"].nunique()
    return {
        "total_focus_minutes": _minutes(durations.sum()),
        "total_rest_minutes": _minutes(rest["active_s"].sum()),
        "session_count": len(work),
        "rest_session_count": len(rest),
        "active_days": int(days),
        "avg_daily_focus_minutes": _minutes(durations.sum() / days) if days else None,
        "avg_session_minutes": _minutes(durations.mean()) if len(work) else None,
        "median_session_minutes": _minutes(durations.median()) if len(work) else None,
        "longest_session_minutes": _minutes(durations.max()) if len(work) else None,
        "total_paused_minutes": _minutes(work["paused_s"].sum()),
        "completed_sessions": int((work["end_reason"] == "completed").sum()),
        "stopped_sessions": int((work["end_reason"] == "stopped").sum()),
        "skipped_sessions": int((work["end_reason"] == "skipped").sum()),
        "switched_sessions": int((work["end_reason"] == "switched").sum()),
        "unknown_end_sessions": int((work["end_reason"] == "unknown").sum()),
        "interrupted_sessions": int(interrupted_mask(work).sum()) if len(work) else 0,
        "completion_rate": completion_rate(work),
        "interruption_rate": round(float(interrupted_mask(work).mean()), 3) if len(work) else None,
    }


def _period_start(d: date, granularity: str) -> date:
    if granularity == "week":
        return d - timedelta(days=d.weekday())
    if granularity == "month":
        return d.replace(day=1)
    return d


def _next_period(d: date, granularity: str) -> date:
    if granularity == "week":
        return d + timedelta(days=7)
    if granularity == "month":
        return (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return d + timedelta(days=1)


def timeseries(
    df: pd.DataFrame, granularity: str, date_from: date | None, date_to: date | None
) -> list[dict]:
    if df.empty and not (date_from and date_to):
        return []
    start = date_from or df["local_date"].min()
    end = date_to or df["local_date"].max()
    buckets: dict[date, list[float]] = {}
    cursor = _period_start(start, granularity)
    while cursor <= end:
        buckets[cursor] = [0.0, 0]
        cursor = _next_period(cursor, granularity)
    for d, secs in zip(df["local_date"], df["active_s"], strict=True):
        key = _period_start(d, granularity)
        if key in buckets:
            buckets[key][0] += secs
            buckets[key][1] += 1
    return [{"period": k, "focus_minutes": _minutes(v[0]), "sessions": int(v[1])} for k, v in buckets.items()]


def _spread_over_hours(local_start: datetime, elapsed_s: float, active_s: float) -> dict[int, float]:
    """Active seconds attributed to each local clock hour the session overlapped."""
    if elapsed_s <= 0:
        return {local_start.hour: active_s}
    ratio = active_s / elapsed_s
    out: dict[int, float] = {}
    cursor, end = local_start, local_start + timedelta(seconds=elapsed_s)
    while cursor < end:
        next_hour = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        chunk_end = min(next_hour, end)
        out[cursor.hour] = out.get(cursor.hour, 0.0) + (chunk_end - cursor).total_seconds() * ratio
        cursor = chunk_end
    return out


def by_hour(df: pd.DataFrame) -> list[dict]:
    focus = [0.0] * 24
    for start, elapsed, active in zip(df["local_start"], df["elapsed_s"], df["active_s"], strict=True):
        for hour, secs in _spread_over_hours(start, elapsed, active).items():
            focus[hour] += secs
    rows = []
    for hour in range(24):
        started = df[df["hour"] == hour]
        rows.append({
            "hour": hour,
            "focus_minutes": _minutes(focus[hour]),
            "sessions_started": len(started),
            "avg_session_minutes": _minutes(started["active_s"].mean()) if len(started) else None,
            "completion_rate": completion_rate(started),
        })  # fmt: skip
    return rows


def count_weekdays(date_from: date, date_to: date) -> list[int]:
    counts = [0] * 7
    if date_to < date_from:
        return counts
    total = (date_to - date_from).days + 1
    full_weeks, extra = divmod(total, 7)
    counts = [full_weeks] * 7
    for i in range(extra):
        counts[(date_from.weekday() + i) % 7] += 1
    return counts


def by_weekday(df: pd.DataFrame, date_from: date | None, date_to: date | None) -> list[dict]:
    if df.empty and not (date_from and date_to):
        span = [0] * 7
    else:
        span = count_weekdays(date_from or df["local_date"].min(), date_to or df["local_date"].max())
    rows = []
    for wd in range(7):
        part = df[df["weekday"] == wd]
        total = part["active_s"].sum()
        rows.append({
            "weekday": wd,
            "name": WEEKDAYS[wd],
            "focus_minutes": _minutes(total),
            "days_in_range": span[wd],
            "avg_daily_focus_minutes": _minutes(total / span[wd]) if span[wd] else None,
            "sessions": len(part),
            "avg_session_minutes": _minutes(part["active_s"].mean()) if len(part) else None,
            "completion_rate": completion_rate(part),
        })  # fmt: skip
    return rows


def by_key(df: pd.DataFrame, key: str) -> list[dict]:
    """Focus allocation by a column (e.g. project_id). Missing keys are grouped under None."""
    if df.empty:
        return []
    total = float(df["active_s"].sum())
    groups: dict[object, list[float]] = {}
    for k, secs in zip(df[key], df["active_s"], strict=True):
        groups.setdefault(None if pd.isna(k) else k, []).append(secs)
    rows = [
        {
            "key": k,
            "focus_minutes": _minutes(sum(v)),
            "share": round(sum(v) / total, 3) if total else 0.0,
            "sessions": len(v),
        }
        for k, v in groups.items()
    ]
    return sorted(rows, key=lambda r: r["focus_minutes"], reverse=True)


def by_tag(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    exploded = df[["active_s", "tags"]].explode("tags")
    exploded["tags"] = exploded["tags"].fillna("(untagged)")
    total = df["active_s"].sum()
    rows = [
        {
            "tag": tag,
            "focus_minutes": _minutes(g["active_s"].sum()),
            "share": round(float(g["active_s"].sum() / total), 3) if total else 0.0,
            "sessions": len(g),
        }
        for tag, g in exploded.groupby("tags")
    ]
    return sorted(rows, key=lambda r: r["focus_minutes"], reverse=True)


def gaps(df: pd.DataFrame) -> dict:
    """Minutes between the end of one work session and the start of the next, same local day."""
    values: list[float] = []
    for _, day in df.sort_values("start").groupby("local_date"):
        ends, starts = list(day["end"]), list(day["start"])
        values += [max(0.0, (starts[i] - ends[i - 1]).total_seconds()) for i in range(1, len(day))]
    if not values:
        return {"avg_gap_minutes": None, "median_gap_minutes": None, "samples": 0}
    series = pd.Series(values)
    return {
        "avg_gap_minutes": _minutes(series.mean()),
        "median_gap_minutes": _minutes(series.median()),
        "samples": len(values),
    }
