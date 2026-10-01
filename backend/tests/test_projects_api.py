from tests.conftest import ok


def test_project_crud_and_unique_name(client):
    p = ok(client.post("/api/projects", json={"name": "Quant Research", "color": "#3366ff"}), 201)
    assert p["status"] == "active"
    dup = client.post("/api/projects", json={"name": "quant research"})
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "conflict"
    updated = ok(client.patch(f"/api/projects/{p['id']}", json={"status": "archived"}))
    assert updated["status"] == "archived"
    assert [x["name"] for x in ok(client.get("/api/projects?status=archived"))] == ["Quant Research"]


def test_project_with_history_cannot_be_deleted(client):
    p = ok(client.post("/api/projects", json={"name": "German"}), 201)
    ok(client.post("/api/tasks", json={"title": "Vocabulary", "project_id": p["id"]}), 201)
    r = client.delete(f"/api/projects/{p['id']}")
    assert r.status_code == 409
    empty = ok(client.post("/api/projects", json={"name": "Empty"}), 201)
    ok(client.delete(f"/api/projects/{empty['id']}"), 204)


def test_project_stats(client, clock):
    p = ok(client.post("/api/projects", json={"name": "Quant"}), 201)
    t1 = ok(
        client.post(
            "/api/tasks", json={"title": "Clean data", "project_id": p["id"], "estimated_minutes": 60}
        ),
        201,
    )
    ok(
        client.post(
            "/api/tasks", json={"title": "Backtest", "project_id": p["id"], "estimated_minutes": 120}
        ),
        201,
    )
    ok(client.post("/api/focus/start", json={"task_id": t1["id"]}), 201)
    clock.advance(minutes=45)
    ok(client.post("/api/focus/finish", json={"complete_task": True}))
    stats = ok(client.get(f"/api/projects/{p['id']}/stats"))
    assert stats["total_focus_minutes"] == 45
    assert stats["session_count"] == 1
    assert stats["tasks_completed"] == 1
    assert stats["tasks_remaining"] == 1
    assert stats["estimated_remaining_minutes"] == 120
