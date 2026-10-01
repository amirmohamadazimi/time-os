import { describe, expect, it } from "vitest";
import type { LiveSession } from "../api/types";
import { formatClock, formatMinutes, formatPercent, parseTags } from "./format";
import { liveActiveSeconds, remainingSeconds } from "./timer";

describe("format", () => {
  it("formats clocks and minutes", () => {
    expect(formatClock(5025)).toBe("01:23:45");
    expect(formatClock(-3)).toBe("00:00:00");
    expect(formatMinutes(222)).toBe("3h 42m");
    expect(formatMinutes(45)).toBe("45m");
    expect(formatMinutes(null)).toBe("–");
    expect(formatPercent(0.666)).toBe("67%");
  });

  it("parses tags", () => {
    expect(parseTags("#python, quant; Python ,  ")).toEqual(["python", "quant"]);
  });
});

describe("liveActiveSeconds", () => {
  const base = {
    state: "running",
    server_time: "2026-10-01T10:00:00Z",
    active_so_far_s: 600,
    planned_duration_s: 1500,
  } as LiveSession;

  it("advances while running, corrected for clock skew", () => {
    const browserNow = Date.parse("2026-10-01T10:00:30Z") - 5000; // browser clock 5s behind
    expect(liveActiveSeconds(base, 5000, browserNow)).toBe(630);
  });

  it("freezes while paused", () => {
    const paused = { ...base, state: "paused" } as LiveSession;
    expect(liveActiveSeconds(paused, 0, Date.parse("2026-10-01T11:00:00Z"))).toBe(600);
  });

  it("computes remaining time against the plan", () => {
    expect(remainingSeconds(base, 600)).toBe(900);
    expect(remainingSeconds({ ...base, planned_duration_s: null }, 600)).toBeNull();
  });
});
