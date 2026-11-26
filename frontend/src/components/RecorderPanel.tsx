import type { AudioRecorder } from "../hooks/useAudioRecorder";
import { formatBytes, formatDuration } from "../utils/format";
import { Alert } from "./Alert";

interface RecorderPanelProps {
  recorder: AudioRecorder;
  limitSeconds: number;
  /** Disable starting a new recording (time is up, or an upload is running). */
  startDisabled: boolean;
  disabledReason?: string;
}

const STATUS_TEXT: Record<AudioRecorder["status"], string> = {
  idle: "Ready to record",
  requesting: "Waiting for microphone permission…",
  recording: "Recording",
  paused: "Paused",
  stopping: "Finishing recording…",
  stopped: "Recording ready: listen, then submit or record again",
  error: "Recording problem",
};

export function RecorderPanel({ recorder, limitSeconds, startDisabled, disabledReason }: RecorderPanelProps) {
  const { status, error, audio, durationSeconds, isSupported, unsupportedReason, canPause } = recorder;
  const active = status === "recording" || status === "paused";
  const remaining = Math.max(0, limitSeconds - durationSeconds);

  return (
    <section className="card recorder" aria-labelledby="recorder-heading">
      <h3 id="recorder-heading" className="visually-hidden">
        Audio recorder
      </h3>

      <div className="recorder-status">
        <span className={`rec-dot rec-${status}`} aria-hidden="true" />
        <span className="recorder-status-text" role="status" aria-live="polite">
          {STATUS_TEXT[status]}
        </span>
      </div>

      <div className="recorder-time" aria-label="Recording time">
        <span className="recorder-clock">{formatDuration(durationSeconds)}</span>
        <span className="recorder-limit">
          / {formatDuration(limitSeconds)} max
          {active && <> · {formatDuration(remaining)} left</>}
        </span>
      </div>

      {!isSupported && unsupportedReason && (
        <Alert tone="error" title="Recording unavailable">
          {unsupportedReason === "insecure-context"
            ? "The microphone only works on secure pages (https:// or localhost). Open this page over HTTPS to record."
            : "Audio recording is not supported in this browser. Please use a recent version of Chrome, Edge, Firefox or Safari."}
        </Alert>
      )}

      {error && (
        <Alert tone="error" title="Could not record">
          {error.message}
        </Alert>
      )}

      {disabledReason && status === "idle" && <p className="hint">{disabledReason}</p>}

      {audio && (
        <div className="preview">
          {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
          <audio controls src={audio.url} aria-label="Preview of your recorded answer" />
          <p className="hint">
            {formatDuration(audio.durationSeconds)} · {formatBytes(audio.blob.size)}
          </p>
        </div>
      )}

      <div className="button-row">
        {(status === "idle" || status === "error" || status === "requesting") && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void recorder.start()}
            disabled={!isSupported || startDisabled || status === "requesting"}
          >
            {status === "error" ? "Try again" : "Start recording"}
          </button>
        )}

        {status === "recording" && (
          <>
            {canPause && (
              <button type="button" className="btn btn-secondary" onClick={recorder.pause}>
                Pause
              </button>
            )}
            <button type="button" className="btn btn-danger" onClick={recorder.stop}>
              Stop
            </button>
          </>
        )}

        {status === "paused" && (
          <>
            <button type="button" className="btn btn-secondary" onClick={recorder.resume}>
              Resume
            </button>
            <button type="button" className="btn btn-danger" onClick={recorder.stop}>
              Stop
            </button>
          </>
        )}

        {status === "stopped" && (
          <button type="button" className="btn btn-secondary" onClick={recorder.reset}>
            Record again
          </button>
        )}
      </div>
    </section>
  );
}
