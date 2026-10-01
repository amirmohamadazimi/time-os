from datetime import UTC, datetime

from tests.conftest import ok


def task(client, **fields):
    return ok(
        client.post("/api/tasks", json={"title": "Implement factor model", "status": "planned", **fields}),
        201,
    )


def test_start_pause_resume_finish_durations(client, clock):
    t = task(client, tags=["quant"])
    live = ok(
        client.post(
            "/api/focus/start", json={"task_id": t["id"], "planned_duration_s": 1500, "tags": ["python"]}
        ),
        201,
    )
    assert live["state"] == "running" and live["active_so_far_s"] == 0
    assert live["task_title_snapshot"] == "Implement factor model"
    assert ok(client.get(f"/api/tasks/{t['id']}"))["status"] == "in_progress"

    clock.advance(minutes=10)
    paused = ok(client.post("/api/focus/pause"))
    assert paused["state"] == "paused" and paused["pause_count"] == 1
    clock.advance(minutes=3)
    assert ok(client.get("/api/focus/current"))["active_so_far_s"] == 600  # pauses don't count
    resumed = ok(client.post("/api/focus/resume"))
    assert resumed["paused_duration_s"] == 180
    clock.advance(minutes=15)
    ok(client.post("/api/focus/pause"))
    clock.advance(minutes=2)
    done = ok(
        client.post(
            "/api/focus/finish",
            json={"end_reason": "completed", "outcome": "partial", "notes": "factor loadings done"},
        )
    )
    # finishing while paused folds the open pause into paused_duration
    assert done["state"] == "finished"
    assert done["elapsed_s"] == 30 * 60
    assert done["paused_duration_s"] == 5 * 60
    assert done["active_duration_s"] == 25 * 60
    assert done["pause_count"] == 2
    assert done["completed"] is True and done["stopped"] is False
    assert done["outcome"] == "partial" and done["notes"] == "factor loadings done"
    assert done["tags"] == ["python"]
    assert ok(client.get("/api/focus/current")) is None


def test_invalid_transitions(client, clock):
    assert client.post("/api/focus/pause").status_code == 409
    assert client.post("/api/focus/finish", json={}).status_code == 409
    ok(client.post("/api/focus/start", json={}), 201)
    assert client.post("/api/focus/start", json={}).status_code == 409
    assert client.post("/api/focus/resume").status_code == 409
    ok(client.post("/api/focus/pause"))
    assert client.post("/api/focus/pause").status_code == 409


def test_stop_and_complete_task(client, clock):
    t = task(client)
    ok(client.post("/api/focus/start", json={"task_id": t["id"]}), 201)
    clock.advance(minutes=20)
    s = ok(client.post("/api/focus/finish", json={"end_reason": "stopped", "complete_task": True}))
    assert s["stopped"] is True and s["active_duration_s"] == 1200
    assert ok(client.get(f"/api/tasks/{t['id']}"))["status"] == "completed"


def test_blocked_outcome_marks_task_blocked(client, clock):
    t = task(client)
    ok(client.post("/api/focus/start", json={"task_id": t["id"]}), 201)
    clock.advance(minutes=5)
    ok(client.post("/api/focus/finish", json={"end_reason": "stopped", "outcome": "blocked"}))
    assert ok(client.get(f"/api/tasks/{t['id']}"))["status"] == "blocked"


def test_rest_session_and_skip(client, clock):
    t = task(client)
    r = client.post("/api/focus/start", json={"type": "rest", "task_id": t["id"]})
    assert r.status_code == 422
    ok(client.post("/api/focus/start", json={"type": "rest", "planned_duration_s": 600}), 201)
    clock.advance(seconds=30)
    s = ok(client.post("/api/focus/finish", json={"end_reason": "skipped"}))
    assert s["type"] == "rest" and s["end_reason"] == "skipped" and s["active_duration_s"] == 30


def test_switch_task(client, clock):
    a = task(client, title="Python")
    b = task(client, title="German")
    first = ok(client.post("/api/focus/start", json={"task_id": a["id"]}), 201)
    clock.advance(minutes=40)
    second = ok(client.post("/api/focus/switch", json={"task_id": b["id"]}))
    assert second["task_id"] == b["id"] and second["state"] == "running"
    old = ok(client.get(f"/api/sessions/{first['id']}"))
    assert old["end_reason"] == "switched" and old["active_duration_s"] == 2400
    assert client.post("/api/focus/switch", json={"task_id": b["id"]}).status_code == 409


def test_switch_to_unworkable_task_changes_nothing(client, clock):
    a = task(client, title="A")
    done = task(client, title="Done")
    ok(client.post(f"/api/tasks/{done['id']}/complete"))
    live = ok(client.post("/api/focus/start", json={"task_id": a["id"]}), 201)
    assert client.post("/api/focus/switch", json={"task_id": done["id"]}).status_code == 409
    assert ok(client.get("/api/focus/current"))["id"] == live["id"]


def test_discard_and_annotate(client, clock):
    ok(client.post("/api/focus/start", json={}), 201)
    annotated = ok(client.patch("/api/focus/current", json={"notes": "warm-up", "tags": ["#deep"]}))
    assert annotated["notes"] == "warm-up" and annotated["tags"] == ["deep"]
    ok(client.delete("/api/focus/current"), 204)
    assert ok(client.get("/api/focus/current")) is None
    assert ok(client.get("/api/audit?action=focus.discarded"))[0]["entity_type"] == "focus_session"


def test_completed_task_cannot_be_started(client):
    t = task(client)
    ok(client.post(f"/api/tasks/{t['id']}/complete"))
    assert client.post("/api/focus/start", json={"task_id": t["id"]}).status_code == 409


def test_timezone_offset_recorded(client, clock):
    ok(client.put("/api/settings", json={"timezone": "Europe/Berlin"}))
    clock.set(datetime(2026, 10, 1, 7, 0, tzinfo=UTC))  # CEST, UTC+2
    s = ok(client.post("/api/focus/start", json={}), 201)
    assert s["tz_offset_minutes"] == 120
    clock.advance(minutes=1)
    ok(client.post("/api/focus/finish", json={}))
    clock.set(datetime(2026, 11, 2, 7, 0, tzinfo=UTC))  # CET, UTC+1 after DST ends
    s = ok(client.post("/api/focus/start", json={}), 201)
    assert s["tz_offset_minutes"] == 60


def test_clock_skew_never_negative(client, clock):
    ok(client.post("/api/focus/start", json={}), 201)
    clock.advance(seconds=-30)
    s = ok(client.post("/api/focus/finish", json={}))
    assert s["active_duration_s"] == 0 and s["exclude_from_stats"] is True
