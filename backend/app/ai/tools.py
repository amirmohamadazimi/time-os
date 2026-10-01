"""Claude's tool layer: the only way the AI can read or change application data.

Each tool validates its input with a Pydantic model (whose JSON schema is what Claude sees),
then calls the same service functions as the REST API with ``source=ActionSource.ai``. Domain
rules, audit logging and approval gates therefore apply to AI actions exactly as to UI actions.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.analytics import service as analytics
from app.analytics.frame import Filters
from app.errors import DomainError
from app.models import FocusSession, Task
from app.models.enums import ActionSource, SessionType, TaskStatus
from app.schemas.common import UTCDatetime
from app.schemas.focus import FocusFinish, FocusStart
from app.schemas.settings import UserSettings
from app.schemas.task import DependencyIn, TaskCreate, TaskUpdate
from app.services import focus, sessions, tasks

AI = ActionSource.ai


@dataclass(frozen=True)
class ToolContext:
    db: Session
    now: datetime
    settings: UserSettings
    confirmed: bool = False  # the user explicitly confirmed this call in the UI


@dataclass(frozen=True)
class ToolResult:
    status: Literal["ok", "error", "confirmation_required"]
    content: Any

    @property
    def is_error(self) -> bool:
        return self.status != "ok"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[ToolContext, Any], Any]
    mutating: bool = False
    requires_confirmation: bool = False
    phase: int = 1

    def definition(self) -> dict[str, Any]:
        """Tool definition in the Anthropic Messages API format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": json_schema(self.input_model),
        }


REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, description: str, *, mutating: bool = False, requires_confirmation: bool = False):
    def register(fn: Callable[[ToolContext, Any], Any]):
        model = fn.__annotations__["args"]
        REGISTRY[name] = ToolSpec(name, description, model, fn, mutating, requires_confirmation)
        return fn

    return register


def json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema with $defs inlined and titles removed (smaller, self-contained)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def definitions() -> list[dict[str, Any]]:
    return [spec.definition() for spec in REGISTRY.values()]


def execute_tool(ctx: ToolContext, name: str, raw_input: dict[str, Any] | None) -> ToolResult:
    spec = REGISTRY.get(name)
    if spec is None:
        return ToolResult("error", {"error": f"unknown tool '{name}'", "available": sorted(REGISTRY)})
    try:
        args = spec.input_model.model_validate(raw_input or {})
    except ValidationError as exc:
        return ToolResult("error", {
            "error": "invalid input",
            "details": exc.errors(include_url=False, include_context=False, include_input=False),
        })  # fmt: skip
    if spec.requires_confirmation and not ctx.confirmed:
        return ToolResult("confirmation_required", {
            "message": f"'{name}' changes data irreversibly and needs the user's confirmation.",
            "input": args.model_dump(mode="json"),
        })  # fmt: skip
    try:
        return ToolResult("ok", spec.handler(ctx, args))
    except DomainError as exc:
        ctx.db.rollback()
        return ToolResult("error", {"error": exc.code, "message": exc.message, "details": exc.details})


# ------------------------------------------------------------------ compact read models


def task_brief(db: Session, items: list[Task]) -> list[dict[str, Any]]:
    out = []
    for t in tasks.to_out(db, items):
        out.append({
            "id": str(t.id), "title": t.title, "status": t.status.value, "priority": t.priority.value,
            "project_id": str(t.project_id) if t.project_id else None, "category": t.category,
            "estimated_minutes": t.estimated_minutes, "actual_minutes": t.actual_minutes,
            "deadline": t.deadline.isoformat() if t.deadline else None,
            "planned_date": t.planned_date.isoformat() if t.planned_date else None,
            "blocked_by": [str(b) for b in t.blocked_by], "pending_approval": t.pending_approval,
            "source": t.source.value, "tags": t.tags,
        })  # fmt: skip
    return out


def session_brief(s: FocusSession, now: datetime) -> dict[str, Any]:
    return {
        "id": str(s.id), "task_id": str(s.task_id) if s.task_id else None,
        "task_title": s.task_title_snapshot,
        "type": s.type.value, "state": s.state.value, "start_time": s.start_time.isoformat(),
        "end_time": s.end_time.isoformat() if s.end_time else None,
        "active_minutes": round(focus.active_so_far(s, now) / 60, 1),
        "paused_minutes": round(focus.paused_so_far(s, now) / 60, 1),
        "end_reason": s.end_reason.value if s.end_reason else None,
        "outcome": s.outcome.value if s.outcome else None, "notes": s.notes, "tags": s.tags,
        "source": s.source.value,
    }  # fmt: skip


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


StatusName = Literal["inbox", "planned", "in_progress", "blocked", "completed", "cancelled"]
PriorityName = Literal["low", "medium", "high", "critical"]


# ------------------------------------------------------------------ tasks


class GetTasksArgs(_Args):
    status: list[StatusName] | None = Field(None, description="Filter by status; default: all open statuses")
    project_id: uuid.UUID | None = None
    planned_date: date | None = Field(None, description="Local date the task is planned for")
    due_before: UTCDatetime | None = None
    limit: int = Field(25, ge=1, le=50)


