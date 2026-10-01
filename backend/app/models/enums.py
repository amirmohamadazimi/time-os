from enum import StrEnum


class ProjectStatus(StrEnum):
    active = "active"
    archived = "archived"


class TaskStatus(StrEnum):
    inbox = "inbox"
    planned = "planned"
    in_progress = "in_progress"
    blocked = "blocked"
    completed = "completed"
    cancelled = "cancelled"


OPEN_TASK_STATUSES = (TaskStatus.inbox, TaskStatus.planned, TaskStatus.in_progress, TaskStatus.blocked)


class Priority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class TimeOfDay(StrEnum):
    morning = "morning"
    afternoon = "afternoon"
    evening = "evening"


class Energy(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class TaskSource(StrEnum):
    user = "user"
    ai = "ai"
    import_ = "import"
    recurrence = "recurrence"


class SessionType(StrEnum):
    work = "work"
    rest = "rest"


class SessionState(StrEnum):
    running = "running"
    paused = "paused"
    finished = "finished"


class SessionSource(StrEnum):
    timer = "timer"
    manual = "manual"
    import_ = "import"


class EndReason(StrEnum):
    completed = "completed"  # timer reached its target / user marked the session complete
    stopped = "stopped"  # user ended the session early
    skipped = "skipped"  # session skipped (typically a break)
    switched = "switched"  # ended because the user switched to another task
    unknown = "unknown"  # source did not say (e.g. imports with neither flag set)


class Outcome(StrEnum):
    completed = "completed"
    partial = "partial"
    blocked = "blocked"
    abandoned = "abandoned"


class ImportRecordStatus(StrEnum):
    imported = "imported"
    duplicate = "duplicate"
    invalid = "invalid"


class ActionSource(StrEnum):
    user = "user"
    ai = "ai"
    scheduler = "scheduler"
    import_ = "import"
    calendar = "calendar"
    system = "system"
