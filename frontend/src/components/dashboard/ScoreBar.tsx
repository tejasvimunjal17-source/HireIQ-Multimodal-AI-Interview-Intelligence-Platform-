import { formatScore, scalePercent } from "../../utils/dashboard";

interface ScoreBarProps { value: number | null; min?: number; max?: number; label: string }

/** A bar for one stored score. A missing score renders as text, never as an empty (zero) bar. */
export function ScoreBar({ value, min = 0, max = 100, label }: ScoreBarProps) {
  if (value === null) return <span className="score-missing">Not scored</span>;
  const percent = scalePercent(value, min, max);
  return (
    <span className="score-bar" role="img" aria-label={`${label}: ${formatScore(value)} on a ${min} to ${max} scale`}>
      <span className="score-bar-track"><span className="score-bar-fill" style={{ width: `${percent}%` }} /></span>
      <span className="score-bar-value">{formatScore(value)}</span>
    </span>
  );
}