@tool("get_tasks", "List tasks with optional filters. Returns compact task records (never the whole table).")
def get_tasks(ctx: ToolContext, args: GetTasksArgs):
    statuses = (
        [TaskStatus(s) for s in args.status]
        if args.status
        else [TaskStatus.inbox, TaskStatus.planned, TaskStatus.in_progress, TaskStatus.blocked]
    )
    rows = tasks.list_tasks(
        ctx.db,
        statuses=statuses,
        project_id=args.project_id,
        planned_date=args.planned_date,
        due_before=args.due_before,
        limit=args.limit,
    )
    return {"tasks": task_brief(ctx.db, rows)}


class SearchTasksArgs(_Args):
    query: str = Field(
        min_length=1, max_length=200, description="Words matched against title, notes, category, tags"
    )
    limit: int = Field(10, ge=1, le=50)


@tool(
    "search_tasks",
    "Find tasks by text. Use this to resolve a task the user mentions by name before acting on it.",
)
def search_tasks(ctx: ToolContext, args: SearchTasksArgs):
    return {"tasks": task_brief(ctx.db, tasks.search_tasks(ctx.db, args.query, args.limit))}


class TaskDraft(_Args):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(None, max_length=5000)
    project_id: uuid.UUID | None = None
    category: str | None = Field(None, max_length=100)
    priority: PriorityName = "medium"
    estimated_minutes: int | None = Field(None, gt=0, le=10000)
    deadline: UTCDatetime | None = None
    planned_date: date | None = None
    tags: list[str] = Field(default_factory=list, max_length=30)


class CreateTaskArgs(TaskDraft):
    reason: str | None = Field(
        None, max_length=500, description="Why you are creating it (shown to the user)"
    )


def _needs_approval(ctx: ToolContext) -> bool:
    return ctx.settings.require_approval_for_ai_tasks


@tool(
    "create_task",
    "Create one task. Unless the user disabled approval, it is stored as a proposal that the "
    "user must approve before it enters the plan.",
    mutating=True,
)
def create_task(ctx: ToolContext, args: CreateTaskArgs):
    data = TaskCreate(**args.model_dump(exclude={"reason"}), status=TaskStatus.planned)
    task = tasks.create_task(
        ctx.db, data, ctx.now, source=AI, pending_approval=_needs_approval(ctx), reason=args.reason
    )
    return {"task": task_brief(ctx.db, [task])[0]}


class ProposeTasksArgs(_Args):
    goal: str = Field(min_length=1, max_length=500, description="The user's goal being decomposed")
    tasks: list[TaskDraft] = Field(min_length=1, max_length=20)
    sequential: bool = Field(False, description="Each task strictly depends on the previous one")


@tool(
    "propose_tasks",
    "Turn a goal into several actionable tasks (task decomposition). All are stored as "
    "proposals pending the user's approval.",
    mutating=True,
)
def propose_tasks(ctx: ToolContext, args: ProposeTasksArgs):
    created: list[Task] = []
    for draft in args.tasks:
        deps = [DependencyIn(depends_on_id=created[-1].id)] if args.sequential and created else []
        data = TaskCreate(**draft.model_dump(), status=TaskStatus.planned, dependencies=deps)
        created.append(
            tasks.create_task(
                ctx.db,
                data,
                ctx.now,
                source=AI,
                pending_approval=_needs_approval(ctx),
                reason=f"decomposition of: {args.goal}",
                commit=False,
            )
        )
    ctx.db.commit()
    return {"goal": args.goal, "tasks": task_brief(ctx.db, created)}


class UpdateTaskArgs(_Args):
    task_id: uuid.UUID
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=5000)
    project_id: uuid.UUID | None = None
    category: str | None = Field(None, max_length=100)
    priority: PriorityName | None = None
    status: StatusName | None = None
    estimated_minutes: int | None = Field(None, gt=0, le=10000)
    deadline: UTCDatetime | None = None
    planned_date: date | None = None
    tags: list[str] | None = None
    reason: str | None = Field(None, max_length=500)


@tool(
    "update_task", "Change fields of an existing task. Only the fields you pass are changed.", mutating=True
)
def update_task(ctx: ToolContext, args: UpdateTaskArgs):
    fields = args.model_dump(exclude_unset=True, exclude={"task_id", "reason"})
    task = tasks.update_task(
        ctx.db, args.task_id, TaskUpdate(**fields), ctx.now, source=AI, reason=args.reason
    )
    return {"task": task_brief(ctx.db, [task])[0]}


class TaskIdArgs(_Args):
    task_id: uuid.UUID


@tool("complete_task", "Mark a task as completed.", mutating=True)
def complete_task(ctx: ToolContext, args: TaskIdArgs):
    return {"task": task_brief(ctx.db, [tasks.complete_task(ctx.db, args.task_id, ctx.now, source=AI)])[0]}


