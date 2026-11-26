import type { AnswerView, DashboardApi, SessionDetail } from "../../types/dashboard";
import { candidateLabel, describeScoreSource, formatDate, formatScore, humanizeKey, statusLabel } from "../../utils/dashboard";
import { CriteriaChart } from "./CriteriaChart";
import { RecommendationBadge } from "./RecommendationBadge";
import { ReportDownloadButton } from "./ReportDownloadButton";
import { ScoreBar } from "./ScoreBar";

interface Props {
  detail: SessionDetail;
  api: Pick<DashboardApi, "downloadReport">;
  onBack: () => void;
  onSave?: (blob: Blob, filename: string) => void;
}

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h5 className="subhead">{title}</h5>
      <ul className="plain-list">{items.map((item, i) => <li key={i}>{item}</li>)}</ul>
    </div>
  );
}

/** Experimental, advisory only: the wording is fixed and these values never feed the recommendation. */
function NlpBlock({ nlp }: { nlp: NonNullable<AnswerView["nlp"]> }) {
  return (
    <div className="nlp-box">
      <h5 className="subhead">NLP insights <span className="badge badge-warning">Experimental · advisory</span></h5>
      <p className="hint">Rule-based text signals. They are not validated measures of competence, personality or honesty and play no part in the score or recommendation.</p>
      {nlp.keywords && nlp.keywords.length > 0 && <p><strong>Keywords:</strong> {nlp.keywords.map((k) => k.text).join(", ")}</p>}
      {nlp.entities && nlp.entities.length > 0 && <p><strong>Entities:</strong> {nlp.entities.map((e) => `${e.text} (${e.label})`).join(", ")}</p>}
      {nlp.sentiment && <p><strong>Sentiment (tone of wording only):</strong> {nlp.sentiment.label}, compound {nlp.sentiment.compound.toFixed(2)}</p>}
      {nlp.confidence && nlp.confidence.score !== null && (
        <p><strong>Confidence indicator (experimental heuristic):</strong> {nlp.confidence.label ?? "n/a"} ({nlp.confidence.score.toFixed(2)} on 0–1)</p>
      )}
    </div>
  );
}

function Answer({ answer }: { answer: AnswerView }) {
  return (
    <article className="answer card-inset" aria-label={`Question ${answer.position}`}>
      <h4 className="question-heading"><span className="question-number">Q{answer.position}.</span> {answer.question}</h4>
      {answer.overall_score === null ? (
        <p className="hint" role="status">{answer.status_text || "Not evaluated"}. This answer has no score.</p>
      ) : (
        <>
          <div className="answer-head">
            <ScoreBar value={answer.overall_score} label={`Score of question ${answer.position}`} />
            {answer.recommendation && <span>Advice: <RecommendationBadge value={answer.recommendation} /></span>}
          </div>
          {answer.summary && <p>{answer.summary}</p>}
          <List title="Strengths" items={answer.strengths} />
          <List title="Areas for improvement" items={answer.improvements} />
          {answer.criteria.length > 0 && (
            <div>
              <h5 className="subhead">Criteria</h5>
              <ul className="criteria-detail">
                {answer.criteria.map((c) => (
                  <li key={c.key}>
                    <div className="criterion-head">
                      <strong>{humanizeKey(c.key)}</strong>
                      <ScoreBar value={c.score} min={answer.scale_min ?? 0} max={answer.scale_max ?? 10} label={humanizeKey(c.key)} />
                    </div>
                    {c.explanation && <p>{c.explanation}</p>}
                    {c.evidence_quotes.map((q, i) => <blockquote key={i} className="evidence">{q}</blockquote>)}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {answer.nlp ? <NlpBlock nlp={answer.nlp} /> : <p className="hint">NLP insights are unavailable for this answer.</p>}
        </>
      )}
    </article>
  );
}

export function CandidateEvaluationView({ detail, api, onBack, onSave }: Props) {
  const name = candidateLabel({ candidate_name: detail.candidate_name, session_id: detail.session_id });
  const noEvaluation = detail.evaluated_count === 0;
  return (
    <section className="card" aria-labelledby="candidate-title">
      <div className="detail-top">
        <button type="button" className="btn btn-secondary" onClick={onBack}>← Back to list</button>
        <ReportDownloadButton api={api} sessionId={detail.session_id} onSave={onSave}
          disabledReason={noEvaluation ? "No answer has been evaluated yet, so there is no report to download." : undefined} />
      </div>
      <h2 id="candidate-title">{name}</h2>
      <dl className="kv">
        <div><dt>Interview</dt><dd>{detail.interview_title ?? "—"}</dd></div>
        <div><dt>Date</dt><dd>{formatDate(detail.interview_date)}</dd></div>
        <div><dt>Status</dt><dd>{statusLabel(detail.status)}</dd></div>
        <div><dt>Answers evaluated</dt><dd>{detail.evaluated_count} of {detail.question_count}</dd></div>
      </dl>
      {!detail.is_complete && <p className="alert alert-warning" role="status">Partial data: some answers have no evaluation yet. Scores cover only the evaluated answers.</p>}

      <div className="score-hero">
        <div>
          <div className="metric-label">Overall score</div>
          <div className="score-hero-value">{formatScore(detail.overall_score)}{detail.overall_score !== null && <span className="score-hero-scale"> / 100</span>}</div>
          <div className="hint">{describeScoreSource(detail.score_source, detail.evaluated_count)}</div>
        </div>
        <div>
          <div className="metric-label">Recommendation</div>
          <div>{detail.recommendation ? <RecommendationBadge value={detail.recommendation} /> : <span className="score-missing">No session-level recommendation is stored</span>}</div>
          <div className="hint">Advisory only; the hiring decision stays with people. Per-answer advice is shown below, unchanged.</div>
        </div>
      </div>

      <h3 className="subhead">Criteria across answers</h3>
      <CriteriaChart points={detail.criteria_summary.points} scaleMin={detail.criteria_summary.scale_min} scaleMax={detail.criteria_summary.scale_max}
        unavailableReason={detail.criteria_summary.unavailable_reason} answersTotal={detail.evaluated_count} />

      <h3 className="subhead">Per-question evaluation</h3>
      {detail.answers.length === 0 ? <p className="hint">This interview has no questions.</p> : detail.answers.map((a) => <Answer key={a.position} answer={a} />)}
      <p className="hint">Transcripts are not shown here; they are part of the PDF report.</p>
    </section>
  );
}
