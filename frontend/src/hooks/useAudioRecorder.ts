import { useCallback, useEffect, useRef, useState } from "react";

export type RecorderStatus = "idle" | "requesting" | "recording" | "paused" | "stopping" | "stopped" | "error";

export type RecorderErrorKind =
  | "unsupported"
  | "insecure-context"
  | "permission-denied"
  | "no-microphone"
  | "microphone-busy"
  | "interrupted"
  | "empty"
  | "unknown";

export interface RecorderError {
  kind: RecorderErrorKind;
  message: string;
}

export interface RecordedAudio {
  blob: Blob;
  /** Object URL for the <audio> preview. Revoked automatically on reset/unmount. */
  url: string;
  mimeType: string;
  durationSeconds: number;
}

export interface UseAudioRecorderOptions {
  /** Recording stops automatically at this length. */
  maxDurationSeconds?: number;
  /** Shorter recordings are rejected as "empty". */
  minDurationSeconds?: number;
}

export const RECORDER_MESSAGES: Record<RecorderErrorKind, string> = {
  unsupported:
    "Audio recording is not supported in this browser. Please use a recent version of Chrome, Edge, Firefox or Safari.",
  "insecure-context":
    "The microphone only works on secure pages (https:// or localhost). Open this page over HTTPS to record.",
  "permission-denied":
    "Microphone access was blocked. Allow the microphone in your browser's site settings, then try again.",
  "no-microphone": "No microphone was found. Connect a microphone and try again.",
  "microphone-busy": "The microphone could not be started. Close other apps that may be using it and try again.",
  interrupted: "The recording was interrupted (the microphone was disconnected or stopped). Please record again.",
  empty: "Nothing was recorded, or the recording was too short. Please speak into the microphone and try again.",
  unknown: "Something went wrong while recording. Please try again.",
};

const PREFERRED_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

/** Tells the UI, before any click, whether recording can work here. Never pretends. */
export function getRecorderSupport(): { supported: boolean; reason?: RecorderErrorKind } {
  if (typeof window === "undefined" || typeof navigator === "undefined") {
    return { supported: false, reason: "unsupported" };
  }
  // navigator.mediaDevices is missing on insecure pages, so check this first for a clearer message.
  if (window.isSecureContext === false) return { supported: false, reason: "insecure-context" };
  if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") {
    return { supported: false, reason: "unsupported" };
  }
  if (typeof MediaRecorder === "undefined") return { supported: false, reason: "unsupported" };
  return { supported: true };
}

export function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") return undefined;
  return PREFERRED_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
}

export function mapMediaError(error: unknown): RecorderErrorKind {
  const name =
    typeof error === "object" && error !== null && "name" in error ? String((error as { name: unknown }).name) : "";
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
    case "PermissionDeniedError":
      return "permission-denied";
    case "NotFoundError":
    case "DevicesNotFoundError":
    case "OverconstrainedError":
      return "no-microphone";
    case "NotSupportedError":
      return "unsupported";
    case "NotReadableError":
    case "TrackStartError":
    case "AbortError":
      return "microphone-busy";
    default:
      return "unknown";
  }
}

function pauseSupported(): boolean {
  return typeof MediaRecorder !== "undefined" && typeof MediaRecorder.prototype?.pause === "function";
}

