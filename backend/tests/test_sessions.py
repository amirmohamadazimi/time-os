from tests.conftest import ok


def log(client, start, end, **fields):
    return client.post("/api/sessions", json={"start_time": start, "end_time": end, **fields})


def test_manual_session_and_validation(client):
    s = ok(
        log(client, "2026-09-30T09:00:00Z", "2026-09-30T10:00:00Z", paused_duration_s=600, tags=["quant"]),
        201,
    )
    assert s["source"] == "manual" and s["active_duration_s"] == 3000 and s["elapsed_s"] == 3600
    assert log(client, "2026-09-30T09:30:00Z", "2026-09-30T09:45:00Z").status_code == 409  # overlap
    assert log(client, "2026-09-30T12:00:00Z", "2026-09-30T11:00:00Z").status_code == 422
    assert log(client, "2026-10-01T09:00:00Z", "2026-10-01T10:00:00Z").status_code == 422  # future
    assert (
        log(client, "2026-09-30T12:00:00Z", "2026-09-30T12:10:00Z", paused_duration_s=600).status_code == 422
    )


def test_list_filters_and_paging(client):
    ok(log(client, "2026-09-28T09:00:00Z", "2026-09-28T10:00:00Z", tags=["quant"], notes="factor work"), 201)
    ok(log(client, "2026-09-29T09:00:00Z", "2026-09-29T09:30:00Z", type="rest"), 201)
    ok(log(client, "2026-09-30T09:00:00Z", "2026-09-30T09:50:00Z", tags=["german"]), 201)
    page = ok(client.get("/api/sessions?limit=2"))
    assert page["total"] == 3 and len(page["items"]) == 2
    assert page["items"][0]["start_time"].startswith("2026-09-30")  # newest first
    assert ok(client.get("/api/sessions?type=rest"))["total"] == 1
    assert ok(client.get("/api/sessions?tag=QUANT"))["total"] == 1
    assert ok(client.get("/api/sessions?q=factor"))["total"] == 1
    assert ok(client.get("/api/sessions?from=2026-09-29&to=2026-09-29"))["total"] == 1


def test_annotate_is_audited_and_times_immutable(client):
    s = ok(log(client, "2026-09-30T09:00:00Z", "2026-09-30T10:00:00Z"), 201)
    p = ok(client.post("/api/projects", json={"name": "Quant"}), 201)
    t = ok(client.post("/api/tasks", json={"title": "Backtest", "project_id": p["id"]}), 201)
    upd = ok(
        client.patch(
            f"/api/sessions/{s['id']}",
            json={
                "task_id": t["id"],
                "notes": "ran backtest",
                "exclude_from_stats": True,
                "start_time": "2020-01-01T00:00:00Z",
            },
        )
    )
    assert upd["task_title_snapshot"] == "Backtest" and upd["project_id"] == p["id"]
    assert upd["start_time"].startswith("2026-09-30T09:00")  # unknown/immutable fields ignored
    entry = ok(client.get(f"/api/audit?entity_id={s['id']}&action=session.annotated"))[0]
    assert entry["after"]["notes"] == "ran backtest" and entry["before"]["notes"] is None


def test_void_hides_session(client):
    s = ok(log(client, "2026-09-30T09:00:00Z", "2026-09-30T10:00:00Z"), 201)
    ok(client.delete(f"/api/sessions/{s['id']}"), 204)
    assert ok(client.get("/api/sessions"))["total"] == 0
    assert ok(client.get("/api/audit?action=session.voided"))[0]["entity_id"] == s["id"]
    assert client.patch(f"/api/sessions/{s['id']}", json={"notes": "x"}).status_code == 409
