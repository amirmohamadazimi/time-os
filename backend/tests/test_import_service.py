from pathlib import Path

import pytest

from tests.conftest import ok

FIXTURE = Path(__file__).parent / "fixtures" / "focus_messy.csv"
# Synthetic file in FocusMeter's multi-section export format (no real user data).
FOCUSMETER = Path(__file__).parent / "fixtures" / "focusmeter_export.csv"


def upload(client, data: bytes, **params):
    params.setdefault("default_timezone", "Europe/Berlin")
    return client.post(
        "/api/imports/focus-sessions", params=params, files={"file": ("export.csv", data, "text/csv")}
    )


def issues_by_row(report):
    return {i["row_number"]: i for i in report["issues"]}


def test_dry_run_summary_on_messy_file(client):
    report = ok(upload(client, FIXTURE.read_bytes()))
    s = report["summary"]
    assert report["dry_run"] is True and report["batch_id"] is None
    assert (s["rows_read"], s["valid"], s["duplicates"], s["invalid"]) == (15, 9, 2, 4)
    assert s["duration_unit"] == "seconds (inferred from timestamps)"
    assert s["duration_meaning"] == "actual" and s["sections"] == []
    assert s["work_sessions"] == 8 and s["rest_sessions"] == 1
    assert s["excluded_from_stats"] == 1 and s["flagged"] == 2
    assert s["total_focus_hours"] == pytest.approx(15030 / 3600, abs=0.01)
    assert s["errors_by_code"] == {
        "invalid_start_time": 1,
        "end_before_start": 1,
        "unknown_type": 1,
        "malformed_row": 1,
    }
    assert s["assumed_timezone_rows"] == 2  # naive timestamp + epoch
    assert ok(client.get("/api/sessions"))["total"] == 0  # nothing written

    rows = issues_by_row(report)
    assert rows[5]["status"] == "duplicate" and "same id" in rows[5]["warnings"][0]
    assert rows[16]["status"] == "duplicate" and "same start" in rows[16]["warnings"][0]
    assert rows[7]["status"] == "invalid" and rows[7]["raw"]["startTime"] == "not-a-date"
    assert rows[12]["errors"][0].startswith("malformed_row")
    assert any(w.startswith("implausible_elapsed") for w in rows[10]["warnings"])
    assert any(w.startswith("long_pause") for w in rows[13]["warnings"])
    assert any(w.startswith("type_missing") for w in rows[9]["warnings"])


def test_commit_creates_sessions_and_preserves_raw_rows(client):
    report = ok(upload(client, FIXTURE.read_bytes(), dry_run="false"))
    batch_id = report["batch_id"]
    sessions = ok(client.get("/api/sessions?limit=50"))["items"]
    assert len(sessions) == 9
    by_ext = {s["external_id"]: s for s in sessions}
    s1 = by_ext["s1"]
    assert s1["source"] == "import" and s1["tz_offset_minutes"] == 120
    assert s1["start_time"].startswith("2026-09-01T07:00:00")
    assert (s1["active_duration_s"], s1["paused_duration_s"], s1["elapsed_s"]) == (1500, 300, 1800)
    assert s1["completed"] is True and s1["tags"] == ["python", "quant"]
    assert by_ext["s3"]["stopped"] is True and by_ext["s3"]["notes"] == "Notes, with comma"
    assert by_ext["s2"]["type"] == "rest"
    assert by_ext["s5"]["start_time"].startswith("2026-09-02T06:00:00")  # naive Berlin time
    assert by_ext["s5"]["end_time"].startswith("2026-09-02T07:00:00")
    assert by_ext["s8"]["end_reason"] == "unknown"
    assert by_ext["s9"]["exclude_from_stats"] is True
    assert set(by_ext["s9"]["quality_flags"]) == {"long_active", "implausible_elapsed"}

    records = ok(client.get(f"/api/imports/{batch_id}/records?limit=100"))
    assert records["total"] == 15  # every input row preserved, including invalid ones
    invalid = ok(client.get(f"/api/imports/{batch_id}/records?status=invalid"))
    assert {r["raw"]["id"] for r in invalid["items"]} == {"s6", "s7", "s10", "s11"}
    assert ok(client.get("/api/audit?action=import.committed"))[0]["entity_id"] == batch_id


def test_reimport_is_idempotent_and_rollback_allows_again(client):
    first = ok(upload(client, FIXTURE.read_bytes(), dry_run="false"))
    again = ok(upload(client, FIXTURE.read_bytes(), dry_run="false"))
    assert again["summary"]["valid"] == 0 and again["summary"]["duplicates"] == 11
    assert again["summary"]["file_previously_imported"] is True
    assert ok(client.get("/api/sessions"))["total"] == 9

    rolled = ok(client.delete(f"/api/imports/{first['batch_id']}"))
    assert rolled["rolled_back_at"] is not None
    assert ok(client.get("/api/sessions"))["total"] == 0
    assert client.delete(f"/api/imports/{first['batch_id']}").status_code == 409
    third = ok(upload(client, FIXTURE.read_bytes(), dry_run="false"))
    assert third["summary"]["valid"] == 9


