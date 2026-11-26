import { useState } from "react";
import { Alert } from "../Alert";

interface TokenGateProps { onSubmit: (token: string) => void; error?: string | null }

/**
 * The API has no user accounts yet, so the dashboard API is protected by a shared access token that the manager types
 * in. It is kept in memory only (lost on refresh), never written to storage, and is not part of the built code.
 */
export function TokenGate({ onSubmit, error }: TokenGateProps) {
  const [value, setValue] = useState("");
  return (
    <section className="card" aria-labelledby="gate-title">
      <h2 id="gate-title">Hiring manager access</h2>
      <p className="lead">Enter the access token configured on the server (<code>REPORT_ACCESS_TOKEN</code>) to view interview evaluations.</p>
      {error && <Alert tone="error">{error}</Alert>}
      <form className="form" onSubmit={(e) => { e.preventDefault(); if (value.trim()) onSubmit(value.trim()); }}>
        <div className="field">
          <label htmlFor="access-token">Access token</label>
          <input id="access-token" type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} />
          <span className="hint">Kept in memory for this tab only. It is never stored or logged.</span>
        </div>
        <button type="submit" className="btn btn-primary" disabled={!value.trim()}>Open dashboard</button>
      </form>
      <p className="hint">Shared-token access is a temporary measure: there is no per-user login yet, so this is not production-grade authentication.</p>
    </section>
  );
}
