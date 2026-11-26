import type { ReactNode } from "react";

interface MetricCardProps { label: string; value: ReactNode; hint?: string }

export function MetricCard({ label, value, hint }: MetricCardProps) {
  return (
    <div className="metric-card">
      <dt className="metric-label">{label}</dt>
      <dd className="metric-value">{value}</dd>
      {hint && <dd className="metric-hint">{hint}</dd>}
    </div>
  );
}
