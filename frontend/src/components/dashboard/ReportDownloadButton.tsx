import { useState } from "react";
import type { DashboardApi } from "../../types/dashboard";
import { saveBlob as defaultSave } from "../../utils/dashboard";
import { Alert } from "../Alert";

interface Props {
  api: Pick<DashboardApi, "downloadReport">;
  sessionId: string;
  onSave?: (blob: Blob, filename: string) => void;
  disabledReason?: string;
}

/** Asks the existing backend endpoint for the PDF; no PDF logic lives in the browser. */
export function ReportDownloadButton({ api, sessionId, onSave = defaultSave, disabledReason }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function download() {
    setBusy(true);
    setError(null);
    try {
      onSave(await api.downloadReport(sessionId), `hireiq-evaluation-${sessionId}.pdf`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The report could not be downloaded.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="report-download">
      <button type="button" className="btn btn-primary" onClick={download} disabled={busy || Boolean(disabledReason)} aria-busy={busy}>
        {busy ? "Preparing PDF…" : "Download PDF report"}
      </button>
      {disabledReason && <p className="hint">{disabledReason}</p>}
      {error && <Alert tone="error" title="Download failed">{error}</Alert>}
    </div>
  );
}
