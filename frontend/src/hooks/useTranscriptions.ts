import { useCallback, useEffect, useMemo, useState } from "react";
import type { InterviewApi, Transcription } from "../types/interview";

const FIRST_POLL_MS = 800;
const POLL_STEPS_MS = [2000, 3000, 5000]; // slows down to every 5 s
const MAX_POLL_MS = 5 * 60 * 1000; // stop asking after 5 minutes; the user can ask again

const isFinished = (t: Transcription | undefined) => t?.status === "completed" || t?.status === "failed";

/**
 * Polls the backend for the transcription status of the answers given so far.
 * Polling runs only while at least one expected answer is not finished, and stops on unmount.
 */
export function useTranscriptions(api: InterviewApi, sessionId: string, answeredQuestionIds: string[]) {
  const [byQuestion, setByQuestion] = useState<Record<string, Transcription>>({});
  const [error, setError] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [restartKey, setRestartKey] = useState(0);

  const expectedKey = answeredQuestionIds.join("|");
  const needsPolling = useMemo(
    () => answeredQuestionIds.some((id) => !isFinished(byQuestion[id])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [expectedKey, byQuestion],
  );

  useEffect(() => {
    if (!needsPolling || timedOut) return;
    let cancelled = false;
    let timer: number | undefined;
    let step = 0;
    const startedAt = Date.now();

    const tick = async () => {
      try {
        const list = await api.listTranscriptions(sessionId);
        if (cancelled) return;
        setByQuestion(Object.fromEntries(list.map((item) => [item.question_id, item])));
        setError(null);
      } catch (caught) {
        if (cancelled) return;
        setError(caught instanceof Error ? caught.message : "Could not check the transcription status.");
      }
      if (cancelled) return;
      if (Date.now() - startedAt > MAX_POLL_MS) {
        setTimedOut(true);
        return;
      }
      timer = window.setTimeout(() => void tick(), POLL_STEPS_MS[Math.min(step++, POLL_STEPS_MS.length - 1)]);
    };

    timer = window.setTimeout(() => void tick(), FIRST_POLL_MS);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [needsPolling, timedOut, api, sessionId, restartKey]);

  const checkAgain = useCallback(() => {
    setTimedOut(false);
    setRestartKey((key) => key + 1);
  }, []);

  const retry = useCallback(
    async (responseId: string) => {
      setRetryingId(responseId);
      try {
        const updated = await api.retryTranscription(sessionId, responseId);
        setByQuestion((previous) => ({ ...previous, [updated.question_id]: updated }));
        setError(null);
        setTimedOut(false);
        setRestartKey((key) => key + 1);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not restart the transcription.");
      } finally {
        setRetryingId(null);
      }
    },
    [api, sessionId],
  );

  return { byQuestion, error, timedOut: timedOut && needsPolling, retryingId, retry, checkAgain };
}
