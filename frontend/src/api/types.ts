// Mirrors backend/app/schemas. Timestamps are ISO strings in UTC; dates are YYYY-MM-DD.

export type UUID = string;
export type TaskStatus = "inbox" | "planned" | "in_progress" | "blocked" | "completed" | "cancelled";
export type Priority = "low" | "medium" | "high" | "critical";
export type TimeOfDay = "morning" | "afternoon" | "evening";
export type Energy = "low" | "medium" | "high";
export type TaskSource = "user" | "ai" | "import" | "recurrence";
export type SessionType = "work" | "rest";
export type SessionState = "running" | "paused" | "finished";
export type SessionSource = "timer" | "manual" | "import";
export type EndReason = "completed" | "stopped" | "skipped" | "switched" | "unknown";
export type Outcome = "completed" | "partial" | "blocked" | "abandoned";

export interface Project {
  id: UUID;
  name: string;
  description: string | null;
  color: string | null;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
}

export interface ProjectStats {
  project_id: UUID;
  total_focus_minutes: number;
  session_count: number;
  tasks_completed: number;
  tasks_remaining: number;
  estimated_remaining_minutes: number;
  last_worked_at: string | null;
}

export interface Dependency {
  depends_on_id: UUID;
  strict: boolean;
}

export interface Task {
  id: UUID;
  title: string;
  description: string | null;
  project_id: UUID | null;
  category: string | null;
  priority: Priority;
  status: TaskStatus;
  estimated_minutes: number | null;
  deadline: string | null;
  earliest_start: string | null;
  planned_date: string | null;
  preferred_time: TimeOfDay | null;
  energy_requirement: Energy | null;
  importance: number | null;
  urgency: number | null;
  recurrence_rule: string | null;
  recurrence_parent_id: UUID | null;
  occurrence_date: string | null;
  tags: string[];
  source: TaskSource;
  pending_approval: boolean;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  dependencies: Dependency[];
  is_template: boolean;
  blocked_by: UUID[];
  actual_minutes: number;
}

export type TaskInput = Partial<
  Omit<Task, "id" | "source" | "pending_approval" | "completed_at" | "created_at" | "updated_at" |
    "is_template" | "blocked_by" | "actual_minutes" | "recurrence_parent_id" | "occurrence_date">
>;

export interface FocusSession {
  id: UUID;
  task_id: UUID | null;
  task_title_snapshot: string | null;
  project_id: UUID | null;
  category_snapshot: string | null;
  type: SessionType;
  state: SessionState;
  source: SessionSource;
  start_time: string;
  end_time: string | null;
  tz_offset_minutes: number;
  planned_duration_s: number | null;
  active_duration_s: number | null;
  paused_duration_s: number;
  paused_since: string | null;
  pause_count: number | null;
  elapsed_s: number | null;
  end_reason: EndReason | null;
  outcome: Outcome | null;
  completed: boolean;
  stopped: boolean;
  notes: string | null;
  tags: string[];
  external_id: string | null;
  import_batch_id: UUID | null;
  quality_flags: string[];
  exclude_from_stats: boolean;
  voided_at: string | null;
  created_at: string;
}

