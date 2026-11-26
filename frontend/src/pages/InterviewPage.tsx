import { useCallback, useEffect, useRef, useState } from "react";
import { Alert } from "../components/Alert";
import { ProgressBar } from "../components/ProgressBar";
import { TranscriptionPanel } from "../components/TranscriptionPanel";
import { QuestionCard } from "../components/QuestionCard";
import { RecorderPanel } from "../components/RecorderPanel";
import { useAudioRecorder } from "../hooks/useAudioRecorder";
import { useElapsedSeconds } from "../hooks/useElapsedSeconds";
import { useTranscriptions } from "../hooks/useTranscriptions";
import { ApiError } from "../services/api";
import { config } from "../services/config";
import type { InterviewApi, SessionView } from "../types/interview";
import { formatDuration } from "../utils/format";

interface InterviewPageProps {
  api: InterviewApi;
  session: SessionView;
  onComplete: (answeredCount: number) => void;
}

type SubmitState = { phase: "idle" | "uploading" | "error"; progress: number; message?: string };
type FinishState = { phase: "idle" | "finishing" | "error"; message?: string };

export function InterviewPage({ api, session, onComplete }: InterviewPageProps) {
  const { questions } = session;
  const [answered, setAnswered] = useState<Set<string>>(() => new Set(session.answered_question_ids));
  const [index, setIndex] = useState(() => {
    const firstOpen = questions.findIndex((q) => !session.answered_question_ids.includes(q.id));
    return firstOpen === -1 ? questions.length - 1 : firstOpen;
  });
  const [submit, setSubmit] = useState<SubmitState>({ phase: "idle", progress: 0 });
  const [finish, setFinish] = useState<FinishState>({ phase: "idle" });
  const [notice, setNotice] = useState<string | null>(null);

  const question = questions[index];
  const limitSeconds = question.time_limit_seconds ?? config.defaultQuestionLimitSeconds;
  const recorder = useAudioRecorder({ maxDurationSeconds: limitSeconds });
  const { reset: resetRecorder } = recorder;

  const transcriptions = useTranscriptions(api, session.session_id, [...answered]);

  const submittingRef = useRef(false);
  const finishingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const elapsed = useElapsedSeconds(true);
  const totalLimit = session.interview.total_time_limit_seconds;
  const timeLeft = totalLimit !== null ? totalLimit - elapsed : null;
  const timeUp = timeLeft !== null && timeLeft <= 0;

  const isAnswered = answered.has(question.id);
  const allAnswered = questions.every((q) => answered.has(q.id));
  const unansweredCount = questions.filter((q) => !answered.has(q.id)).length;
  const uploading = submit.phase === "uploading";
  const hasUnsentPreview = recorder.audio !== null && !isAnswered;
  const navLocked = recorder.isBusy || uploading || hasUnsentPreview || finish.phase === "finishing";
  const isLast = index === questions.length - 1;

  // New question => fresh recorder and clean messages.
  useEffect(() => {
    resetRecorder();
    setSubmit({ phase: "idle", progress: 0 });
    setNotice(null);
  }, [question.id, resetRecorder]);

  // Cancel an in-flight upload if the page is closed.
  useEffect(() => () => abortRef.current?.abort(), []);

  // Warn before leaving with unsaved work.
  useEffect(() => {
    if (!(recorder.isBusy || uploading || hasUnsentPreview)) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [recorder.isBusy, uploading, hasUnsentPreview]);

  const markAnswered = useCallback((questionId: string) => {
    setAnswered((previous) => new Set(previous).add(questionId));
  }, []);

  async function handleSubmit() {
    if (submittingRef.current) return; // blocks double-clicks and double-taps
    const audio = recorder.audio;
    if (!audio || audio.blob.size === 0) {
      setSubmit({ phase: "error", progress: 0, message: "Please record an answer before submitting." });
      return;
    }

    submittingRef.current = true;
    const controller = new AbortController();
    abortRef.current = controller;
    setSubmit({ phase: "uploading", progress: 0 });
    try {
      await api.uploadResponse({
        sessionId: session.session_id,
        questionId: question.id,
        audio: audio.blob,
        durationSeconds: audio.durationSeconds,
        signal: controller.signal,
        onProgress: (fraction) => setSubmit((s) => (s.phase === "uploading" ? { ...s, progress: fraction } : s)),
      });
      markAnswered(question.id);
      setSubmit({ phase: "idle", progress: 0 });
      setNotice("Answer submitted successfully.");
      resetRecorder();
    } catch (error) {
      if (error instanceof ApiError && error.kind === "aborted") return;
      if (error instanceof ApiError && error.status === 409) {
        // The server may already have this answer (e.g. the first reply was lost). Ask it.
        try {
          const latest = await api.getSession(session.session_id);
          if (latest.answered_question_ids.includes(question.id)) {
            markAnswered(question.id);
            setSubmit({ phase: "idle", progress: 0 });
            setNotice("This question was already submitted earlier, so your first answer was kept.");
            resetRecorder();
            return;
          }
        } catch {
          /* fall through to the normal error below */
        }
      }
      setSubmit({
        phase: "error",
        progress: 0,
        message: error instanceof Error ? error.message : "The upload failed. Please try again.",
      });
    } finally {
      submittingRef.current = false;
      abortRef.current = null;
    }
  }

  async function handleFinish() {
    if (finishingRef.current || !allAnswered) return;
    finishingRef.current = true;
    setFinish({ phase: "finishing" });
    try {
      await api.completeSession(session.session_id);
      onComplete(questions.length);
    } catch (error) {
      setFinish({ phase: "error", message: error instanceof Error ? error.message : "Could not finish the interview." });
    } finally {
      finishingRef.current = false;
    }
  }

  const startDisabledReason = timeUp
    ? "Interview time is up. You can no longer start new recordings."
    : uploading
      ? "Please wait for the upload to finish."
      : undefined;

  return (
    <main className="page">
      <section className="card session-bar" aria-label="Interview session">
        <div>
          <strong className="session-title">{session.interview.title}</strong>
          <span className="hint">Session in progress</span>
        </div>
        <div className="timers">
          <span className="timer" aria-label={`Time elapsed ${formatDuration(elapsed)}`}>
            <span className="timer-label">Elapsed</span> {formatDuration(elapsed)}
          </span>
          {timeLeft !== null && (
            <span
              className={`timer ${timeLeft <= 60 ? "timer-warning" : ""}`}
              aria-label={`Time left ${formatDuration(timeLeft)}`}
            >
              <span className="timer-label">Left</span> {formatDuration(timeLeft)}
            </span>
          )}
        </div>
      </section>

      <ProgressBar current={index + 1} total={questions.length} answered={answered.size} />
      <QuestionCard question={question} number={index + 1} answered={isAnswered} />

      {timeUp && (
        <Alert tone="warning" title="Time is up">
          The interview time limit has passed. You can still submit a finished recording and complete the interview.
        </Alert>
      )}

      {notice && <Alert tone="success">{notice}</Alert>}

      {isAnswered ? (
        <>
          <section className="card submitted-card">
            <p>
              <strong>This answer has been submitted.</strong> It cannot be changed.
            </p>
          </section>
          <TranscriptionPanel
            transcription={transcriptions.byQuestion[question.id]}
            pollError={transcriptions.error}
            timedOut={transcriptions.timedOut}
            retrying={transcriptions.retryingId === transcriptions.byQuestion[question.id]?.response_id}
            onRetry={(responseId) => void transcriptions.retry(responseId)}
            onCheckAgain={transcriptions.checkAgain}
          />
        </>
      ) : (
        <>
          <RecorderPanel
            recorder={recorder}
            limitSeconds={limitSeconds}
            startDisabled={timeUp || uploading}
            disabledReason={startDisabledReason}
          />

          {recorder.audio && (
            <section className="card submit-card" aria-label="Submit answer">
              {submit.phase === "error" && (
                <Alert tone="error" title="Upload problem">
                  {submit.message}
                </Alert>
              )}
              {uploading && (
                <div className="upload-progress">
                  <label htmlFor="upload-progress">Uploading… {Math.round(submit.progress * 100)}%</label>
                  <progress id="upload-progress" value={submit.progress} max={1} />
                </div>
              )}
              <button
                type="button"
                className="btn btn-primary btn-large"
                onClick={() => void handleSubmit()}
                disabled={uploading}
              >
                {uploading ? "Uploading…" : submit.phase === "error" ? "Retry upload" : "Submit answer"}
              </button>
              <p className="hint">Not happy with it? Press “Record again” above before submitting.</p>
            </section>
          )}

          {!recorder.audio && submit.phase === "error" && <Alert tone="error">{submit.message}</Alert>}
        </>
      )}

      {hasUnsentPreview && <p className="hint">Submit this answer or choose “Record again” before moving to another question.</p>}

      {finish.phase === "error" && (
        <Alert tone="error" title="Could not finish">
          {finish.message}
        </Alert>
      )}

      <nav className="card nav-row" aria-label="Question navigation">
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => setIndex((i) => Math.max(0, i - 1))}
          disabled={index === 0 || navLocked}
        >
          Previous
        </button>

        {isLast ? (
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void handleFinish()}
            disabled={!allAnswered || navLocked}
          >
            {finish.phase === "finishing" ? "Finishing…" : "Finish interview"}
          </button>
        ) : (
          <button
            type="button"
            className={`btn ${isAnswered ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setIndex((i) => Math.min(questions.length - 1, i + 1))}
            disabled={navLocked}
          >
            Next
          </button>
        )}
      </nav>
      {isLast && !allAnswered && (
        <p className="hint nav-hint">
          {unansweredCount} question{unansweredCount === 1 ? "" : "s"} still unanswered. Use Previous to go back.
        </p>
      )}
    </main>
  );
}
