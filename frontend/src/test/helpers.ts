/**
 * Test doubles. EVERYTHING in this file is MOCKED browser behaviour:
 * FakeMediaRecorder/getUserMedia do not touch a real microphone, and FakeXHR sends nothing.
 */
import { vi } from "vitest";
import type {
  InterviewApi, InterviewSummary, ResponseReceipt, SessionView, StartSessionInput, Transcription, UploadInput,
} from "../types/interview";

// ---------------------------------------------------------------- MediaRecorder / microphone
export class FakeTrack {
  stopped = false;
  onended: (() => void) | null = null;
  stop() {
    this.stopped = true;
  }
}

export class FakeMediaRecorder {
  static instances: FakeMediaRecorder[] = [];
  static payload = "fake-audio-bytes";
  static isTypeSupported = (_type: string) => true;

  state: "inactive" | "recording" | "paused" = "inactive";
  mimeType: string;
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(
    public stream: unknown,
    options?: { mimeType?: string },
  ) {
    this.mimeType = options?.mimeType ?? "audio/webm";
    FakeMediaRecorder.instances.push(this);
  }
  start() {
    this.state = "recording";
  }
  pause() {
    this.state = "paused";
  }
  resume() {
    this.state = "recording";
  }
  stop() {
    if (this.state === "inactive") return;
    this.state = "inactive";
    const parts = FakeMediaRecorder.payload ? [FakeMediaRecorder.payload] : [];
    this.ondataavailable?.({ data: new Blob(parts, { type: this.mimeType }) });
    this.onstop?.();
  }
}

export interface FakeMediaOptions {
  /** DOMException name that getUserMedia should reject with, e.g. "NotAllowedError". */
  error?: string;
  secure?: boolean;
  /** Bytes the fake recorder "captures". Empty string simulates an empty recording. */
  payload?: string;
}

export function installFakeMedia(options: FakeMediaOptions = {}) {
  FakeMediaRecorder.instances = [];
  FakeMediaRecorder.payload = options.payload ?? "fake-audio-bytes";
  const tracks: FakeTrack[] = [];
  const getUserMedia = vi.fn(async (_constraints?: unknown) => {
    if (options.error) throw Object.assign(new Error(options.error), { name: options.error });
    const track = new FakeTrack();
    tracks.push(track);
    return { getTracks: () => [track], getAudioTracks: () => [track] } as unknown as MediaStream;
  });
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true });
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  Object.defineProperty(window, "isSecureContext", { value: options.secure ?? true, configurable: true });
  URL.createObjectURL = vi.fn(() => "blob:fake-preview");
  URL.revokeObjectURL = vi.fn();
  return { getUserMedia, tracks, recorders: () => FakeMediaRecorder.instances };
}

/** Simulates a browser with no MediaRecorder and no microphone API. */
export function installNoMediaSupport() {
  Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true });
  vi.stubGlobal("MediaRecorder", undefined);
  Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
}

// ---------------------------------------------------------------- XMLHttpRequest
export class FakeXHR {
  static instances: FakeXHR[] = [];
  method = "";
  url = "";
  timeout = 0;
  headers: Record<string, string> = {};
  body: FormData | null = null;
  status = 0;
  responseText = "";
  aborted = false;
  upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  onabort: (() => void) | null = null;

  constructor() {
    FakeXHR.instances.push(this);
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  send(body: FormData) {
    this.body = body;
  }
  abort() {
    this.aborted = true;
    this.onabort?.();
  }
  // helpers used by tests to play the server's part
  respond(status: number, json: unknown) {
    this.status = status;
    this.responseText = JSON.stringify(json);
    this.onload?.();
  }
  progress(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total } as ProgressEvent);
  }
}

export function installFakeXhr() {
  FakeXHR.instances = [];
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  return FakeXHR;
}

// ---------------------------------------------------------------- sample data + fake API
export const INTERVIEW: InterviewSummary = {
  id: "int-1",
  title: "Backend Engineer Interview",
  description: "Two short questions.",
  interview_type: "mixed",
  question_count: 2,
  total_time_limit_seconds: 600,
};

export function makeSession(overrides: Partial<SessionView> = {}): SessionView {
  return {
    session_id: "sess-1",
    status: "created",
    interview: INTERVIEW,
    questions: [
      { id: "q1", position: 1, question_type: "technical", time_limit_seconds: 60, text: "Explain what an index does in a database." },
      { id: "q2", position: 2, question_type: "behavioral", time_limit_seconds: 60, text: "Describe a time you fixed a difficult bug." },
    ],
    answered_question_ids: [],
    ...overrides,
  };
}

export function createFakeApi(overrides: Partial<InterviewApi> = {}) {
  return {
    listInterviews: vi.fn(async () => [INTERVIEW]),
    startSession: vi.fn(async (_input: StartSessionInput) => makeSession()),
    getSession: vi.fn(async (_id: string) => makeSession()),
    uploadResponse: vi.fn(
      async (input: UploadInput): Promise<ResponseReceipt> => ({
        response_id: `resp-${input.questionId}`,
        question_id: input.questionId,
        transcription_status: "pending",
        size_bytes: input.audio.size,
        content_type: input.audio.type,
        task_id: `task-${input.questionId}`,
      }),
    ),
    listTranscriptions: vi.fn(async (_sessionId: string): Promise<Transcription[]> => []),
    retryTranscription: vi.fn(async (_sessionId: string, responseId: string): Promise<Transcription> =>
      makeTranscription({ response_id: responseId, status: "pending" })),
    completeSession: vi.fn(async (id: string) => ({ session_id: id, status: "submitted" })),
    ...overrides,
  };
}

export function makeTranscription(overrides: Partial<Transcription> = {}): Transcription {
  return {
    response_id: "resp-q1", question_id: "q1", status: "pending", task_id: "task-1", transcript: null,
    language: null, duration_seconds: null, provider: null, no_speech_detected: false, error_code: null,
    error_message: null, attempts: 0, can_retry: false, completed_at: null, ...overrides,
  };
}
