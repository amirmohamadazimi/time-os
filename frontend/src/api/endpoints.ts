import { api } from "./client";
import type {
  AnalyticsSummary, EstimationRow, FocusSession, HourRow, ImportBatch, ImportReport, LiveSession, Meta, Page,
  Pattern, Project, ProjectRow, ProjectStats, TagRow, Task, TaskInput, TaskStatus, Timeseries, TodayDashboard,
  UserSettings, WeekdayRow,
} from "./types";

export interface Range {
  from?: string;
  to?: string;
  project_id?: string;
  tag?: string;
  type?: "work" | "rest";
}

export const endpoints = {
  dashboard: () => api.get<TodayDashboard>("/dashboard/today"),

  projects: (status?: "active" | "archived") => api.get<Project[]>("/projects", { status }),
  createProject: (body: Partial<Project>) => api.post<Project>("/projects", body),
  updateProject: (id: string, body: Partial<Project>) => api.patch<Project>(`/projects/${id}`, body),
  deleteProject: (id: string) => api.del(`/projects/${id}`),
  projectStats: (id: string) => api.get<ProjectStats>(`/projects/${id}/stats`),

  tasks: (q: { status?: TaskStatus[]; project_id?: string; q?: string; pending_approval?: boolean;
               planned_date?: string; include_templates?: boolean } = {}) => api.get<Task[]>("/tasks", q),
  categories: () => api.get<string[]>("/tasks/categories"),
  createTask: (body: TaskInput) => api.post<Task>("/tasks", body),
  captureInbox: (text: string) => api.post<Task[]>("/tasks/inbox", { text }),
  updateTask: (id: string, body: TaskInput) => api.patch<Task>(`/tasks/${id}`, body),
  deleteTask: (id: string) => api.del(`/tasks/${id}`),
  completeTask: (id: string) => api.post<Task>(`/tasks/${id}/complete`),
  approveTask: (id: string) => api.post<Task>(`/tasks/${id}/approve`),

  currentFocus: () => api.get<LiveSession | null>("/focus/current"),
  startFocus: (body: { task_id?: string | null; type: "work" | "rest"; planned_duration_s?: number | null;
                       notes?: string | null; tags?: string[] }) =>
    api.post<LiveSession>("/focus/start", body),
  pauseFocus: () => api.post<LiveSession>("/focus/pause"),
  resumeFocus: () => api.post<LiveSession>("/focus/resume"),
  annotateFocus: (body: { notes?: string | null; tags?: string[] }) => api.patch<LiveSession>("/focus/current", body),
  finishFocus: (body: { end_reason: "completed" | "stopped" | "skipped"; outcome?: string | null;
                        notes?: string | null; complete_task?: boolean }) =>
    api.post<FocusSession>("/focus/finish", body),
  switchFocus: (body: { task_id: string; planned_duration_s?: number | null }) =>
    api.post<LiveSession>("/focus/switch", body),
  discardFocus: () => api.del("/focus/current"),

  sessions: (q: Range & { q?: string; limit?: number; offset?: number; task_id?: string; source?: string }) =>
    api.get<Page<FocusSession>>("/sessions", { ...q }),
  logSession: (body: Record<string, unknown>) => api.post<FocusSession>("/sessions", body),
  annotateSession: (id: string, body: Record<string, unknown>) => api.patch<FocusSession>(`/sessions/${id}`, body),
  voidSession: (id: string) => api.del(`/sessions/${id}`),

  importSessions: (file: File, opts: { dry_run: boolean; default_timezone?: string; duration_unit?: string }) => {
    const form = new FormData();
    form.append("file", file);
    return api.upload<ImportReport>("/imports/focus-sessions", form, opts);
  },
  imports: () => api.get<ImportBatch[]>("/imports"),
  rollbackImport: (id: string) => api.del<ImportBatch>(`/imports/${id}`),

  summary: (r: Range) => api.get<AnalyticsSummary>("/analytics/summary", { ...r }),
  timeseries: (r: Range, granularity: "day" | "week" | "month") =>
    api.get<Timeseries>("/analytics/timeseries", { ...r, granularity }),
  byHour: (r: Range) => api.get<{ meta: Meta; items: HourRow[] }>("/analytics/by-hour", { ...r }),
  byWeekday: (r: Range) => api.get<{ meta: Meta; items: WeekdayRow[] }>("/analytics/by-weekday", { ...r }),
  byProject: (r: Range) => api.get<{ meta: Meta; items: ProjectRow[] }>("/analytics/by-project", { ...r }),
  byTag: (r: Range) => api.get<{ meta: Meta; items: TagRow[] }>("/analytics/by-tag", { ...r }),
  estimation: (group_by: "category" | "project") =>
    api.get<{ items: EstimationRow[] }>("/analytics/estimation", { group_by }),
  patterns: (r: Range) => api.get<{ meta: Meta; items: Pattern[] }>("/analytics/patterns", { ...r }),

  settings: () => api.get<UserSettings>("/settings"),
  updateSettings: (patch: Record<string, unknown>) => api.put<UserSettings>("/settings", patch),
};
