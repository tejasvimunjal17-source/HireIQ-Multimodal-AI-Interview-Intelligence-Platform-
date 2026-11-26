import type { DashboardSummary } from "../../types/dashboard";
import { formatScore } from "../../utils/dashboard";
import { MetricCard } from "./MetricCard";

export function DashboardOverview({ summary }: { summary: DashboardSummary }) {
  const peak = Math.max(1, ...summary.score_distribution.map((bucket) => bucket.count));
  return (
    <section className="card" aria-labelledby="overview-title">
      <h2 id="overview-title">Overview</h2>
      <dl className="metric-grid">
        <MetricCard label="Interview sessions" value={summary.total_sessions} hint="All sessions ever started" />
        <MetricCard label="Completed interviews" value={summary.completed_interviews} hint="Candidate has submitted" />
        <MetricCard label="Awaiting evaluation" value={summary.awaiting_evaluation} hint="Submitted or being evaluated" />
        <MetricCard label="Evaluated sessions" value={summary.evaluated_sessions} hint={summary.evaluation_failed ? `${summary.evaluation_failed} failed evaluation` : undefined} />
        <MetricCard
          label="Average score"
          value={summary.average_score === null ? "—" : formatScore(summary.average_score)}
          hint={summary.scored_sessions ? `Mean of ${summary.scored_sessions} scored session${summary.scored_sessions === 1 ? "" : "s"} (0-100)` : "No scored sessions yet"}
        />
      </dl>
      <div>
        <h3 className="subhead">Score distribution</h3>
        {summary.scored_sessions === 0 ? (
          <p className="hint">No scored sessions yet.</p>
        ) : (
          <ol className="distribution" aria-label="Number of scored sessions per score range">
            {summary.score_distribution.map((bucket) => (
              <li key={bucket.label} className="dist-col">
                <span className="dist-count">{bucket.count}</span>
                <span className="dist-bar" style={{ height: `${(bucket.count / peak) * 100}%`, minHeight: bucket.count > 0 ? 3 : 0 }} aria-hidden="true" />
                <span className="dist-label">{bucket.label}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
