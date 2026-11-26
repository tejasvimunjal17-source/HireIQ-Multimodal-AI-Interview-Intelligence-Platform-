import type {
  InterviewApi, InterviewSummary, ResponseReceipt, SessionComplete, SessionView,
  StartSessionInput, Transcription, UploadInput,
} from "../types/interview";
import { config } from "./config";

export type ApiErrorKind = "network" | "timeout" | "http" | "aborted";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;

  constructor(kind: ApiErrorKind, message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
  }
}

const NETWORK_MESSAGE = "Cannot reach the server. Check your internet connection and try again.";
const TIMEOUT_MESSAGE = "The server took too long to respond. Please try again.";

/** FastAPI errors look like {detail: "text"} or {detail: [{msg: "..."}, ...]}. */
function extractDetail(body: unknown): string | undefined {
  if (!body || typeof body !== "object" || !("detail" in body)) return undefined;
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item && typeof item === "object" && "msg" in item ? String((item as { msg: unknown }).msg) : ""))
      .filter(Boolean);
    return messages.length ? messages.join("; ") : undefined;
  }
  return undefined;
}

export function httpErrorMessage(status: number, detail?: string): string {
  switch (status) {
    case 413:
      return "The recording is too large to upload. Please record a shorter answer.";
    case 415:
      return "This audio format is not supported by the server.";
    case 409:
      return detail ?? "This action conflicts with the current state of the interview.";
    case 404:
      return detail ?? "The interview or question could not be found.";
    case 422:
      return detail ? `Please check your input: ${detail}` : "Please check your input and try again.";
    default:
      return status >= 500
        ? "The server had a problem. Please try again in a moment."
        : (detail ?? `The request failed (status ${status}).`);
  }
}

function parseJson(text: string): unknown {
  try {
    return text ? JSON.parse(text) : undefined;
  } catch {
    return undefined;
  }
}

export function createHttpApi(baseUrl: string = config.apiBaseUrl): InterviewApi {
  async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), config.requestTimeoutMs);
    let response: Response;
    try {
      response = await fetch(`${baseUrl}${path}`, {
        ...init,
        headers: { Accept: "application/json", ...(init.headers ?? {}) },
        signal: controller.signal,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new ApiError("timeout", TIMEOUT_MESSAGE);
      }
      throw new ApiError("network", NETWORK_MESSAGE);
    } finally {
      clearTimeout(timer);
    }

    const body = parseJson(await response.text());
    if (!response.ok) {
      throw new ApiError("http", httpErrorMessage(response.status, extractDetail(body)), response.status);
    }
    return body as T;
  }

  const postJson = <T>(path: string, payload: unknown) =>
    requestJson<T>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

  return {
    listInterviews: () => requestJson<InterviewSummary[]>("/api/interviews"),
    startSession: (input: StartSessionInput) => postJson<SessionView>("/api/sessions", input),
    getSession: (sessionId: string) => requestJson<SessionView>(`/api/sessions/${encodeURIComponent(sessionId)}`),
    completeSession: (sessionId: string) =>
      requestJson<SessionComplete>(`/api/sessions/${encodeURIComponent(sessionId)}/complete`, { method: "POST" }),
    uploadResponse: (input: UploadInput) => uploadWithProgress(baseUrl, input),
    listTranscriptions: (sessionId: string) =>
      requestJson<Transcription[]>(`/api/sessions/${encodeURIComponent(sessionId)}/transcriptions`),
    retryTranscription: (sessionId: string, responseId: string) =>
      requestJson<Transcription>(
        `/api/sessions/${encodeURIComponent(sessionId)}/responses/${encodeURIComponent(responseId)}/transcription/retry`,
        { method: "POST" },
      ),
  };
}

/** Pick a file extension for the multipart filename. The server ignores it (it sniffs the content). */
export function extensionFor(mimeType: string): string {
  const type = mimeType.split(";")[0].trim().toLowerCase();
  if (type.includes("webm")) return "webm";
  if (type.includes("ogg")) return "ogg";
  if (type.includes("mp4") || type.includes("m4a")) return "mp4";
  if (type.includes("mpeg")) return "mp3";
  if (type.includes("wav")) return "wav";
  return "bin";
}

/** fetch() cannot report upload progress, so audio uploads use XMLHttpRequest. */
function uploadWithProgress(baseUrl: string, input: UploadInput): Promise<ResponseReceipt> {
  return new Promise<ResponseReceipt>((resolve, reject) => {
    const form = new FormData();
    form.append("question_id", input.questionId);
    form.append("duration_seconds", String(Math.round(input.durationSeconds * 10) / 10));
    form.append("audio", input.audio, `answer.${extensionFor(input.audio.type)}`);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${baseUrl}/api/sessions/${encodeURIComponent(input.sessionId)}/responses`);
    xhr.timeout = config.uploadTimeoutMs;
    xhr.setRequestHeader("Accept", "application/json");

    xhr.upload.onprogress = (event: ProgressEvent) => {
      if (event.lengthComputable && event.total > 0) {
        input.onProgress?.(Math.min(1, event.loaded / event.total));
      }
    };
    xhr.onload = () => {
      const body = parseJson(xhr.responseText);
      if (xhr.status >= 200 && xhr.status < 300) {
        input.onProgress?.(1);
        resolve(body as ResponseReceipt);
      } else {
        reject(new ApiError("http", httpErrorMessage(xhr.status, extractDetail(body)), xhr.status));
      }
    };
    xhr.onerror = () => reject(new ApiError("network", NETWORK_MESSAGE));
    xhr.ontimeout = () => reject(new ApiError("timeout", "The upload took too long. Check your connection and try again."));
    xhr.onabort = () => reject(new ApiError("aborted", "The upload was cancelled."));

    input.signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(form);
  });
}
