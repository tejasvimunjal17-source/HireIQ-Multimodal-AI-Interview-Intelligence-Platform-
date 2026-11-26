import { formatScore, humanizeKey, scalePercent } from "../../utils/dashboard";

interface CriteriaChartProps {
  points: { key: string; value: number; answers: number }[];
  scaleMin: number | null;
  scaleMax: number | null;
  unavailableReason?: string;
  answersTotal?: number;
}

/** Criterion-wise horizontal bars of STORED scores (mean over the evaluated answers that contain the criterion). */
export function CriteriaChart({ points, scaleMin, scaleMax, unavailableReason, answersTotal }: CriteriaChartProps) {
  if (points.length === 0 || scaleMin === null || scaleMax === null) {
    return <p className="hint">{unavailableReason || "No criterion scores are available for this session."}</p>;
  }
  return (
    <figure className="criteria-chart">
      <figcaption className="hint">
        Mean stored score per criterion, scale {scaleMin}–{scaleMax}. Criteria that appear in only some answers are marked; nothing is estimated.
      </figcaption>
      <ul className="criteria-list">
        {points.map((p) => (
          <li key={p.key}>
            <span className="criteria-name">{humanizeKey(p.key)}</span>
            <span className="score-bar" role="img" aria-label={`${humanizeKey(p.key)}: ${formatScore(p.value)} on a ${scaleMin} to ${scaleMax} scale`}>
              <span className="score-bar-track"><span className="score-bar-fill" style={{ width: `${scalePercent(p.value, scaleMin, scaleMax)}%` }} /></span>
              <span className="score-bar-value">{formatScore(p.value)}</span>
            </span>
            {answersTotal !== undefined && p.answers < answersTotal && <span className="cell-sub">{p.answers} of {answersTotal} answers</span>}
          </li>
        ))}
      </ul>
    </figure>
  );
}
