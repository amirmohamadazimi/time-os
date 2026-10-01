import type { LiveSession } from "../api/types";

/**
 * Active seconds of a live session "now", computed from the server's snapshot.
 * `skewMs` = server clock − browser clock at the time the snapshot was received, so the
 * display stays right even if the two clocks disagree.
 */
export function liveActiveSeconds(session: LiveSession, skewMs: number, nowMs: number): number {
  if (session.state === "paused") return session.active_so_far_s;
  const serverNow = nowMs + skewMs;
  const sinceSnapshot = (serverNow - Date.parse(session.server_time)) / 1000;
  return Math.max(0, session.active_so_far_s + Math.max(0, sinceSnapshot));
}

export function remainingSeconds(session: LiveSession, active: number): number | null {
  return session.planned_duration_s ? session.planned_duration_s - active : null;
}
