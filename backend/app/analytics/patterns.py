"""Deterministic, observed findings. Every statement is computed from data and labelled
``observed``; interpretation ("why") is left to the AI layer and labelled separately."""

import pandas as pd

from app.analytics.metrics import WEEKDAYS, by_hour, by_weekday, completion_rate, interrupted_mask

DAYPARTS = [("morning", 5, 12), ("afternoon", 12, 17), ("evening", 17, 22), ("night", 22, 29)]


def _daypart(hour: int) -> str:
    h = hour if hour >= 5 else hour + 24
    return next(name for name, lo, hi in DAYPARTS if lo <= h < hi)


def _fmt_minutes(m: float) -> str:
    h, mm = divmod(int(round(m)), 60)
    return f"{h}h {mm:02d}m" if h else f"{mm}m"


def find_patterns(df: pd.DataFrame, min_samples: int, date_from=None, date_to=None) -> list[dict]:
    out: list[dict] = []
    if len(df) < min_samples:
        return out
    total_min = df["active_s"].sum() / 60

    hours = by_hour(df)
    minutes = [h["focus_minutes"] for h in hours]
    best_start = max(range(24), key=lambda s: sum(minutes[(s + i) % 24] for i in range(3)))
    share = sum(minutes[(best_start + i) % 24] for i in range(3)) / total_min if total_min else 0
    out.append({
        "id": "peak_window",
        "kind": "observed",
        "statement": f"{share:.0%} of your focused time falls between {best_start:02d}:00 and "
                     f"{(best_start + 3) % 24:02d}:00.",
        "values": {"start_hour": best_start, "end_hour": (best_start + 3) % 24, "share": round(share, 3)},
        "sample_size": len(df),
    })  # fmt: skip

    parts = df.assign(daypart=df["hour"].map(_daypart)).groupby("daypart")
    stats = {
        name: {"n": len(g), "avg": g["active_s"].mean() / 60, "completion": completion_rate(g)}
        for name, g in parts
        if len(g) >= min_samples
    }
    if len(stats) >= 2:
        best = max(stats, key=lambda k: stats[k]["avg"])
        worst = min(stats, key=lambda k: stats[k]["avg"])
        if stats[best]["avg"] >= 1.2 * stats[worst]["avg"]:
            best_avg, worst_avg = _fmt_minutes(stats[best]["avg"]), _fmt_minutes(stats[worst]["avg"])
            out.append({
                "id": "session_length_by_daypart",
                "kind": "observed",
                "statement": f"Your work sessions starting in the {best} average {best_avg}, "
                             f"versus {worst_avg} in the {worst}.",
                "values": {k: round(v["avg"], 1) for k, v in stats.items()},
                "sample_size": stats[best]["n"] + stats[worst]["n"],
            })  # fmt: skip
        rated = {k: v for k, v in stats.items() if v["completion"] is not None}
        if len(rated) >= 2:
            hi = max(rated, key=lambda k: rated[k]["completion"])
            lo = min(rated, key=lambda k: rated[k]["completion"])
            if rated[hi]["completion"] - rated[lo]["completion"] >= 0.10:
                hi_rate, lo_rate = rated[hi]["completion"], rated[lo]["completion"]
                out.append({
                    "id": "completion_by_daypart",
                    "kind": "observed",
                    "statement": f"You complete {hi_rate:.0%} of sessions started in the {hi}, "
                                 f"versus {lo_rate:.0%} in the {lo}.",
                    "values": {k: v["completion"] for k, v in rated.items()},
                    "sample_size": rated[hi]["n"] + rated[lo]["n"],
                })  # fmt: skip

    weekdays = [w for w in by_weekday(df, date_from, date_to) if w["days_in_range"] >= 2 and w["sessions"]]
    if len(weekdays) >= 2:
        top = max(weekdays, key=lambda w: w["avg_daily_focus_minutes"])
        low = min(weekdays, key=lambda w: w["avg_daily_focus_minutes"])
        if top["weekday"] != low["weekday"]:
            out.append({
                "id": "weekday_focus",
                "kind": "observed",
                "statement": f"You focus most on {WEEKDAYS[top['weekday']]}s "
                             f"({_fmt_minutes(top['avg_daily_focus_minutes'])} on average) and least on "
                             f"{WEEKDAYS[low['weekday']]}s ({_fmt_minutes(low['avg_daily_focus_minutes'])}).",
                "values": {w["name"]: w["avg_daily_focus_minutes"] for w in weekdays},
                "sample_size": len(df),
            })  # fmt: skip

    rate = float(interrupted_mask(df).mean())
    out.append({
        "id": "interruptions",
        "kind": "observed",
        "statement": f"{rate:.0%} of your work sessions included at least one pause.",
        "values": {"interruption_rate": round(rate, 3)},
        "sample_size": len(df),
    })  # fmt: skip
    return out