export function useAudioRecorder(options: UseAudioRecorderOptions = {}) {
  const { maxDurationSeconds, minDurationSeconds = 0.5 } = options;

  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [error, setError] = useState<RecorderError | null>(null);
  const [durationSeconds, setDurationSeconds] = useState(0);
  const [audio, setAudio] = useState<RecordedAudio | null>(null);

  const statusRef = useRef<RecorderStatus>("idle");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const urlRef = useRef<string | null>(null);
  const timerRef = useRef<number | null>(null);
  const elapsedMsRef = useRef(0);
  const segmentStartRef = useRef<number | null>(null);
  const mountedRef = useRef(true);
  const maxRef = useRef(maxDurationSeconds);
  const minRef = useRef(minDurationSeconds);
  maxRef.current = maxDurationSeconds;
  minRef.current = minDurationSeconds;

  const changeStatus = useCallback((next: RecorderStatus) => {
    statusRef.current = next;
    setStatus(next);
  }, []);

  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };
  const releaseStream = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  };
  const revokeUrl = () => {
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
  };
  const currentElapsedMs = () =>
    elapsedMsRef.current + (segmentStartRef.current !== null ? Date.now() - segmentStartRef.current : 0);
  const freezeElapsed = () => {
    if (segmentStartRef.current !== null) {
      elapsedMsRef.current += Date.now() - segmentStartRef.current;
      segmentStartRef.current = null;
    }
  };

  /** Stop everything WITHOUT producing a recording (used by reset, errors and unmount). */
  const teardown = () => {
    clearTimer();
    const recorder = recorderRef.current;
    if (recorder) {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      recorder.onerror = null;
      if (recorder.state !== "inactive") {
        try {
          recorder.stop();
        } catch {
          /* already stopped */
        }
      }
    }
    recorderRef.current = null;
    releaseStream();
    chunksRef.current = [];
  };

  const fail = useCallback(
    (kind: RecorderErrorKind) => {
      if (!mountedRef.current) return;
      setError({ kind, message: RECORDER_MESSAGES[kind] });
      changeStatus("error");
    },
    [changeStatus],
  );

  const handleInterruption = () => {
    if (statusRef.current !== "recording" && statusRef.current !== "paused") return;
    teardown();
    fail("interrupted");
  };

  const finalize = (mimeType: string) => {
    clearTimer();
    releaseStream();
    recorderRef.current = null;
    if (!mountedRef.current) return;
    const blob = new Blob(chunksRef.current, { type: mimeType });
    chunksRef.current = [];
    const seconds = elapsedMsRef.current / 1000;
    if (blob.size === 0 || seconds < minRef.current) {
      fail("empty");
      return;
    }
    revokeUrl();
    const url = URL.createObjectURL(blob);
    urlRef.current = url;
    setDurationSeconds(seconds);
    setAudio({ blob, url, mimeType, durationSeconds: seconds });
    changeStatus("stopped");
  };

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder || (statusRef.current !== "recording" && statusRef.current !== "paused")) return;
    freezeElapsed();
    clearTimer();
    setDurationSeconds(elapsedMsRef.current / 1000);
    changeStatus("stopping");
    try {
      recorder.stop(); // the "stop" event then calls finalize()
    } catch {
      teardown();
      fail("unknown");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [changeStatus, fail]);

  const startTicker = () => {
    clearTimer();
    timerRef.current = window.setInterval(() => {
      const ms = currentElapsedMs();
      setDurationSeconds(ms / 1000);
      const max = maxRef.current;
      if (max !== undefined && ms >= max * 1000) stop();
    }, 250);
  };

  const start = useCallback(async () => {
    if (["requesting", "recording", "paused", "stopping"].includes(statusRef.current)) return;

    const support = getRecorderSupport();
    if (!support.supported) {
      fail(support.reason ?? "unsupported");
      return;
    }

    revokeUrl();
    setAudio(null);
    setError(null);
    setDurationSeconds(0);
    elapsedMsRef.current = 0;
    segmentStartRef.current = null;
    changeStatus("requesting");

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (caught) {
      fail(mapMediaError(caught));
      return;
    }
    if (!mountedRef.current) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    streamRef.current = stream;

    const mimeType = pickMimeType();
    let recorder: MediaRecorder;
    try {
      recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    } catch {
      releaseStream();
      fail("unsupported");
      return;
    }

    chunksRef.current = [];
    recorderRef.current = recorder;
    recorder.ondataavailable = (event: BlobEvent) => {
      if (event.data && event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onerror = () => handleInterruption();
    recorder.onstop = () => finalize(recorder.mimeType || mimeType || "audio/webm");
    stream.getAudioTracks().forEach((track) => {
      track.onended = () => handleInterruption();
    });

    try {
      recorder.start(1000); // deliver data every second so little is lost if something fails
    } catch {
      teardown();
      fail("unknown");
      return;
    }
    segmentStartRef.current = Date.now();
    changeStatus("recording");
    startTicker();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [changeStatus, fail, stop]);

  const pause = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder || statusRef.current !== "recording" || !pauseSupported()) return;
    try {
      recorder.pause();
    } catch {
      return;
    }
    freezeElapsed();
    clearTimer();
    setDurationSeconds(elapsedMsRef.current / 1000);
    changeStatus("paused");
  }, [changeStatus]);

  const resume = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder || statusRef.current !== "paused") return;
    try {
      recorder.resume();
    } catch {
      return;
    }
    segmentStartRef.current = Date.now();
    changeStatus("recording");
    startTicker();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [changeStatus]);

  /** Discard everything and return to idle (used for "Record again"). */
  const reset = useCallback(() => {
    teardown();
    revokeUrl();
    elapsedMsRef.current = 0;
    segmentStartRef.current = null;
    setAudio(null);
    setError(null);
    setDurationSeconds(0);
    changeStatus("idle");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [changeStatus]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      teardown();
      revokeUrl();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const support = getRecorderSupport();
  return {
    status,
    error,
    durationSeconds,
    audio,
    isSupported: support.supported,
    unsupportedReason: support.reason,
    canPause: pauseSupported(),
    isBusy: status === "requesting" || status === "recording" || status === "paused" || status === "stopping",
    start,
    pause,
    resume,
    stop,
    reset,
  };
}

export type AudioRecorder = ReturnType<typeof useAudioRecorder>;
