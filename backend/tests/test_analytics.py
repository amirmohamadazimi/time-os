from datetime import UTC, datetime

import pytest

from app.analytics.estimation import Observation, build_model, group, shrunk_multiplier
from app.analytics.metrics import _spread_over_hours, count_weekdays
from app.schemas.settings import Personalization
from tests.conftest import ok


def log(client, start, end, **fields):
    return ok(client.post("/api/sessions", json={"start_time": start, "end_time": end, **fields}), 201)


@pytest.fixture
def week(client, clock):
    """Mon 2026-09-21 .. Sun 2026-09-27 in Europe/Berlin (UTC+2)."""
    clock.set(datetime(2026, 10, 1, 12, tzinfo=UTC))
    ok(client.put("/api/settings", json={"timezone": "Europe/Berlin"}))
    p = ok(client.post("/api/projects", json={"name": "Quant"}), 201)
    t = ok(
        client.post(
            "/api/tasks", json={"title": "Factor model", "project_id": p["id"], "category": "Programming"}
        ),
        201,
    )
    # Monday: 09:00-10:00 local (completed, 10 min paused), 14:00-14:30 (stopped)
    log(
        client,
        "2026-09-21T07:00:00Z",
        "2026-09-21T08:00:00Z",
        paused_duration_s=600,
        task_id=t["id"],
        tags=["python"],
    )
    log(
        client, "2026-09-21T12:00:00Z", "2026-09-21T12:30:00Z", end_reason="stopped", tags=["python", "quant"]
    )
    # Monday break
    log(client, "2026-09-21T08:00:00Z", "2026-09-21T08:15:00Z", type="rest")
    # Wednesday: 09:30-10:30 local, completed
    log(client, "2026-09-23T07:30:00Z", "2026-09-23T08:30:00Z", task_id=t["id"])
    # Wednesday: switched session (ignored for completion rate)
    log(client, "2026-09-23T09:00:00Z", "2026-09-23T09:20:00Z", end_reason="switched")
    return {"project": p, "task": t}


def test_summary(client, week):
    s = ok(client.get("/api/analytics/summary?from=2026-09-21&to=2026-09-27"))
    assert s["meta"]["kind"] == "observed" and s["meta"]["from"] == "2026-09-21"
    assert s["session_count"] == 4 and s["rest_session_count"] == 1
    assert s["total_focus_minutes"] == 50 + 30 + 60 + 20
    assert s["total_rest_minutes"] == 15
    assert s["active_days"] == 2 and s["avg_daily_focus_minutes"] == 80
    assert s["avg_session_minutes"] == 40 and s["median_session_minutes"] == 40
    assert s["longest_session_minutes"] == 60
    assert (s["completed_sessions"], s["stopped_sessions"], s["switched_sessions"]) == (2, 1, 1)
    assert s["completion_rate"] == pytest.approx(2 / 3, abs=0.001)
    assert s["interrupted_sessions"] == 1 and s["interruption_rate"] == 0.25


def test_excluded_sessions_are_reported_not_counted(client, week):
    sessions = ok(client.get("/api/sessions?type=work&limit=10"))["items"]
    longest = max(sessions, key=lambda x: x["active_duration_s"])
    ok(client.patch(f"/api/sessions/{longest['id']}", json={"exclude_from_stats": True}))
    s = ok(client.get("/api/analytics/summary"))
    assert s["session_count"] == 3 and s["meta"]["excluded_count"] == 1


def test_timeseries_fills_empty_periods(client, week):
    day = ok(client.get("/api/analytics/timeseries?from=2026-09-21&to=2026-09-27&granularity=day"))
    assert [p["focus_minutes"] for p in day["items"]] == [80, 0, 80, 0, 0, 0, 0]
    wk = ok(client.get("/api/analytics/timeseries?from=2026-09-14&to=2026-09-27&granularity=week"))
    assert [(p["period"], p["focus_minutes"]) for p in wk["items"]] == [
        ("2026-09-14", 0),
        ("2026-09-21", 160),
    ]
    month = ok(client.get("/api/analytics/timeseries?granularity=month"))
    assert [(p["period"], p["sessions"]) for p in month["items"]] == [("2026-09-01", 4)]


def test_by_hour_uses_local_time_and_spreads_across_hours(client, week):
    rows = {r["hour"]: r for r in ok(client.get("/api/analytics/by-hour"))["items"]}
    assert rows[9]["sessions_started"] == 2  # 09:00 and 09:30 local (UTC+2), not 07/08 UTC
    assert rows[9]["focus_minutes"] == pytest.approx(50 + 30)  # 09:30-10:30 splits 30/30
    assert rows[10]["focus_minutes"] == pytest.approx(30)
    assert rows[14]["completion_rate"] == 0.0 and rows[9]["completion_rate"] == 1.0
    assert rows[7]["focus_minutes"] == 0


def test_spread_scales_by_active_ratio():
    start = datetime(2026, 9, 21, 9, 30)
    spread = _spread_over_hours(start, 3600, 1800)  # half the time paused
    assert spread == {9: 900.0, 10: 900.0}


