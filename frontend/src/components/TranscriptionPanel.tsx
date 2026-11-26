import type { Transcription } from "../types/interview";
import { formatDuration } from "../utils/format";
import { Alert } from "./Alert";

interface TranscriptionPanelProps {
  /** undefined = the server has not reported on this answer yet. */
  transcription: Transcription | undefined;
  pollError: string | null;
  timedOut: boolean;
  retrying: boolean;
  onRetry: (responseId: string) => void;
  onCheckAgain: () => void;
}

/** Providers whose text is NOT real speech recognition. */
const PLACEHOLDER_PROVIDERS = new Set(["mock", "demo"]);

export function TranscriptionPanel({
  transcription, pollError, timedOut, retrying, onRetry, onCheckAgain,
}: TranscriptionPanelProps) {
  const status = transcription?.status ?? "pending";

  return (
    <section className="card transcription" aria-labelledby="transcription-heading" aria-live="polite">
      <h3 id="transcription-heading">Transcription</h3>

      {status === "pending" && (
        <p className="transcription-state">
          <span className="spinner" aria-hidden="true" /> Answer received. Waiting in the queue to be transcribed…
        </p>
      )}

      {status === "processing" && (
        <p className="transcription-state">
          <span className="spinner" aria-hidden="true" /> Transcribing your answer…
        </p>
      )}

      {status === "completed" && transcription && (
        <>
          {transcription.no_speech_detected ? (
            <Alert tone="info" title="No speech detected">
              We could not hear any speech in this recording.
            </Alert>
          ) : (
            <blockquote className="transcript-text">{transcription.transcript}</blockquote>
          )}
          <p className="hint">
            {transcription.language && <>Language: {transcription.language} · </>}
            {transcription.duration_seconds !== null && <>Length: {formatDuration(transcription.duration_seconds)} · </>}
            Transcription complete
          </p>
          {transcription.provider && PLACEHOLDER_PROVIDERS.has(transcription.provider) && (
            <p className="badge badge-warning">Placeholder text: not real speech recognition ({transcription.provider} mode)</p>
          )}
        </>
      )}

      {status === "failed" && transcription && (
        <Alert
          tone="error"
          title="Transcription failed"
          action={
            transcription.can_retry ? (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => onRetry(transcription.response_id)}
                disabled={retrying}
              >
                {retrying ? "Retrying…" : "Try transcribing again"}
              </button>
            ) : undefined
          }
        >
          {transcription.error_message ?? "Something went wrong."}
          {!transcription.can_retry && " Your answer was saved; the hiring team can still review it."}
        </Alert>
      )}

      {pollError && status !== "completed" && status !== "failed" && (
        <p className="hint">Could not refresh the status ({pollError}). We will keep trying.</p>
      )}

      {timedOut && (
        <p className="hint">
          This is taking longer than expected.{" "}
          <button type="button" className="btn btn-secondary" onClick={onCheckAgain}>
            Check again
          </button>
        </p>
      )}
    </section>
  );
}
