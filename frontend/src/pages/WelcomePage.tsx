import { type ChangeEvent, type FormEvent, useCallback, useEffect, useState } from "react";
import { Alert } from "../components/Alert";
import { getRecorderSupport } from "../hooks/useAudioRecorder";
import type { InterviewApi, InterviewSummary, SessionView } from "../types/interview";

interface WelcomePageProps {
  api: InterviewApi;
  onStarted: (session: SessionView) => void;
}

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

interface FieldErrors {
  interview?: string;
  name?: string;
  email?: string;
  consent?: string;
}

export function WelcomePage({ api, onStarted }: WelcomePageProps) {
  const [interviews, setInterviews] = useState<InterviewSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const support = getRecorderSupport();

  const loadInterviews = useCallback(async () => {
    setLoadError(null);
    setInterviews(null);
    try {
      const list = await api.listInterviews();
      setInterviews(list);
      if (list.length === 1) setSelectedId(list[0].id);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not load interviews.");
    }
  }, [api]);

  useEffect(() => {
    void loadInterviews();
  }, [loadInterviews]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (starting) return;

    const next: FieldErrors = {};
    if (!selectedId) next.interview = "Please choose an interview.";
    if (!name.trim()) next.name = "Please enter your full name.";
    if (!EMAIL_PATTERN.test(email.trim())) next.email = "Please enter a valid email address.";
    if (!consent) next.consent = "You need to agree before the interview can start.";
    setErrors(next);
    if (Object.keys(next).length > 0) return;

    setStarting(true);
    setStartError(null);
    try {
      const session = await api.startSession({
        interview_id: selectedId,
        candidate_name: name.trim(),
        candidate_email: email.trim(),
        consent: true,
      });
      onStarted(session);
    } catch (error) {
      setStartError(error instanceof Error ? error.message : "Could not start the interview.");
      setStarting(false);
    }
  }

  const selected = interviews?.find((item) => item.id === selectedId);

  return (
    <main className="page">
      <section className="card hero">
        <h1>Welcome to your AI-assisted interview</h1>
        <p className="lead">
          You will answer a short set of questions by speaking. Your answers are recorded as audio and
          reviewed with AI assistance; people on the hiring team make the final decisions.
        </p>
      </section>

      <section className="card" aria-labelledby="instructions-heading">
        <h2 id="instructions-heading">Before you begin</h2>
        <ol className="instructions">
          <li>Find a quiet place and check that your microphone works.</li>
          <li>When your browser asks, allow microphone access.</li>
          <li>
            For each question: press <strong>Start recording</strong>, speak your answer, press{" "}
            <strong>Stop</strong>, then listen to it.
          </li>
          <li>
            Happy with it? Press <strong>Submit answer</strong>. Want another go? Press{" "}
            <strong>Record again</strong>.
          </li>
          <li>Each question has a time limit. Recording stops by itself when time runs out.</li>
          <li>You can only submit one answer per question, so check your preview first.</li>
        </ol>
      </section>

      {!support.supported && (
        <Alert tone="warning" title="This browser cannot record audio">
          {support.reason === "insecure-context"
            ? "The microphone only works on secure pages (https:// or localhost). Please open this page over HTTPS."
            : "Please use a recent version of Chrome, Edge, Firefox or Safari to take this interview."}
        </Alert>
      )}

      <section className="card" aria-labelledby="details-heading">
        <h2 id="details-heading">Your details</h2>

        {loadError && (
          <Alert
            tone="error"
            title="Could not load interviews"
            action={
              <button type="button" className="btn btn-secondary" onClick={() => void loadInterviews()}>
                Retry
              </button>
            }
          >
            {loadError}
          </Alert>
        )}
        {interviews === null && !loadError && <p className="hint">Loading available interviews…</p>}
        {interviews !== null && interviews.length === 0 && (
          <Alert tone="info">No interviews are available right now. Please contact the hiring team.</Alert>
        )}

        {interviews !== null && interviews.length > 0 && (
          <form onSubmit={(event: FormEvent) => void handleSubmit(event)} noValidate className="form">
            <fieldset className="field" aria-describedby={errors.interview ? "interview-error" : undefined}>
              <legend>Interview</legend>
              {interviews.map((item) => (
                <label key={item.id} className="radio">
                  <input
                    type="radio"
                    name="interview"
                    value={item.id}
                    checked={selectedId === item.id}
                    onChange={() => setSelectedId(item.id)}
                  />
                  <span>
                    <strong>{item.title}</strong>
                    <span className="hint">
                      {item.question_count} questions
                      {item.total_time_limit_seconds ? ` · about ${Math.max(1, Math.round(item.total_time_limit_seconds / 60))} minutes` : ""}
                    </span>
                  </span>
                </label>
              ))}
              {errors.interview && (
                <p id="interview-error" className="field-error">
                  {errors.interview}
                </p>
              )}
            </fieldset>

            {selected?.description && <p className="hint">{selected.description}</p>}

            <div className="field">
              <label htmlFor="candidate-name">Full name</label>
              <input
                id="candidate-name"
                type="text"
                autoComplete="name"
                value={name}
                onChange={(event: ChangeEvent<HTMLInputElement>) => setName(event.target.value)}
                aria-invalid={Boolean(errors.name)}
                aria-describedby={errors.name ? "name-error" : undefined}
              />
              {errors.name && (
                <p id="name-error" className="field-error">
                  {errors.name}
                </p>
              )}
            </div>

            <div className="field">
              <label htmlFor="candidate-email">Email address</label>
              <input
                id="candidate-email"
                type="email"
                autoComplete="email"
                inputMode="email"
                value={email}
                onChange={(event: ChangeEvent<HTMLInputElement>) => setEmail(event.target.value)}
                aria-invalid={Boolean(errors.email)}
                aria-describedby={errors.email ? "email-error" : undefined}
              />
              {errors.email && (
                <p id="email-error" className="field-error">
                  {errors.email}
                </p>
              )}
            </div>

            <div className="field">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(event: ChangeEvent<HTMLInputElement>) => setConsent(event.target.checked)}
                  aria-describedby={errors.consent ? "consent-error" : undefined}
                />
                <span>
                  I agree that my name, email and recorded audio answers are processed for this interview. Audio is
                  kept only temporarily, not permanently.
                </span>
              </label>
              {errors.consent && (
                <p id="consent-error" className="field-error">
                  {errors.consent}
                </p>
              )}
            </div>

            {startError && <Alert tone="error" title="Could not start">{startError}</Alert>}

            <button type="submit" className="btn btn-primary btn-large" disabled={starting}>
              {starting ? "Starting…" : "Start interview"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