def test_by_weekday(client, week):
    rows = ok(client.get("/api/analytics/by-weekday?from=2026-09-14&to=2026-09-27"))["items"]
    mon, wed = rows[0], rows[2]
    assert mon["focus_minutes"] == 80 and mon["days_in_range"] == 2 and mon["avg_daily_focus_minutes"] == 40
    assert wed["sessions"] == 2 and rows[6]["focus_minutes"] == 0
    assert count_weekdays(datetime(2026, 9, 21).date(), datetime(2026, 9, 30).date()) == [2, 2, 2, 1, 1, 1, 1]


def test_by_project_and_tag_and_gaps(client, week):
    proj = ok(client.get("/api/analytics/by-project"))["items"]
    assert proj[0]["project_name"] == "Quant" and proj[0]["focus_minutes"] == 110
    assert proj[1]["project_name"] == "(no project)" and proj[0]["share"] == pytest.approx(
        110 / 160, abs=0.001
    )
    tags = {r["tag"]: r for r in ok(client.get("/api/analytics/by-tag"))["items"]}
    assert tags["python"]["focus_minutes"] == 80 and tags["quant"]["sessions"] == 1
    assert tags["(untagged)"]["sessions"] == 2
    g = ok(client.get("/api/analytics/gaps"))
    assert g["samples"] == 2 and g["avg_gap_minutes"] == pytest.approx((240 + 30) / 2)


def test_filters_by_project_tag_and_type(client, week):
    pid = week["project"]["id"]
    assert ok(client.get(f"/api/analytics/summary?project_id={pid}"))["session_count"] == 2
    assert ok(client.get("/api/analytics/summary?tag=quant"))["session_count"] == 1
    rest = ok(client.get("/api/analytics/by-hour?type=rest"))
    assert rest["meta"]["type"] == "rest" and rest["meta"]["session_count"] == 1


def test_patterns_are_observed_and_need_samples(client, week):
    assert ok(client.get("/api/analytics/patterns"))["items"] == []  # 4 sessions < min_samples (5)
    ok(client.put("/api/settings", json={"personalization": {"min_samples": 2}}))
    items = {p["id"]: p for p in ok(client.get("/api/analytics/patterns"))["items"]}
    assert all(p["kind"] == "observed" for p in items.values())
    assert items["peak_window"]["values"]["start_hour"] in (8, 9)
    assert "pause" in items["interruptions"]["statement"]


P = Personalization(min_samples=5, strong_samples=20, prior_strength=10)


def obs(category, est, act):
    import uuid

    return Observation(uuid.uuid4(), "t", category, None, None, est, act)


def test_shrinkage_respects_sample_thresholds():
    import math

    assert shrunk_multiplier([math.log(1.5)] * 4, P) == (1.0, 0.0)  # below min_samples: no adjustment
    m5, w5 = shrunk_multiplier([math.log(1.5)] * 5, P)
    m20, w20 = shrunk_multiplier([math.log(1.5)] * 20, P)
    assert w5 == pytest.approx(5 / 15, abs=0.01) and w20 == pytest.approx(20 / 30, abs=0.01)
    assert 1.0 < m5 < m20 < 1.5
    capped, _ = shrunk_multiplier([math.log(10)] * 500, P)
    assert capped == 3.0


def test_group_estimates():
    data = [obs("Programming", 60, 87)] * 6 + [obs("Language", 60, 60)] * 2
    rows = {r["group"]: r for r in group(data, "category", P)}
    prog = rows["Programming"]
    assert prog["ratio"] == 1.45 and prog["avg_actual_minutes"] == 87 and prog["tendency"] == "underestimate"
    assert prog["confidence"] == "moderate" and 1.0 < prog["multiplier"] < 1.45
    assert rows["Language"]["confidence"] == "insufficient" and rows["Language"]["multiplier"] == 1.0
    model = build_model(data, P)
    assert model.multiplier("Programming", None) == prog["multiplier"]
    assert model.multiplier("Language", None) == model.overall
    assert model.effective_estimate(60, "Programming", None) == round(60 * prog["multiplier"])


def test_estimation_endpoint(client, clock):
    for i in range(5):
        t = ok(
            client.post(
                "/api/tasks",
                json={
                    "title": f"t{i}",
                    "category": "Programming",
                    "estimated_minutes": 60,
                    "status": "planned",
                },
            ),
            201,
        )
        ok(client.post("/api/focus/start", json={"task_id": t["id"]}), 201)
        clock.advance(minutes=90)
        ok(client.post("/api/focus/finish", json={"complete_task": True}))
        clock.advance(minutes=5)
    rows = ok(client.get("/api/analytics/estimation"))["items"]
    assert rows[0]["group"] == "Programming" and rows[0]["samples"] == 5 and rows[0]["ratio"] == 1.5
    s = ok(client.get("/api/analytics/summary"))
    assert s["planned_vs_actual"] == {"tasks": 5, "estimated_minutes": 300, "actual_minutes": 450}
