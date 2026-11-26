import { describe, expect, it } from "vitest";
import { formatBytes, formatDuration } from "./format";

describe("formatDuration", () => {
  it("formats seconds as mm:ss", () => {
    expect(formatDuration(0)).toBe("00:00");
    expect(formatDuration(75)).toBe("01:15");
    expect(formatDuration(600)).toBe("10:00");
    expect(formatDuration(59.9)).toBe("00:59");
  });
  it("treats negative or invalid values as zero", () => {
    expect(formatDuration(-5)).toBe("00:00");
    expect(formatDuration(Number.NaN)).toBe("00:00");
  });
});

describe("formatBytes", () => {
  it("uses sensible units", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(formatBytes(-1)).toBe("0 B");
  });
});
