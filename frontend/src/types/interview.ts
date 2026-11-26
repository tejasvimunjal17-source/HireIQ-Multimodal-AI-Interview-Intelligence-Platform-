// These shapes mirror the FastAPI schemas in backend/app/schemas/interview.py.

export type QuestionType = "technical" | "behavioral";

export interface InterviewSummary {
  id: string;
  title: string;
  description: string | null;
  interview_type: string;
  question_count: number;
  total_time_limit_seconds: number | null;
}

export interface Question {
  id: string;
  position: number;
  text: string;
  question_type: QuestionType;
  time_limit_seconds: number | null;
}

export interface SessionView {
  session_id: string;
  status: string;
  interview: InterviewSummary;
  questions: Question[];
  answered_question_ids: string[];
}

export interface StartSessionInput {
  interview_id: string;
  candidate_name: string;
  candidate_email: string;
  consent: boolean;
}

export interface ResponseReceipt {
  response_id: string;
  question_id: string;
  transcription_status: "pending";
  size_bytes: number;
  content_type: string;
  /** Id of the queued transcription task. null if the queue was unavailable. */
  task_id: string | null;
}

export type TranscriptionState = "pending" | "processing" | "completed" | "failed";

/** Mirrors backend TranscriptionView. */
export interface Transcription {
  response_id: string;
  question_id: string;
  status: TranscriptionState;
  task_id: string | null;
  transcript: string | null;
  language: string | null;
  duration_seconds: number | null;
  provider: string | null;
  no_speech_detected: boolean;
  error_code: string | null;
  error_message: string | null;
  attempts: number;
  can_retry: boolean;
  completed_at: string | null;
}

export interface SessionComplete {
  session_id: string;
  status: string;
}

export interface UploadInput {
  sessionId: string;
  questionId: string;
  audio: Blob;
  durationSeconds: number;
  /** Called with a number between 0 and 1. */
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
}

/** Everything the UI needs from a backend. Real (HTTP) and demo implementations both satisfy it. */
export interface InterviewApi {
  listInterviews(): Promise<InterviewSummary[]>;
  startSession(input: StartSessionInput): Promise<SessionView>;
  getSession(sessionId: string): Promise<SessionView>;
  uploadResponse(input: UploadInput): Promise<ResponseReceipt>;
  completeSession(sessionId: string): Promise<SessionComplete>;
  listTranscriptions(sessionId: string): Promise<Transcription[]>;
  retryTranscription(sessionId: string, responseId: string): Promise<Transcription>;
}
