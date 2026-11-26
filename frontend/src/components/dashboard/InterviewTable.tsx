import type { SessionRow } from "../../types/dashboard";
import { adviceSummary, candidateLabel, describeScoreSource, formatDate, statusLabel } from "../../utils/dashboard";
import { RecommendationBadge } from "./RecommendationBadge";
import { ScoreBar } from "./ScoreBar";

interface InterviewTableProps { rows: SessionRow[]; onOpen: (sessionId: string) => void }

export function InterviewTable({ rows, onOpen }: InterviewTableProps) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <caption className="visually-hidden">Interview sessions</caption>
        <thead>
          <tr>
            <th scope="col">Candidate</th>
            <th scope="col">Interview</th>
            <th scope="col">Date</th>
            <th scope="col">Status</th>
            <th scope="col">Score (0-100)</th>
            <th scope="col">Recommendation</th>
            <th scope="col"><span className="visually-hidden">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const name = candidateLabel(row);
            const advice = adviceSummary(row);
            return (
              <tr key={row.session_id}>
                <th scope="row" className="cell-name" data-label="Candidate" title={name}>{name}</th>
                <td data-label="Interview" className="cell-wrap">{row.interview_title}</td>
                <td data-label="Date">{formatDate(row.interview_date)}</td>
                <td data-label="Status">
                  <span className={`status-pill status-${row.status}`}>{statusLabel(row.status)}</span>
                  <span className="cell-sub">{row.evaluated_count} of {row.question_count} answers evaluated</span>
                </td>
                <td data-label="Score">
                  <ScoreBar value={row.overall_score} label={`Score of ${name}`} />
                  <span className="cell-sub">{describeScoreSource(row.score_source, row.evaluated_count)}</span>
                </td>
                <td data-label="Recommendation">
                  {row.recommendation ? <RecommendationBadge value={row.recommendation} /> : <span className="score-missing">Not recorded</span>}
                  {advice.length > 0 && (
                    <span className="cell-sub advice-line">
                      Answer advice: {advice.map((item) => <RecommendationBadge key={item.advice} value={item.advice} count={item.count} />)}
                    </span>
                  )}
                </td>
                <td data-label="">
                  <button type="button" className="btn btn-secondary btn-small" onClick={() => onOpen(row.session_id)} aria-label={`View evaluation of ${name}`}>View</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
