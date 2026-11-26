/**
 * DEMO MODE ONLY (VITE_DEMO_MODE=true).
 * Sample interview data held in memory. NOTHING is sent to any server and NOTHING is stored:
 * answers submitted here are not real. The UI shows a banner whenever this is active.
 */
import type {
  InterviewApi, InterviewSummary, Question, ResponseReceipt, SessionView, Transcription, UploadInput,
} from "../types/interview";

const INTERVIEW: InterviewSummary = {
  id: "demo-interview",
  title: "Demo interview (sample data)",
  description: "Preview of the interview screens. Nothing you record here is sent anywhere.",
  interview_type: "mixed",
  question_count: 3,
  total_time_limit_seconds: 600,
};

const QUESTIONS: Question[] = [
  { id: "demo-q1", position: 1, question_type: "technical", time_limit_seconds: 90,
    text: "Explain the difference between a process and a thread." },
  { id: "demo-q2", position: 2, question_type: "technical", time_limit_seconds: 90,
    text: "How would you make a slow database query faster?" },
  { id: "demo-q3", position: 3, question_type: "behavioral", time_limit_seconds: 90,
    text: "Tell us about a time you disagreed with a teammate and how you handled it." },
];

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export function createDemoApi(): InterviewApi {
  const answered = new Set<string>();
  const uploadedAt = new Map<string, number>();
  let status = "created";

  const view = (): SessionView => ({
    session_id: "demo-session",
    status,
    interview: INTERVIEW,
    questions: QUESTIONS,
    answered_question_ids: [...answered],
  });

  return {
    listInterviews: async () => [INTERVIEW],
    startSession: async () => view(),
    getSession: async () => view(),
    uploadResponse: async (input: UploadInput): Promise<ResponseReceipt> => {
      for (const step of [0.3, 0.7, 1]) {
        await wait(150);
        input.onProgress?.(step);
      }
      answered.add(input.questionId);
      uploadedAt.set(input.questionId, Date.now());
      status = "in_progress";
      return {
        response_id: `demo-response-${answered.size}`,
        question_id: input.questionId,
        transcription_status: "pending",
        size_bytes: input.audio.size,
        content_type: input.audio.type,
        task_id: `demo-task-${answered.size}`,
      };
    },
    // Simulated progress: queued -> processing -> done. The text is a fixed sample, NOT a transcription.
    listTranscriptions: async (): Promise<Transcription[]> =>
      [...uploadedAt].map(([questionId, at]) => {
        const age = Date.now() - at;
        const done = age > 3500;
        return {
          response_id: `demo-response-${questionId}`,
          question_id: questionId,
          status: done ? "completed" : age > 1500 ? "processing" : "pending",
          task_id: `demo-task-${questionId}`,
          transcript: done ? "[DEMO] Sample text. Nothing was actually transcribed." : null,
          language: done ? "en" : null,
          duration_seconds: done ? 5 : null,
          provider: done ? "demo" : null,
          no_speech_detected: false,
          error_code: null,
          error_message: null,
          attempts: 1,
          can_retry: false,
          completed_at: done ? new Date().toISOString() : null,
        };
      }),
    retryTranscription: async () => {
      throw new Error("Retry is not available in demo mode.");
    },
    completeSession: async () => {
      status = "submitted";
      return { session_id: "demo-session", status };
    },
  };
}
