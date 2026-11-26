/** Recorder hook tests. MediaRecorder and getUserMedia are MOCKED (see test/helpers.ts). */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { installFakeMedia, installNoMediaSupport } from "../test/helpers";
import { getRecorderSupport, mapMediaError, useAudioRecorder } from "./useAudioRecorder";

beforeEach(() => {
  vi.useFakeTimers();
});

async function startRecording(result: { current: ReturnType<typeof useAudioRecorder> }) {
  await act(async () => {
    await result.current.start();
  });
}

describe("browser support detection", () => {
  it("is supported when MediaRecorder and getUserMedia exist on a secure page", () => {
    installFakeMedia();
    expect(getRecorderSupport()).toEqual({ supported: true });
  });
  it("reports an insecure context (plain http)", () => {
    installFakeMedia({ secure: false });
    expect(getRecorderSupport()).toEqual({ supported: false, reason: "insecure-context" });
  });
  it("reports missing MediaRecorder / microphone API", () => {
    installNoMediaSupport();
    expect(getRecorderSupport()).toEqual({ supported: false, reason: "unsupported" });
  });
});

describe("error mapping", () => {
  it.each([
    ["NotAllowedError", "permission-denied"],
    ["SecurityError", "permission-denied"],
    ["NotFoundError", "no-microphone"],
    ["NotReadableError", "microphone-busy"],
    ["NotSupportedError", "unsupported"],
    ["SomethingElse", "unknown"],
  ])("%s -> %s", (name: string, kind: string) => {
    expect(mapMediaError({ name })).toBe(kind);
  });
  it("handles non-object errors", () => {
    expect(mapMediaError("boom")).toBe("unknown");
    expect(mapMediaError(undefined)).toBe("unknown");
  });
});

