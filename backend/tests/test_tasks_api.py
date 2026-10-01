from tests.conftest import ok


def make(client, **fields):
    return ok(client.post("/api/tasks", json={"title": "Task", **fields}), 201)


def test_create_task_with_all_fields(client):
    t = make(
        client,
        title="Implement factor model",
        category="Programming",
        priority="high",
        status="planned",
        estimated_minutes=90,
        deadline="2026-10-03T18:00:00+02:00",
        earliest_start="2026-10-02T07:00:00Z",
        planned_date="2026-10-02",
        preferred_time="morning",
        energy_requirement="high",
        importance=5,
        urgency=3,
        tags=["python", "#Quant", "python"],
    )
    assert t["deadline"].startswith("2026-10-03T16:00:00")  # stored and returned as UTC
    assert t["tags"] == ["python", "Quant"]
    assert t["source"] == "user" and t["pending_approval"] is False
    assert t["is_template"] is False and t["blocked_by"] == []


def test_validation_errors(client):
    assert client.post("/api/tasks", json={"title": ""}).status_code == 422
    assert client.post("/api/tasks", json={"title": "x", "estimated_minutes": 0}).status_code == 422
    assert client.post("/api/tasks", json={"title": "x", "importance": 9}).status_code == 422
    naive = client.post("/api/tasks", json={"title": "x", "deadline": "2026-10-03T18:00:00"})
    assert naive.status_code == 422
    window = client.post(
        "/api/tasks",
        json={"title": "x", "earliest_start": "2026-10-05T00:00:00Z", "deadline": "2026-10-04T00:00:00Z"},
    )
    assert window.status_code == 422
    bad_rule = client.post("/api/tasks", json={"title": "x", "recurrence_rule": "EVERY DAY"})
    assert bad_rule.status_code == 422
    missing_project = client.post(
        "/api/tasks", json={"title": "x", "project_id": "00000000-0000-0000-0000-000000000000"}
    )
    assert missing_project.status_code == 422


def test_status_transitions_set_completed_at(client, clock):
    t = make(client, status="planned")
    done = ok(client.post(f"/api/tasks/{t['id']}/complete"))
    assert done["status"] == "completed"
    assert done["completed_at"].startswith("2026-10-01T08:00:00")
    reopened = ok(client.patch(f"/api/tasks/{t['id']}", json={"status": "planned"}))
    assert reopened["completed_at"] is None


def test_partial_update_and_null_guard(client):
    t = make(client, title="Read Hull", estimated_minutes=30)
    u = ok(client.patch(f"/api/tasks/{t['id']}", json={"estimated_minutes": 45, "description": "chapter 6"}))
    assert u["title"] == "Read Hull" and u["estimated_minutes"] == 45
    assert client.patch(f"/api/tasks/{t['id']}", json={"title": None}).status_code == 422


def test_inbox_capture_strips_bullets(client):
    text = "- Read Hull chapter 6\n* Finish SQL exercise\n\n1. German vocabulary\n[ ] Email professor\n"
    created = ok(client.post("/api/tasks/inbox", json={"text": text}), 201)
    assert [t["title"] for t in created] == [
        "Read Hull chapter 6",
        "Finish SQL exercise",
        "German vocabulary",
        "Email professor",
    ]
    assert all(t["status"] == "inbox" for t in created)


def test_list_filters(client):
    p = ok(client.post("/api/projects", json={"name": "Uni"}), 201)
    make(
        client,
        title="SQL assignment",
        project_id=p["id"],
        tags=["sql"],
        status="planned",
        planned_date="2026-10-01",
        deadline="2026-10-01T20:00:00Z",
    )
    make(client, title="German", category="Language", tags=["german"])
    assert len(ok(client.get("/api/tasks"))) == 2
    assert [t["title"] for t in ok(client.get(f"/api/tasks?project_id={p['id']}"))] == ["SQL assignment"]
    assert [t["title"] for t in ok(client.get("/api/tasks?tag=GERMAN"))] == ["German"]
    assert [t["title"] for t in ok(client.get("/api/tasks?q=sql"))] == ["SQL assignment"]
    assert [t["title"] for t in ok(client.get("/api/tasks?status=planned&status=blocked"))] == [
        "SQL assignment"
    ]
    assert [t["title"] for t in ok(client.get("/api/tasks?planned_date=2026-10-01"))] == ["SQL assignment"]
    assert ok(client.get("/api/tasks/categories")) == ["Language"]


def test_delete_task_keeps_session_snapshot(client, clock):
    t = make(client, title="Throwaway")
    ok(client.post("/api/focus/start", json={"task_id": t["id"]}), 201)
    clock.advance(minutes=10)
    s = ok(client.post("/api/focus/finish", json={}))
    ok(client.delete(f"/api/tasks/{t['id']}"), 204)
    session = ok(client.get(f"/api/sessions/{s['id']}"))
    assert session["task_id"] is None
    assert session["task_title_snapshot"] == "Throwaway"
    audit = ok(client.get(f"/api/audit?entity_type=task&entity_id={t['id']}"))
    assert audit[0]["action"] == "task.deleted" and audit[0]["before"]["title"] == "Throwaway"


def test_approve_pending_task(client, db, clock):
    from app.models.enums import ActionSource
    from app.schemas.task import TaskCreate
    from app.services import tasks

    task = tasks.create_task(
        db, TaskCreate(title="Clean market data"), clock.now, source=ActionSource.ai, pending_approval=True
    )
    listed = ok(client.get("/api/tasks?pending_approval=true"))
    assert [t["title"] for t in listed] == ["Clean market data"] and listed[0]["source"] == "ai"
    approved = ok(client.post(f"/api/tasks/{task.id}/approve"))
    assert approved["pending_approval"] is False
