"""The Claude tool layer, exercised with scripted tool calls (no live model)."""

import json

import pytest

from app.ai.tools import REGISTRY, ToolContext, definitions, execute_tool
from app.services.settings import get_settings, update_settings


@pytest.fixture
def ctx(db, clock):
    def make(confirmed: bool = False) -> ToolContext:
        return ToolContext(db=db, now=clock.now, settings=get_settings(db), confirmed=confirmed)

    return make


def call(ctx, name, **args):
    return execute_tool(ctx(), name, args)


def test_definitions_are_valid_anthropic_tools():
    defs = definitions()
    assert {d["name"] for d in defs} == set(REGISTRY)
    for d in defs:
        assert set(d) == {"name", "description", "input_schema"}
        assert d["input_schema"]["type"] == "object"
        assert "$defs" not in json.dumps(d["input_schema"]) and "$ref" not in json.dumps(d["input_schema"])


def test_unknown_tool_and_invalid_input_are_error_results(ctx):
    r = call(ctx, "drop_database")
    assert r.is_error and "unknown tool" in r.content["error"]
    r = call(ctx, "create_task", title="")
    assert r.status == "error" and r.content["error"] == "invalid input"
    r = call(ctx, "create_task", title="x", estimated_minutes=-5, sneaky_field=1)
    assert {e["type"] for e in r.content["details"]} >= {"greater_than", "extra_forbidden"}


def test_ai_created_tasks_need_approval_and_are_audited(ctx, db):
    r = call(ctx, "create_task", title="Clean market data", estimated_minutes=60, reason="from your goal")
    assert r.status == "ok"
    task = r.content["task"]
    assert task["source"] == "ai" and task["pending_approval"] is True
    from app.services import audit

    entry = audit.list_entries(db, entity_id=task["id"])[0]
    assert entry.source.value == "ai" and entry.reason == "from your goal"
    update_settings(db, {"require_approval_for_ai_tasks": False})
    r = call(ctx, "create_task", title="Run backtest")
    assert r.content["task"]["pending_approval"] is False


def test_propose_tasks_decomposition_with_sequence(ctx):
    r = call(
        ctx,
        "propose_tasks",
        goal="Finish quant research project",
        sequential=True,
        tasks=[
            {"title": "Clean market data", "estimated_minutes": 60},
            {"title": "Implement factor calculations", "estimated_minutes": 90},
            {"title": "Run backtest", "estimated_minutes": 120},
        ],
    )
    created = r.content["tasks"]
    assert [t["title"] for t in created] == [
        "Clean market data",
        "Implement factor calculations",
        "Run backtest",
    ]
    assert all(t["pending_approval"] for t in created)
    assert created[1]["blocked_by"] == [created[0]["id"]]


def test_ai_actions_go_through_domain_validation(ctx):
    a = call(ctx, "create_task", title="A").content["task"]
    b = call(ctx, "create_task", title="B").content["task"]
    r = call(ctx, "update_task", task_id=b["id"], deadline="2026-10-01T10:00:00Z")
    assert r.status == "ok"
    r = call(ctx, "update_task", task_id=a["id"], project_id="00000000-0000-0000-0000-000000000000")
    assert r.status == "error" and r.content["error"] == "validation_error"
    r = call(ctx, "start_focus_session", task_id=a["id"])
    assert r.status == "error" and "approval" in r.content["message"]  # pending proposals can't be worked on


def test_delete_requires_confirmation(ctx, db):
    t = call(ctx, "create_task", title="Obsolete").content["task"]
    r = call(ctx, "delete_task", task_id=t["id"], reason="user said it's no longer needed")
    assert r.status == "confirmation_required"
    assert call(ctx, "search_tasks", query="obsolete").content["tasks"]  # still there
    r = execute_tool(ctx(confirmed=True), "delete_task", {"task_id": t["id"], "reason": "confirmed"})
    assert r.status == "ok"
    assert call(ctx, "search_tasks", query="obsolete").content["tasks"] == []


def test_focus_session_tools(ctx, db, clock):
    from app.schemas.task import TaskCreate
    from app.services import tasks

    task = tasks.create_task(db, TaskCreate(title="German", status="planned"), clock.now)
    r = call(ctx, "start_focus_session", task_id=str(task.id), planned_minutes=25)
    assert r.status == "ok" and r.content["session"]["state"] == "running"
    clock.advance(minutes=25)
    assert call(ctx, "get_current_focus_session").content["session"]["active_minutes"] == 25
    r = call(ctx, "stop_focus_session", outcome="completed", complete_task=True)
    assert r.content["session"]["end_reason"] == "completed"
    assert call(ctx, "search_tasks", query="german").content["tasks"][0]["status"] == "completed"
    found = call(ctx, "search_sessions", task_id=str(task.id)).content
    assert found["total"] == 1 and found["sessions"][0]["active_minutes"] == 25


def test_stats_tools_return_observed_metrics(ctx, db, clock):
    call(ctx, "start_focus_session")
    clock.advance(minutes=30)
    call(ctx, "stop_focus_session")
    r = call(ctx, "get_productivity_stats", breakdown=["hour", "weekday"])
    assert r.content["summary"]["meta"]["kind"] == "observed"
    assert r.content["summary"]["total_focus_minutes"] == 30
    assert len(r.content["by_hour"]) == 24 and len(r.content["by_weekday"]) == 7
    json.dumps(r.content)  # serialisable for a tool_result block
    est = call(ctx, "get_estimation_accuracy", group_by="project")
    assert est.content["meta"]["kind"] == "observed"
