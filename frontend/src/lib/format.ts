import dayjs from "dayjs";

/** 5025 → "01:23:45" */
export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return [h, m, sec].map((n) => String(n).padStart(2, "0")).join(":");
}

/** 222 → "3h 42m", 45 → "45m", 0 → "0m" */
export function formatMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "–";
  const total = Math.round(minutes);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

export function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : `${Math.round(value * 100)}%`;
}

export function formatDateTime(iso: string | null | undefined): string {
  return iso ? dayjs(iso).format("ddd D MMM, HH:mm") : "–";
}

export function formatDate(iso: string | null | undefined): string {
  return iso ? dayjs(iso).format("ddd D MMM YYYY") : "–";
}

export function formatTime(iso: string | null | undefined): string {
  return iso ? dayjs(iso).format("HH:mm") : "–";
}

export function isoDate(d: Date | dayjs.Dayjs): string {
  return dayjs(d).format("YYYY-MM-DD");
}

/** Comma/space separated input → clean tag list. */
export function parseTags(input: string): string[] {
  const seen = new Set<string>();
  return input
    .split(/[,;]/)
    .map((t) => t.trim().replace(/^#/, ""))
    .filter((t) => t && !seen.has(t.toLowerCase()) && seen.add(t.toLowerCase()));
}
