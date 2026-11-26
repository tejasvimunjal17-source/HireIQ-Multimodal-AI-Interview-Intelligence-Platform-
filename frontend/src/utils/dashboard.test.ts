import { describe, expect, it } from "vitest";
import { makeRow } from "../test/dashboardHelpers";
import { adviceSummary, candidateLabel, describeScoreSource, formatDate, formatScore, humanizeKey, pageCount, scalePercent, statusLabel } from "./dashboard";

describe("formatScore", () => {
  it("keeps stored precision without trailing zeros", () => {
    expect(formatScore(75.5)).toBe("75.5");
    expect(formatScore(69.75)).toBe("69.75");
    expect(formatScore(100)).toBe("100");
    expect(formatScore(70.126)).toBe("70.13");
  });
  it("shows a real zero as 0 but a missing score as 'Not scored'", () => {
    expect(formatScore(0)).toBe("0");
    expect(formatScore(null)).toBe("Not scored");
    expect(formatScore(undefined)).toBe("Not scored");
    expect(formatScore(Number.NaN)).toBe("Not scored");
  });
});

describe("scalePercent", () => {
  it("maps a value onto the stored scale", () => {
    expect(scalePercent(5, 0, 10)).toBe(50);
    expect(scalePercent(7.5, 5, 10)).toBe(50);
    expect(scalePercent(10, 0, 10)).toBe(100);
  });
  it("clamps and survives bad scales", () => {
    expect(scalePercent(12, 0, 10)).toBe(100);
    expect(scalePercent(-3, 0, 10)).toBe(0);
    expect(scalePercent(5, null, 10)).toBe(0);
    expect(scalePercent(5, 10, 10)).toBe(0);
  });
});

describe("labels", () => {
  it("names statuses and falls back to the raw value", () => {
    expect(statusLabel("processing")).toBe("Evaluating");
    expect(statusLabel("something_new")).toBe("something_new");
  });
  it("handles missing and very long candidate names", () => {
    expect(candidateLabel({ candidate_name: null, session_id: "abcdef12-0000" })).toBe("Unnamed candidate (abcdef12)");
    expect(candidateLabel({ candidate_name: "   ", session_id: "abcdef12-0000" })).toContain("Unnamed candidate");
    expect(candidateLabel({ candidate_name: "A".repeat(200), session_id: "x" })).toHaveLength(200);
  });
  it("humanizes criterion keys", () => {
    expect(humanizeKey("technical_accuracy")).toBe("Technical accuracy");
    expect(humanizeKey("")).toBe("");
  });
});

describe("dates, advice and paging", () => {
  it("formats dates in UTC and tolerates missing or bad values", () => {
    expect(formatDate("2026-11-20T23:30:00Z")).toBe("20 Nov 2026");
    expect(formatDate(null)).toBe("—");
    expect(formatDate("not a date")).toBe("—");
  });
  it("lists only advice that exists", () => {
    expect(adviceSummary(makeRow({ advice: { proceed: 2, hold: 0, reject: 1 } }))).toEqual([{ advice: "proceed", count: 2 }, { advice: "reject", count: 1 }]);
    expect(adviceSummary(makeRow({ advice: { proceed: 0, hold: 0, reject: 0 } }))).toEqual([]);
  });
  it("explains where a score comes from", () => {
    expect(describeScoreSource("stored_report", 2)).toBe("Stored session score");
    expect(describeScoreSource("average_of_answers", 1)).toBe("Average of 1 evaluated answer");
    expect(describeScoreSource("average_of_answers", 3)).toBe("Average of 3 evaluated answers");
    expect(describeScoreSource(null, 0)).toBe("");
  });
  it("counts pages", () => {
    expect(pageCount(0, 20)).toBe(1);
    expect(pageCount(20, 20)).toBe(1);
    expect(pageCount(21, 20)).toBe(2);
  });
});
