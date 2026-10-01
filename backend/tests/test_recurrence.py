from datetime import date

import pytest

from app.errors import ValidationFailed
from app.services.recurrence import normalize_rule, occurrence_dates
from tests.conftest import ok


def test_rule_normalization():
    assert normalize_rule("rrule:freq=weekly;byday=mo,we") == "FREQ=WEEKLY;BYDAY=MO,WE"
    for bad in ("", "BYDAY=MO", "FREQ=SOMETIMES", "DTSTART:20260101\nRRULE:FREQ=DAILY"):
        with pytest.raises(ValidationFailed):
            normalize_rule(bad)


@pytest.mark.parametrize(
    "rule, expected",
    [
        ("FREQ=DAILY", [date(2026, 10, d) for d in range(1, 8)]),
        (
            "FREQ=WEEKLY;BYDAY=MO,WE,TH,SA",
            [date(2026, 10, 1), date(2026, 10, 3), date(2026, 10, 5), date(2026, 10, 7)],
        ),
        ("FREQ=WEEKLY;BYDAY=SU", [date(2026, 10, 4)]),
    ],
)
def test_occurrence_dates(rule, expected):
    assert occurrence_dates(rule, date(2026, 10, 1), date(2026, 10, 1), date(2026, 10, 7)) == expected


def test_monthly_uses_anchor_day():
    got = occurrence_dates("FREQ=MONTHLY", date(2026, 1, 15), date(2026, 10, 1), date(2026, 12, 31))
    assert got == [date(2026, 10, 15), date(2026, 11, 15), date(2026, 12, 15)]


def test_never_before_anchor():
    assert occurrence_dates("FREQ=DAILY", date(2026, 10, 5), date(2026, 10, 1), date(2026, 10, 6)) == [
        date(2026, 10, 5),
        date(2026, 10, 6),
    ]


def test_generate_occurrences_is_idempotent(client):
    template = ok(
        client.post(
            "/api/tasks",
            json={
                "title": "German",
                "estimated_minutes": 60,
                "category": "Language",
                "recurrence_rule": "FREQ=DAILY",
                "planned_date": "2026-10-01",
            },
        ),
        201,
    )
    assert template["is_template"] is True
    assert ok(client.get("/api/tasks")) == []  # templates hidden by default
    window = {"start_date": "2026-10-01", "end_date": "2026-10-03"}
    first = ok(client.post("/api/tasks/recurrences/generate", json=window))
    assert [t["occurrence_date"] for t in first] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert all(t["source"] == "recurrence" and t["status"] == "planned" for t in first)
    assert first[0]["estimated_minutes"] == 60 and first[0]["planned_date"] == "2026-10-01"
    assert ok(client.post("/api/tasks/recurrences/generate", json=window)) == []
    assert len(ok(client.get("/api/tasks"))) == 3


def test_template_cannot_be_worked_on_or_completed(client):
    template = ok(
        client.post("/api/tasks", json={"title": "Gym", "recurrence_rule": "FREQ=WEEKLY;BYDAY=MO"}), 201
    )
    assert client.post("/api/focus/start", json={"task_id": template["id"]}).status_code == 422
    assert client.post(f"/api/tasks/{template['id']}/complete").status_code == 422


def test_deleting_template_keeps_finished_occurrences(client):
    template = ok(
        client.post(
            "/api/tasks",
            json={"title": "Review", "recurrence_rule": "FREQ=DAILY", "planned_date": "2026-10-01"},
        ),
        201,
    )
    occ = ok(
        client.post(
            "/api/tasks/recurrences/generate", json={"start_date": "2026-10-01", "end_date": "2026-10-02"}
        )
    )
    ok(client.post(f"/api/tasks/{occ[0]['id']}/complete"))
    ok(client.delete(f"/api/tasks/{template['id']}"), 204)
    remaining = ok(client.get("/api/tasks"))
    assert [t["id"] for t in remaining] == [occ[0]["id"]]
    assert remaining[0]["recurrence_parent_id"] is None
