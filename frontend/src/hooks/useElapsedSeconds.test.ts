import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useElapsedSeconds } from "./useElapsedSeconds";

describe("useElapsedSeconds", () => {
  it("counts while running, holds while stopped, and continues", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ running }: { running: boolean }) => useElapsedSeconds(running), {
      initialProps: { running: true },
    });
    expect(result.current).toBe(0);
    act(() => void vi.advanceTimersByTime(3000));
    expect(result.current).toBe(3);

    rerender({ running: false });
    act(() => void vi.advanceTimersByTime(5000));
    expect(result.current).toBe(3);

    rerender({ running: true });
    act(() => void vi.advanceTimersByTime(2000));
    expect(result.current).toBe(5);
  });
});
