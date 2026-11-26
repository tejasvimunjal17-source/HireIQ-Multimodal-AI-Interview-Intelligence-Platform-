import { useEffect, useState } from "react";
import { BrandHeader } from "./components/BrandHeader";
import { DemoBanner } from "./components/DemoBanner";
import { CompletePage } from "./pages/CompletePage";
import { InterviewPage } from "./pages/InterviewPage";
import { WelcomePage } from "./pages/WelcomePage";
import { config } from "./services/config";
import { api as defaultApi } from "./services";
import type { InterviewApi, SessionView } from "./types/interview";
import { clearSessionId, loadSessionId, saveSessionId } from "./utils/storage";

type Stage =
  | { name: "resuming" }
  | { name: "welcome" }
  | { name: "interview"; session: SessionView }
  | { name: "complete"; answeredCount?: number };

const FINISHED_STATUSES = new Set(["submitted", "processing", "evaluated", "failed"]);

interface AppProps {
  api?: InterviewApi;
  demoMode?: boolean;
}

export default function App({ api = defaultApi, demoMode = config.demoMode }: AppProps) {
  const [stage, setStage] = useState<Stage>(() => (loadSessionId() ? { name: "resuming" } : { name: "welcome" }));

  // After a page refresh, continue the session that is still open on the server.
  useEffect(() => {
    const savedId = loadSessionId();
    if (!savedId) return;
    let cancelled = false;
    api
      .getSession(savedId)
      .then((session) => {
        if (cancelled) return;
        if (FINISHED_STATUSES.has(session.status)) {
          clearSessionId();
          setStage({ name: "complete" });
        } else {
          setStage({ name: "interview", session });
        }
      })
      .catch(() => {
        if (cancelled) return;
        clearSessionId();
        setStage({ name: "welcome" });
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  return (
    <>
      {demoMode && <DemoBanner />}
      <BrandHeader />
      {stage.name === "resuming" && (
        <main className="page">
          <p className="hint" role="status">
            Restoring your interview…
          </p>
        </main>
      )}
      {stage.name === "welcome" && (
        <WelcomePage
          api={api}
          onStarted={(session) => {
            saveSessionId(session.session_id);
            setStage({ name: "interview", session });
          }}
        />
      )}
      {stage.name === "interview" && (
        <InterviewPage
          api={api}
          session={stage.session}
          onComplete={(answeredCount) => {
            clearSessionId();
            setStage({ name: "complete", answeredCount });
          }}
        />
      )}
      {stage.name === "complete" && <CompletePage answeredCount={stage.answeredCount} />}
    </>
  );
}
