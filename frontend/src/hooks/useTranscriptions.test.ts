/** Polling hook. The API is MOCKED; timers are fake. */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../services/api";
import { createFakeApi, makeTranscription } from "../test/helpers";
import { useTranscriptions } from "./useTranscriptions";

const t = (status: "pending" | "processing" | "completed" | "failed", extra = {}) =>
  makeTranscription({ status, ...extra });

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

describe("useTranscriptions", () => {
  it("does not poll when there are no answers yet", async () => {
    const api = createFakeApi();
    renderHook(() => useTranscriptions(api, "s1", []));
    await advance(30_000);
    expect(api.listTranscriptions).not.toHaveBeenCalled();
  });

  it("polls through pending and processing until completed, then stops", async () => {
    const api = createFakeApi({
      listTranscriptions: vi.fn()
        .mockResolvedValueOnce([t("pending")])
        .mockResolvedValueOnce([t("processing")])
        .mockResolvedValue([t("completed", { transcript: "hello" })]),
    });
    const { result } = renderHook(() => useTranscriptions(api, "s1", ["q1"]));
    await advance(800);
    expect(result.current.byQuestion.q1.status).toBe("pending");
    await advance(2000);
    expect(result.current.byQuestion.q1.status).toBe("processing");
    await advance(3000);
    expect(result.current.byQuestion.q1.status).toBe("completed");
    expect(result.current.byQuestion.q1.transcript).toBe("hello");
    const calls = vi.mocked(api.listTranscriptions).mock.calls.length;
    await advance(60_000);
    expect(api.listTranscriptions).toHaveBeenCalledTimes(calls); // stopped
    expect(api.listTranscriptions).toHaveBeenCalledWith("s1");
  });

  it("treats a failed transcription as finished", async () => {
    const api = createFakeApi({ listTranscriptions: vi.fn().mockResolvedValue([t("failed", { error_code: "audio_corrupt" })]) });
    renderHook(() => useTranscriptions(api, "s1", ["q1"]));
    await advance(800);
    await advance(60_000);
    expect(api.listTranscriptions).toHaveBeenCalledTimes(1);
  });

  it("keeps polling after a network error and recovers", async () => {
    const api = createFakeApi({
      listTranscriptions: vi.fn()
        .mockRejectedValueOnce(new ApiError("network", "Cannot reach the server."))
        .mockResolvedValue([t("completed", { transcript: "ok" })]),
    });
    const { result } = renderHook(() => useTranscriptions(api, "s1", ["q1"]));
    await advance(800);
    expect(result.current.error).toBe("Cannot reach the server.");
    await advance(2000);
    expect(result.current.error).toBeNull();
    expect(result.current.byQuestion.q1.status).toBe("completed");
  });

  it("starts polling again when a new answer is added", async () => {
    const api = createFakeApi({
      listTranscriptions: vi.fn(async () => [
        t("completed", { question_id: "q1" }),
        t("pending", { question_id: "q2", response_id: "resp-q2" }),
      ]),
    });
    const { result, rerender } = renderHook(({ ids }: { ids: string[] }) => useTranscriptions(api, "s1", ids), {
      initialProps: { ids: ["q1"] },
    });
    await advance(800);
    const before = vi.mocked(api.listTranscriptions).mock.calls.length;
    rerender({ ids: ["q1", "q2"] });
    await advance(10_000);
    expect(vi.mocked(api.listTranscriptions).mock.calls.length).toBeGreaterThan(before);
    expect(result.current.byQuestion.q2.status).toBe("pending");
  });

  it("gives up after 5 minutes, and checkAgain resumes", async () => {
    const api = createFakeApi({ listTranscriptions: vi.fn().mockResolvedValue([t("processing")]) });
    const { result } = renderHook(() => useTranscriptions(api, "s1", ["q1"]));
    await advance(5 * 60 * 1000 + 10_000);
    expect(result.current.timedOut).toBe(true);
    const stopped = vi.mocked(api.listTranscriptions).mock.calls.length;
    await advance(60_000);
    expect(api.listTranscriptions).toHaveBeenCalledTimes(stopped);
    act(() => result.current.checkAgain());
    await advance(1000);
    expect(vi.mocked(api.listTranscriptions).mock.calls.length).toBeGreaterThan(stopped);
    expect(result.current.timedOut).toBe(false);
  });

  it("retry restarts the transcription and polling", async () => {
    const api = createFakeApi({
      listTranscriptions: vi.fn().mockResolvedValue([t("failed", { can_retry: true })]),
      retryTranscription: vi.fn(async () => t("pending")),
    });
    const { result } = renderHook(() => useTranscriptions(api, "s1", ["q1"]));
    await advance(800);
    await act(async () => {
      await result.current.retry("resp-q1");
    });
    expect(api.retryTranscription).toHaveBeenCalledWith("s1", "resp-q1");
    expect(result.current.byQuestion.q1.status).toBe("pending");
    expect(result.current.retryingId).toBeNull();
  });

  it("reports a retry that fails", async () => {
    const api = createFakeApi({
      listTranscriptions: vi.fn().mockResolvedValue([t("failed", { can_retry: true })]),
      retryTranscription: vi.fn().mockRejectedValue(new ApiError("http", "This answer cannot be re-queued right now.", 409)),
    });
    const { result } = renderHook(() => useTranscriptions(api, "s1", ["q1"]));
    await advance(800);
    await act(async () => {
      await result.current.retry("resp-q1");
    });
    expect(result.current.error).toBe("This answer cannot be re-queued right now.");
    expect(result.current.byQuestion.q1.status).toBe("failed");
  });

  it("stops polling when the component unmounts", async () => {
    const api = createFakeApi({ listTranscriptions: vi.fn().mockResolvedValue([t("processing")]) });
    const { unmount } = renderHook(() => useTranscriptions(api, "s1", ["q1"]));
    await advance(800);
    unmount();
    const calls = vi.mocked(api.listTranscriptions).mock.calls.length;
    await advance(60_000);
    expect(api.listTranscriptions).toHaveBeenCalledTimes(calls);
  });
});
