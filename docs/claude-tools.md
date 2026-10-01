# Claude integration: tools, context and provider

Claude is the reasoning and conversational layer. It has **no database access**; it can only
call the tools registered in [`backend/app/ai/tools.py`](../backend/app/ai/tools.py), and
every tool calls the same service functions as the REST API.

```
User ─► Chat endpoint ─► Context builder ─► Claude (Messages API, tool use)
                                               │ tool_use
                                               ▼
                                    Tool registry (Pydantic input validation)
                                               │
                                               ▼
                               Application services (domain validation, audit)
                                               │
                                               ▼
                                   Database / Google Calendar
```

## Tool contract

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]       # JSON schema sent to Claude, also used to validate input
    handler: Callable[[ToolContext, BaseModel], Any]
    mutating: bool = False             # writes go to the audit log with source="ai"
    requires_confirmation: bool = False  # destructive: needs the user's explicit confirmation

def execute_tool(ctx: ToolContext, name: str, raw_input: dict) -> ToolResult
```

`execute_tool` is the single entry point for model-originated actions:

1. Unknown tool → error result.
2. Input validated against the tool's Pydantic model → validation errors are returned to
   Claude as an `is_error` tool result so it can correct itself.
3. `requires_confirmation` tools return `confirmation_required` unless the user has confirmed
   that call in the UI.
4. The handler calls services with `source="ai"`. Services apply the same rules as for the UI
   (task exists, dependency cycles, deadlines, calendar conflicts once Phase 4 lands). Domain
   errors become error results; nothing bypasses validation.
5. Results are compact JSON (ids, titles, minutes) rather than full rows.

AI-created tasks are stored with `source="ai"` and `pending_approval=true` (unless the user
turned off `require_approval_for_ai_tasks`), so decomposed goals never enter the plan until
the user accepts them.

## Tool catalogue

| Tool | Phase | Mutating | Notes |
|---|---|---|---|
| `get_tasks` | 1 ✅ | | filters: status, project, planned date, due before |
| `search_tasks` | 1 ✅ | | text search over title/description/tags |
| `create_task` | 1 ✅ | yes | lands as a pending proposal by default |
| `propose_tasks` | 1 ✅ | yes | batch of tasks from decomposition, all pending approval |
| `update_task` | 1 ✅ | yes | partial update |
| `complete_task` | 1 ✅ | yes | |
| `delete_task` | 1 ✅ | yes | requires confirmation |
| `get_current_focus_session` | 1 ✅ | | |
| `start_focus_session` | 1 ✅ | yes | |
| `stop_focus_session` | 1 ✅ | yes | |
| `search_sessions` | 2 ✅ | | date range, task, tag, text |
| `get_productivity_stats` | 2 ✅ | | summary + by hour/weekday/project, all `observed` |
| `get_estimation_accuracy` | 2 ✅ | | multipliers with sample sizes |
| `get_calendar`, `get_free_time` | 3 | | from the local calendar cache |
| `get_today_schedule`, `generate_schedule`, `reschedule_task` | 4 | yes | engine output only; validated |
| `get_daily_report`, `get_weekly_report` | 5 | | deterministic report + Claude narrative |

## Context builder (Phase 5)

Claude receives only what a question needs. The chat service classifies the request
(planning, retrospective, status, task management) and assembles a bounded context:

| Question type | Context |
|---|---|
| "What should I work on now?" | current session, today's schedule, top eligible tasks with reasons, free time until next event |
| "Why was I unproductive yesterday?" | yesterday's tasks, calendar, sessions, planned-vs-actual, 4-week baseline metrics |
| "What am I underestimating?" | estimation table (groups with ≥ min samples) |
| Task management | matching tasks only (search), never the whole table |

Larger questions are answered by Claude calling tools for more data, not by dumping rows
into the prompt. Every metric in the context is computed by the analytics engine and labelled
`observed`; Claude is instructed to label its own interpretation as interpretation and to
avoid causal claims the data cannot support.

## Provider abstraction (Phase 5)

```python
class LLMProvider(Protocol):
    def run(self, system: str, messages: list[dict], tools: list[dict]) -> Iterator[LLMEvent]: ...
```

The default implementation uses the official `anthropic` Python SDK with model
`claude-opus-5-5` (configurable through `TIMEOS_AI_MODEL`), streaming, adaptive thinking and
the SDK's tool runner hooks for audit and confirmation. Swapping models or providers changes
only this adapter. With no `ANTHROPIC_API_KEY` the provider is absent and the chat UI shows
that AI is disabled; nothing else depends on it.

## Testing

Tests never call the live API. `tests/test_ai_tools.py` exercises the registry directly
(validation errors, confirmation gating, audit with `source="ai"`, pending approval), and
Phase 5 adds a scripted fake provider that emits predetermined `tool_use` blocks to test the
chat loop end-to-end.