class DeleteTaskArgs(_Args):
    task_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=500)


@tool(
    "delete_task",
    "Permanently delete a task. Requires the user's explicit confirmation; prefer setting "
    "status to cancelled.",
    mutating=True,
    requires_confirmation=True,
)
def delete_task(ctx: ToolContext, args: DeleteTaskArgs):
    tasks.delete_task(ctx.db, args.task_id, source=AI, reason=args.reason)
    return {"deleted": str(args.task_id)}


# ------------------------------------------------------------------ focus sessions


class NoArgs(_Args):
    pass


@tool("get_current_focus_session", "The live focus session, if any, with active minutes so far.")
def get_current_focus_session(ctx: ToolContext, args: NoArgs):
    live = focus.get_live(ctx.db)
    return {"session": session_brief(live, ctx.now) if live else None}


class StartFocusArgs(_Args):
    task_id: uuid.UUID | None = None
    type: Literal["work", "rest"] = "work"
    planned_minutes: int | None = Field(None, ge=1, le=480)


@tool(
    "start_focus_session",
    "Start the focus timer, optionally on a task. Fails if a session is already live or the task is blocked.",
    mutating=True,
)
def start_focus_session(ctx: ToolContext, args: StartFocusArgs):
    data = FocusStart(
        task_id=args.task_id,
        type=SessionType(args.type),
        planned_duration_s=args.planned_minutes * 60 if args.planned_minutes else None,
    )
    return {"session": session_brief(focus.start(ctx.db, data, ctx.now, ctx.settings, source=AI), ctx.now)}


class StopFocusArgs(_Args):
    end_reason: Literal["completed", "stopped", "skipped"] = "completed"
    outcome: Literal["completed", "partial", "blocked", "abandoned"] | None = None
    notes: str | None = Field(None, max_length=5000)
    complete_task: bool = False


@tool("stop_focus_session", "Finish the live focus session and log it.", mutating=True)
def stop_focus_session(ctx: ToolContext, args: StopFocusArgs):
    session = focus.finish(ctx.db, FocusFinish(**args.model_dump()), ctx.now, source=AI)
    return {"session": session_brief(session, ctx.now)}


class SearchSessionsArgs(_Args):
    date_from: date | None = None
    date_to: date | None = None
    task_id: uuid.UUID | None = None
    tag: str | None = None
    query: str | None = Field(None, max_length=200)
    type: Literal["work", "rest"] | None = None
    limit: int = Field(25, ge=1, le=50)


@tool("search_sessions", "Find logged focus sessions by date range, task, tag or note text.")
def search_sessions(ctx: ToolContext, args: SearchSessionsArgs):
    rows, total = sessions.list_sessions(
        ctx.db,
        ctx.settings,
        date_from=args.date_from,
        date_to=args.date_to,
        task_id=args.task_id,
        tag=args.tag,
        q=args.query,
        type_=SessionType(args.type) if args.type else None,
        limit=args.limit,
    )
    return {"total": total, "sessions": [session_brief(s, ctx.now) for s in rows]}


# ------------------------------------------------------------------ analytics


class StatsArgs(_Args):
    date_from: date | None = None
    date_to: date | None = None
    project_id: uuid.UUID | None = None
    breakdown: list[Literal["hour", "weekday", "project", "tag", "day"]] = Field(default_factory=list)


@tool(
    "get_productivity_stats",
    "Observed productivity statistics computed by the analytics engine (totals, "
    "averages, completion and interruption rates, optional breakdowns). "
    "Quote these numbers; do not recompute.",
)
def get_productivity_stats(ctx: ToolContext, args: StatsArgs):
    f = Filters(date_from=args.date_from, date_to=args.date_to, project_id=args.project_id)
    out: dict[str, Any] = {"summary": analytics.summary(ctx.db, ctx.settings, f)}
    calls = {
        "hour": lambda: analytics.by_hour(ctx.db, ctx.settings, f)["items"],
        "weekday": lambda: analytics.by_weekday(ctx.db, ctx.settings, f)["items"],
        "project": lambda: analytics.by_project(ctx.db, ctx.settings, f)["items"],
        "tag": lambda: analytics.by_tag(ctx.db, ctx.settings, f)["items"],
        "day": lambda: analytics.timeseries(ctx.db, ctx.settings, f, "day")["items"],
    }
    for name in dict.fromkeys(args.breakdown):
        out[f"by_{name}"] = calls[name]()
    return _jsonable(out)


class EstimationArgs(_Args):
    group_by: Literal["category", "project"] = "category"


@tool(
    "get_estimation_accuracy",
    "Estimated vs actual duration by category or project, with sample sizes, "
    "confidence and the multiplier the scheduler would apply.",
)
def get_estimation_accuracy(ctx: ToolContext, args: EstimationArgs):
    return _jsonable(analytics.estimation_accuracy(ctx.db, ctx.settings, args.group_by))


def _jsonable(value: Any) -> Any:
    from app.services.audit import jsonable

    return jsonable(value)
