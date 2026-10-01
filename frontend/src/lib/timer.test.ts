import { describe, expect, it } from "vitest";
import type { LiveSession } from "../api/types";
import { liveActiveSeconds, remainingSeconds } from "./timer";

const snapshot = (overrides: Partial<LiveSession>): LiveSession =>
  ({ state: "running", active_so_far_s: 600, server_time: "2026-10-01T10:00:00Z", planned_duration_s: 1500,
     ...overrides }) as LiveSession;

describe("liveActiveSeconds", () => {
  const serverMs = Date.parse("2026-10-01T10:00:00Z");

  it("advances a running session from the server snapshot", () => {
    expect(liveActiveSeconds(snapshot({}), 0, serverMs + 30_000)).toBe(630);
  });

  it("corrects for a browser clock that is ahead of the server", () => {
    // Browser is 5 minutes fast: skew = server − browser = −300 s.
    expect(liveActiveSeconds(snapshot({}), -300_000, serverMs + 300_000 + 10_000)).toBe(610);
  });

  it("freezes a paused session", () => {
    expect(liveActiveSeconds(snapshot({ state: "paused" }), 0, serverMs + 600_000)).toBe(600);
  });

  it("never goes below the snapshot when the clock jumps backwards", () => {
    expect(liveActiveSeconds(snapshot({}), 0, serverMs - 60_000)).toBe(600);
  });
});

describe("remainingSeconds", () => {
  it("counts down against the planned duration, negative once over", () => {
    expect(remainingSeconds(snapshot({}), 1000)).toBe(500);
    expect(remainingSeconds(snapshot({}), 1600)).toBe(-100);
    expect(remainingSeconds(snapshot({ planned_duration_s: null }), 1000)).toBeNull();
  });
});
