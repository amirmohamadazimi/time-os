from tests.conftest import ok


def make(client, title, **fields):
    return ok(client.post("/api/tasks", json={"title": title, "status": "planned", **fields}), 201)


def test_strict_dependency_blocks_until_prerequisite_done(client):
    a = make(client, "A: clean data")
    b = make(client, "B: factor calcs", dependencies=[{"depends_on_id": a["id"]}])
    assert ok(client.get(f"/api/tasks/{b['id']}"))["blocked_by"] == [a["id"]]
    r = client.post("/api/focus/start", json={"task_id": b["id"]})
    assert r.status_code == 409 and "blocked" in r.json()["error"]["message"]
    ok(client.post(f"/api/tasks/{a['id']}/complete"))
    assert ok(client.get(f"/api/tasks/{b['id']}"))["blocked_by"] == []
    ok(client.post("/api/focus/start", json={"task_id": b["id"]}), 201)


def test_soft_dependency_does_not_block(client):
    a = make(client, "A")
    b = make(client, "B", dependencies=[{"depends_on_id": a["id"], "strict": False}])
    assert ok(client.get(f"/api/tasks/{b['id']}"))["blocked_by"] == []


def test_cancelled_prerequisite_unblocks(client):
    a = make(client, "A")
    b = make(client, "B", dependencies=[{"depends_on_id": a["id"]}])
    ok(client.patch(f"/api/tasks/{a['id']}", json={"status": "cancelled"}))
    assert ok(client.get(f"/api/tasks/{b['id']}"))["blocked_by"] == []


def test_cycles_and_self_dependencies_rejected(client):
    a = make(client, "A")
    b = make(client, "B", dependencies=[{"depends_on_id": a["id"]}])
    c = make(client, "C", dependencies=[{"depends_on_id": b["id"]}])
    r = client.patch(f"/api/tasks/{a['id']}", json={"dependencies": [{"depends_on_id": c["id"]}]})
    assert r.status_code == 422 and "cycle" in r.json()["error"]["message"]
    r = client.patch(f"/api/tasks/{a['id']}", json={"dependencies": [{"depends_on_id": a["id"]}]})
    assert r.status_code == 422


def test_dependencies_replace_and_missing(client):
    a = make(client, "A")
    b = make(client, "B")
    c = make(client, "C", dependencies=[{"depends_on_id": a["id"]}])
    updated = ok(client.patch(f"/api/tasks/{c['id']}", json={"dependencies": [{"depends_on_id": b["id"]}]}))
    assert [d["depends_on_id"] for d in updated["dependencies"]] == [b["id"]]
    r = client.patch(
        f"/api/tasks/{c['id']}",
        json={"dependencies": [{"depends_on_id": "00000000-0000-0000-0000-000000000001"}]},
    )
    assert r.status_code == 422