export interface LiveSession extends FocusSession {
  server_time: string;
  active_so_far_s: number;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export interface TodayDashboard {
  date: string;
  timezone: string;
  focused_minutes: number;
  rest_minutes: number;
  planned_minutes: number;
  sessions_today: number;
  current_session: LiveSession | null;
  next_tasks: Task[];
  due_today: Task[];
  overdue: Task[];
  inbox_count: number;
  pending_approval_count: number;
}

export interface ImportSummary {
  rows_read: number;
  valid: number;
  duplicates: number;
  invalid: number;
  flagged: number;
  excluded_from_stats: number;
  work_sessions: number;
  rest_sessions: number;
  total_focus_hours: number;
  total_rest_hours: number;
  avg_work_session_minutes: number | null;
  median_work_session_minutes: number | null;
  first_session: string | null;
  last_session: string | null;
  duration_unit: string;
  duration_meaning: "actual" | "planned";
  sections: string[];
  assumed_timezone_rows: number;
  columns_detected: Record<string, string>;
  warnings_by_code: Record<string, number>;
  errors_by_code: Record<string, number>;
  file_previously_imported: boolean;
}

export interface ImportIssue {
  row_number: number;
  status: "imported" | "duplicate" | "invalid";
  errors: string[];
  warnings: string[];
  raw: Record<string, string | null>;
}

export interface ImportReport {
  batch_id: UUID | null;
  dry_run: boolean;
  summary: ImportSummary;
  issues: ImportIssue[];
}

export interface ImportBatch {
  id: UUID;
  kind: string;
  filename: string;
  file_sha256: string;
  options: Record<string, unknown>;
  summary: Partial<ImportSummary>;
  created_at: string;
  rolled_back_at: string | null;
}

export interface Meta {
  kind: "observed";
  from: string | null;
  to: string | null;
  type: SessionType | null;
  session_count: number;
  excluded_count: number;
}

export interface AnalyticsSummary {
  meta: Meta;
  total_focus_minutes: number;
  total_rest_minutes: number;
  session_count: number;
  rest_session_count: number;
  active_days: number;
  avg_daily_focus_minutes: number | null;
  avg_session_minutes: number | null;
  median_session_minutes: number | null;
  longest_session_minutes: number | null;
  total_paused_minutes: number;
  completed_sessions: number;
  stopped_sessions: number;
  skipped_sessions: number;
  switched_sessions: number;
  unknown_end_sessions: number;
  interrupted_sessions: number;
  completion_rate: number | null;
  interruption_rate: number | null;
  tasks_considered: number;
  tasks_completed: number;
  task_completion_rate: number | null;
  planned_vs_actual: { tasks: number; estimated_minutes: number; actual_minutes: number };
}

export interface Timeseries {
  meta: Meta;
  granularity: "day" | "week" | "month";
  items: { period: string; focus_minutes: number; sessions: number }[];
}

export interface HourRow {
  hour: number;
  focus_minutes: number;
  sessions_started: number;
  avg_session_minutes: number | null;
  completion_rate: number | null;
}

export interface WeekdayRow {
  weekday: number;
  name: string;
  focus_minutes: number;
  days_in_range: number;
  avg_daily_focus_minutes: number | null;
  sessions: number;
  avg_session_minutes: number | null;
  completion_rate: number | null;
}

export interface ProjectRow {
  project_id: UUID | null;
  project_name: string;
  focus_minutes: number;
  share: number;
  sessions: number;
}

export interface TagRow {
  tag: string;
  focus_minutes: number;
  share: number;
  sessions: number;
}

export interface EstimationRow {
  group: string;
  group_id: UUID | null;
  samples: number;
  avg_estimate_minutes: number;
  avg_actual_minutes: number;
  ratio: number;
  median_ratio: number;
  multiplier: number;
  weight: number;
  confidence: "insufficient" | "moderate" | "strong";
  tendency: "underestimate" | "overestimate" | "accurate";
}

export interface Pattern {
  id: string;
  kind: "observed";
  statement: string;
  values: Record<string, unknown>;
  sample_size: number;
}

export interface UserSettings {
  timezone: string;
  working_hours: { start: string; end: string; days: number[] };
  scheduling_mode: "manual" | "suggest" | "auto";
  calendar_mode: "read_only" | "suggest" | "auto_create";
  require_approval_for_ai_tasks: boolean;
  focus: { work_minutes: number; break_minutes: number };
  scheduler: {
    buffer_ratio: number;
    max_focus_minutes: number;
    break_minutes: number;
    transition_minutes: number;
    min_block_minutes: number;
    meals: { label: string; start: string; end: string }[];
  };
  import_rules: {
    long_active_minutes: number;
    long_pause_minutes: number;
    implausible_elapsed_hours: number;
    duplicate_tolerance_seconds: number;
    short_session_seconds: number;
  };
  personalization: {
    min_samples: number;
    strong_samples: number;
    prior_strength: number;
    min_multiplier: number;
    max_multiplier: number;
  };
}

export interface CalendarInfo {
  id: string;
  account_id: string;
  summary: string;
  timezone: string | null;
  color: string | null;
  selected: boolean;
  all_day_busy: boolean;
  last_synced_at: string | null;
  last_error: string | null;
}

export interface CalendarAccount {
  id: string;
  provider: "ical" | "google";
  display_name: string;
  status: "connected" | "error";
  feed_host: string | null;
  created_at: string;
  calendars: CalendarInfo[];
}

export interface CalendarEvent {
  id: string;
  calendar_id: string;
  title: string;
  location: string | null;
  start_time: string;
  end_time: string;
  all_day: boolean;
  busy: boolean;
  status: "confirmed" | "tentative" | "cancelled";
  origin: "USER_CREATED_EVENT" | "APP_GENERATED_EVENT";
  recurring_event_id: string | null;
}

export interface CalendarSyncResult {
  calendar_id: string;
  summary: string;
  status: "synced" | "not_modified" | "skipped" | "error";
  created: number;
  updated: number;
  cancelled: number;
  unchanged: number;
  skipped_components: number;
  truncated: boolean;
  error: string | null;
}

export interface TimeSpan {
  start: string;
  end: string;
  minutes: number;
}

export interface FreeTime {
  date: string;
  working_day: boolean;
  window_start: string | null;
  window_end: string | null;
  busy: (TimeSpan & { titles: string[] })[];
  free: TimeSpan[];
  busy_minutes: number;
  free_minutes: number;
  calendars: number;
  synced_at: string | null;
}