def test_duplicates_against_timer_sessions(client, clock):
    from datetime import UTC, datetime

    clock.set(datetime(2026, 9, 1, 7, 0, tzinfo=UTC))
    ok(client.post("/api/focus/start", json={}), 201)
    clock.advance(minutes=30)
    ok(client.post("/api/focus/finish", json={}))
    data = b"startTime,endTime\n2026-09-01T09:00:20+02:00,2026-09-01T09:30:10+02:00\n"
    report = ok(upload(client, data))
    assert report["summary"]["duplicates"] == 1


def test_deleted_imported_session_is_not_resurrected(client):
    ok(upload(client, FIXTURE.read_bytes(), dry_run="false"))
    s1 = next(s for s in ok(client.get("/api/sessions?limit=50"))["items"] if s["external_id"] == "s1")
    ok(client.delete(f"/api/sessions/{s1['id']}"), 204)
    report = ok(upload(client, FIXTURE.read_bytes(), dry_run="false"))
    assert report["summary"]["valid"] == 0


def test_bad_files_rejected(client):
    r = upload(client, b"id,notes\n1,hello\n")
    assert r.status_code == 422 and r.json()["error"]["details"]["errors"]
    assert upload(client, b"   ").status_code == 422
    assert upload(client, FIXTURE.read_bytes(), default_timezone="Not/AZone").status_code == 422


def test_focusmeter_multi_section_export(client):
    report = ok(upload(client, FOCUSMETER.read_bytes(), default_timezone="Asia/Tehran"))
    s = report["summary"]
    assert (s["rows_read"], s["valid"], s["duplicates"], s["invalid"]) == (11, 10, 0, 1)
    assert {"sessions", "timeblocks", "events"} <= set(s["sections"])
    # completed sessions match the duration column, stopped ones fall short: it is the planned target
    assert s["duration_meaning"] == "planned"
    assert "duration_mismatch" not in s["warnings_by_code"]
    assert s["errors_by_code"] == {"unfinished_session": 1}  # epoch end time: still running at export
    assert (s["work_sessions"], s["rest_sessions"]) == (7, 3)
    assert (s["flagged"], s["excluded_from_stats"]) == (4, 2)
    assert s["total_focus_hours"] == pytest.approx(13624 / 3600, abs=0.01)

    ok(upload(client, FOCUSMETER.read_bytes(), default_timezone="Asia/Tehran", dry_run="false"))
    by_ext = {x["external_id"]: x for x in ok(client.get("/api/sessions?limit=50"))["items"]}
    assert set(by_ext) == {str(i) for i in range(1, 11)}

    paused = by_ext["3"]
    assert (paused["planned_duration_s"], paused["active_duration_s"], paused["pause_count"]) == (
        1500,
        1500,
        1,
    )
    assert paused["tz_offset_minutes"] == 210 and paused["tags"] == ["Study"]

    stopped = by_ext["4"]
    assert (stopped["planned_duration_s"], stopped["active_duration_s"], stopped["end_reason"]) == (
        3600,
        720,
        "stopped",
    )

    # The timer finished and sat idle for over two hours before being stopped: the app's timer
    # blocks (1500 s + 3 s) are the active time, not end - start.
    idle = by_ext["7"]
    assert (idle["active_duration_s"], idle["paused_duration_s"], idle["pause_count"]) == (1503, 7497, 1)

    # Paused overnight: a long elapsed time explained by pauses keeps its real focus time in the stats.
    overnight = by_ext["8"]
    assert set(overnight["quality_flags"]) == {"long_pause", "implausible_elapsed"}
    assert overnight["exclude_from_stats"] is False and overnight["active_duration_s"] == 3600

    # Accidental taps seconds apart: separate sessions (they do not overlap), flagged and excluded.
    for tap in ("5", "6"):
        assert by_ext[tap]["quality_flags"] == ["too_short"] and by_ext[tap]["exclude_from_stats"] is True

    summary = ok(client.get("/api/analytics/summary"))
    assert summary["session_count"] == 7 and summary["meta"]["excluded_count"] == 0


def test_short_session_threshold_is_a_setting(client):
    ok(client.put("/api/settings", json={"import_rules": {"short_session_seconds": 0}}))
    report = ok(upload(client, FOCUSMETER.read_bytes(), default_timezone="Asia/Tehran"))
    assert report["summary"]["excluded_from_stats"] == 0
