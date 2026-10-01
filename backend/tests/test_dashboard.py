from datetime import UTC, datetime

from tests.conftest import ok


def test_today_dashboard(client, clock):
    ok(client.put("/api/settings", json={"timezone": "Europe/Berlin"}))
    clock.set(datetime(2026, 10, 1, 10, 0, tzinfo=UTC))  # 12:00 in Berlin
    a = ok(
        client.post(
            "/api/tasks",
            json={
                "title": "SQL assignment",
                "status": "planned",
                "estimated_minutes": 90,
                "deadline": "2026-10-01T20:00:00+02:00",
                "priority": "high",
            },
        ),
        201,
    )
    b = ok(
        client.post(
            "/api/tasks",
            json={
                "title": "German",
                "status": "planned",
                "estimated_minutes": 60,
                "planned_date": "2026-10-01",
            },
        ),
        201,
    )
    late = ok(
        client.post(
            "/api/tasks",
            json={"title": "Email professor", "status": "planned", "deadline": "2026-09-30T09:00:00Z"},
        ),
        201,
    )
    ok(
        client.post(
            "/api/tasks", json={"title": "Read paper", "status": "planned", "planned_date": "2026-10-05"}
        ),
        201,
    )
    ok(client.post("/api/tasks/inbox", json={"text": "Research master's programs"}), 201)
    ok(
        client.post(
            "/api/tasks",
            json={
                "title": "Daily review",
                "recurrence_rule": "FREQ=DAILY",
                "planned_date": "2026-09-01",
                "estimated_minutes": 15,
            },
        ),
        201,
    )
    # 30 minutes on SQL earlier today, then a live session on German
    ok(
        client.post(
            "/api/sessions",
            json={
                "start_time": "2026-10-01T08:00:00Z",
                "end_time": "2026-10-01T08:30:00Z",
                "task_id": a["id"],
            },
        ),
        201,
    )
    ok(client.post("/api/focus/start", json={"task_id": b["id"]}), 201)
    clock.advance(minutes=20)

    d = ok(client.get("/api/dashboard/today"))
    assert d["date"] == "2026-10-01" and d["timezone"] == "Europe/Berlin"
    assert d["focused_minutes"] == 50  # 30 finished + 20 live
    assert d["sessions_today"] == 1
    assert d["current_session"]["active_so_far_s"] == 1200
    # SQL 90-30 remaining + German 60-0 (live time not yet logged) + daily review 15
    assert d["planned_minutes"] == 60 + 60 + 15
    titles = [t["title"] for t in d["next_tasks"]]
    assert titles[0] == "Email professor"  # overdue first
    assert titles[1] == "German"  # in progress next
    assert "Read paper" not in titles
    assert [t["title"] for t in d["due_today"]] == ["SQL assignment"]
    assert [t["id"] for t in d["overdue"]] == [late["id"]]
    assert d["inbox_count"] == 1 and d["pending_approval_count"] == 0
    # recurrence occurrences were generated for today and the next 6 days
    occurrences = ok(client.get("/api/tasks?q=daily review"))
    assert len(occurrences) == 7