describe("useAudioRecorder", () => {
  it("starts in idle and reports support", () => {
    installFakeMedia();
    const { result } = renderHook(() => useAudioRecorder());
    expect(result.current.status).toBe("idle");
    expect(result.current.isSupported).toBe(true);
    expect(result.current.canPause).toBe(true);
    expect(result.current.audio).toBeNull();
  });

  it("requests the microphone and starts recording", async () => {
    const media = installFakeMedia();
    const { result } = renderHook(() => useAudioRecorder());
    await startRecording(result);
    expect(media.getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(result.current.status).toBe("recording");
    expect(media.recorders()[0].state).toBe("recording");
    expect(media.recorders()[0].mimeType).toBe("audio/webm;codecs=opus");
  });

  it("tracks recording duration", async () => {
    installFakeMedia();
    const { result } = renderHook(() => useAudioRecorder());
    await startRecording(result);
    act(() => void vi.advanceTimersByTime(3000));
    expect(result.current.durationSeconds).toBeGreaterThanOrEqual(2.75);
    expect(result.current.durationSeconds).toBeLessThanOrEqual(3.25);
  });

  it("pauses (clock frozen) and resumes", async () => {
    const media = installFakeMedia();
    const { result } = renderHook(() => useAudioRecorder());
    await startRecording(result);
    act(() => void vi.advanceTimersByTime(2000));
    act(() => result.current.pause());
    expect(result.current.status).toBe("paused");
    expect(media.recorders()[0].state).toBe("paused");
    const frozen = result.current.durationSeconds;
    act(() => void vi.advanceTimersByTime(5000));
    expect(result.current.durationSeconds).toBe(frozen);
    act(() => result.current.resume());
    expect(result.current.status).toBe("recording");
    act(() => void vi.advanceTimersByTime(1000));
    expect(result.current.durationSeconds).toBeGreaterThan(frozen);
  });

  it("stop produces a playable audio blob and releases the microphone", async () => {
    const media = installFakeMedia();
    const { result } = renderHook(() => useAudioRecorder());
    await startRecording(result);
    act(() => void vi.advanceTimersByTime(2000));
    act(() => result.current.stop());
    expect(result.current.status).toBe("stopped");
    expect(result.current.audio?.blob.size).toBeGreaterThan(0);
    expect(result.current.audio?.mimeType).toBe("audio/webm;codecs=opus");
    expect(result.current.audio?.url).toBe("blob:fake-preview");
    expect(result.current.audio?.durationSeconds).toBeGreaterThanOrEqual(1.75);
    expect(media.tracks[0].stopped).toBe(true);
  });

  it("rejects an empty recording", async () => {
    installFakeMedia({ payload: "" });
    const { result } = renderHook(() => useAudioRecorder());
    await startRecording(result);
    act(() => void vi.advanceTimersByTime(2000));
    act(() => result.current.stop());
    expect(result.current.status).toBe("error");
    expect(result.current.error?.kind).toBe("empty");
    expect(result.current.audio).toBeNull();
  });

  it("rejects a recording that is too short", async () => {
    installFakeMedia();
    const { result } = renderHook(() => useAudioRecorder({ minDurationSeconds: 1 }));
    await startRecording(result);
    act(() => void vi.advanceTimersByTime(200));
    act(() => result.current.stop());
    expect(result.current.error?.kind).toBe("empty");
  });

  it("reports permission denied without creating a recorder", async () => {
    const media = installFakeMedia({ error: "NotAllowedError" });
    const { result } = renderHook(() => useAudioRecorder());
    await startRecording(result);
    expect(result.current.status).toBe("error");
    expect(result.current.error?.kind).toBe("permission-denied");
    expect(result.current.error?.message).toMatch(/blocked/i);
    expect(media.recorders()).toHaveLength(0);
  });

  it("reports a missing microphone", async () => {
    installFakeMedia({ error: "NotFoundError" });
    const { result } = renderHook(() => useAudioRecorder());
    await startRecording(result);
    expect(result.current.error?.kind).toBe("no-microphone");
  });

  it("does not ask for the microphone when the browser is unsupported", async () => {
    installNoMediaSupport();
    const { result } = renderHook(() => useAudioRecorder());
    expect(result.current.isSupported).toBe(false);
    await startRecording(result);
    expect(result.current.status).toBe("error");
    expect(result.current.error?.kind).toBe("unsupported");
  });

  it("handles the microphone being disconnected mid-recording", async () => {
    const media = installFakeMedia();
    const { result } = renderHook(() => useAudioRecorder());
    await startRecording(result);
    act(() => void vi.advanceTimersByTime(1500));
    act(() => media.tracks[0].onended?.());
    expect(result.current.status).toBe("error");
    expect(result.current.error?.kind).toBe("interrupted");
    expect(result.current.audio).toBeNull();
    expect(media.tracks[0].stopped).toBe(true);
  });

  it("handles a MediaRecorder error event", async () => {
    const media = installFakeMedia();
    const { result } = renderHook(() => useAudioRecorder());
    await startRecording(result);
    act(() => media.recorders()[0].onerror?.());
    expect(result.current.error?.kind).toBe("interrupted");
  });

  it("stops automatically at the maximum duration", async () => {
    installFakeMedia();
    const { result } = renderHook(() => useAudioRecorder({ maxDurationSeconds: 2 }));
    await startRecording(result);
    act(() => void vi.advanceTimersByTime(2600));
    expect(result.current.status).toBe("stopped");
    expect(result.current.audio).not.toBeNull();
  });

  it("reset discards the recording and revokes the preview URL", async () => {
    installFakeMedia();
    const { result } = renderHook(() => useAudioRecorder());
    await startRecording(result);
    act(() => void vi.advanceTimersByTime(2000));
    act(() => result.current.stop());
    act(() => result.current.reset());
    expect(result.current.status).toBe("idle");
    expect(result.current.audio).toBeNull();
    expect(result.current.durationSeconds).toBe(0);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:fake-preview");
  });

  it("ignores a second start while recording", async () => {
    const media = installFakeMedia();
    const { result } = renderHook(() => useAudioRecorder());
    await startRecording(result);
    await startRecording(result);
    expect(media.getUserMedia).toHaveBeenCalledTimes(1);
  });

  it("releases the microphone when the component unmounts", async () => {
    const media = installFakeMedia();
    const { result, unmount } = renderHook(() => useAudioRecorder());
    await startRecording(result);
    unmount();
    expect(media.tracks[0].stopped).toBe(true);
    expect(media.recorders()[0].state).toBe("inactive");
  });
});
