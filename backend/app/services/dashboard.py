"""Hiring-manager dashboard queries (Day 7). READ-ONLY: no writes, no model calls, no scoring.

Every number comes from stored rows:
- session score  = the stored `reports.overall_score` when a Report row exists, otherwise the plain average of that
  session's stored per-answer `evaluations.overall_score` (same rule as the Day 6 PDF). No score -> null, never 0.
- recommendation = the stored session-level `reports.recommendation` (usually absent: nothing writes it yet). The
  per-answer advice is counted separately in `advice`; it is never combined into a new decision here.
Listings use one aggregate query (no per-row queries) and only select the columns the table needs.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Candidate, CandidateResponse, Evaluation, Interview, InterviewSession, Question, Recommendation, Report, SessionStatus
from app.schemas.dashboard import (
    AdviceCounts, AnswerView, public_nlp, CriteriaSummary, CriterionView, DashboardSummary, RadarPointView, ScoreBucket, SessionDetail,
    SessionPage, SessionRow,
)
from app.services.reporting.data import AnswerData
from app.services.reporting.loader import load_session_data
from app.services.reporting.radar import aggregate_criteria

MAX_PAGE_SIZE = 100
FINISHED = (SessionStatus.SUBMITTED, SessionStatus.PROCESSING, SessionStatus.EVALUATED, SessionStatus.FAILED)
AWAITING = (SessionStatus.SUBMITTED, SessionStatus.PROCESSING)
BUCKETS = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100)]  # the last one includes 100


def _per_session_aggregates() -> sa.Subquery:
    def advice(rec: Recommendation):
        return sa.func.coalesce(sa.func.sum(sa.case((Evaluation.recommendation == rec, 1), else_=0)), 0)

    return (
        sa.select(
            CandidateResponse.session_id.label("session_id"),
            sa.func.count(CandidateResponse.id).label("answered"),
            sa.func.count(Evaluation.id).label("evaluated"),
            sa.func.avg(Evaluation.overall_score).label("avg_score"),
            advice(Recommendation.PROCEED).label("n_proceed"),
            advice(Recommendation.HOLD).label("n_hold"),
            advice(Recommendation.REJECT).label("n_reject"),
        )
        .select_from(CandidateResponse)
        .outerjoin(Evaluation, Evaluation.response_id == CandidateResponse.id)
        .group_by(CandidateResponse.session_id)
        .subquery()
    )


def _question_counts() -> sa.Subquery:
    return sa.select(Question.interview_id.label("interview_id"), sa.func.count(Question.id).label("n")).group_by(Question.interview_id).subquery()


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_sessions(
    db: Session, *, search: str | None = None, interview_id: uuid.UUID | None = None, status: SessionStatus | None = None,
    recommendation: Recommendation | None = None, page: int = 1, page_size: int = 20,
) -> SessionPage:
    """One page of sessions (newest first). Filters combine with AND. `recommendation` keeps sessions that have at
    least one evaluated answer with that stored advice."""
    if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise HTTPException(status_code=422, detail=f"page must be >= 1 and page_size between 1 and {MAX_PAGE_SIZE}.")
    agg, counts = _per_session_aggregates(), _question_counts()
    score = sa.func.coalesce(Report.overall_score, agg.c.avg_score)
    base = (
        sa.select(
            InterviewSession.id, InterviewSession.status, InterviewSession.started_at, InterviewSession.completed_at,
            InterviewSession.created_at, Candidate.full_name, Interview.id.label("interview_id"), Interview.title,
            sa.func.coalesce(counts.c.n, 0).label("question_count"),
            sa.func.coalesce(agg.c.answered, 0).label("answered"), sa.func.coalesce(agg.c.evaluated, 0).label("evaluated"),
            sa.case((Report.overall_score.is_not(None), "stored_report"), (agg.c.avg_score.is_not(None), "average_of_answers"), else_=None).label("score_source"),
            score.label("score"), Report.recommendation.label("recommendation"),
            sa.func.coalesce(agg.c.n_proceed, 0).label("n_proceed"), sa.func.coalesce(agg.c.n_hold, 0).label("n_hold"),
            sa.func.coalesce(agg.c.n_reject, 0).label("n_reject"),
        )
        .select_from(InterviewSession)
        .join(Candidate, Candidate.id == InterviewSession.candidate_id)
        .join(Interview, Interview.id == InterviewSession.interview_id)
        .outerjoin(agg, agg.c.session_id == InterviewSession.id)
        .outerjoin(counts, counts.c.interview_id == InterviewSession.interview_id)
        .outerjoin(Report, Report.session_id == InterviewSession.id)
    )
    term = (search or "").strip()
    if term:
        base = base.where(Candidate.full_name.ilike(f"%{_like_escape(term[:100])}%", escape="\\"))
    if interview_id is not None:
        base = base.where(InterviewSession.interview_id == interview_id)
    if status is not None:
        base = base.where(InterviewSession.status == status)
    if recommendation is not None:
        column = {Recommendation.PROCEED: agg.c.n_proceed, Recommendation.HOLD: agg.c.n_hold, Recommendation.REJECT: agg.c.n_reject}[recommendation]
        base = base.where(column > 0)

    total = db.scalar(sa.select(sa.func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.order_by(InterviewSession.created_at.desc(), InterviewSession.id).limit(page_size).offset((page - 1) * page_size)).all()
    items = [
        SessionRow(
            session_id=r.id, candidate_name=(r.full_name or "").strip() or None, interview_id=r.interview_id, interview_title=r.title,
            interview_date=r.completed_at or r.started_at or r.created_at, status=getattr(r.status, "value", r.status),
            question_count=r.question_count, answered_count=r.answered, evaluated_count=r.evaluated,
            overall_score=float(r.score) if r.score is not None else None, score_source=r.score_source,
            recommendation=getattr(r.recommendation, "value", r.recommendation),
            advice=AdviceCounts(proceed=r.n_proceed, hold=r.n_hold, reject=r.n_reject),
        )
        for r in rows
    ]
    return SessionPage(items=items, total=total, page=page, page_size=page_size)


def summary(db: Session) -> DashboardSummary:
    agg = _per_session_aggregates()
    rows = db.execute(
        sa.select(InterviewSession.status, sa.func.coalesce(Report.overall_score, agg.c.avg_score).label("score"))
        .select_from(InterviewSession)
        .outerjoin(agg, agg.c.session_id == InterviewSession.id)
        .outerjoin(Report, Report.session_id == InterviewSession.id)
    ).all()
    by_status = {s.value: 0 for s in SessionStatus}
    scores: list[float] = []
    for status, score in rows:
        by_status[getattr(status, "value", status)] += 1
        if score is not None:
            scores.append(float(score))
    distribution = [
        ScoreBucket(label=f"{lo}-{hi}", min=lo, max=hi, count=sum(1 for v in scores if lo <= v < hi or (hi == 100 and v == 100)))
        for lo, hi in BUCKETS
    ]
    return DashboardSummary(
        total_sessions=len(rows), by_status=by_status,
        completed_interviews=sum(by_status[s.value] for s in FINISHED), awaiting_evaluation=sum(by_status[s.value] for s in AWAITING),
        evaluation_failed=by_status[SessionStatus.FAILED.value], evaluated_sessions=by_status[SessionStatus.EVALUATED.value],
        scored_sessions=len(scores), average_score=(sum(scores) / len(scores)) if scores else None, score_distribution=distribution,
    )


def _answer_view(a: AnswerData) -> AnswerView:
    return AnswerView(
        position=a.position, question=a.question, status_text=a.status_text, overall_score=a.overall_score,
        recommendation=a.recommendation, summary=a.summary, strengths=list(a.strengths), improvements=list(a.improvements),
        criteria=[CriterionView(key=c.key, score=c.score, weight=c.weight, explanation=c.explanation, evidence_quotes=list(c.evidence_quotes)) for c in a.criteria],
        scale_min=a.scale[0] if a.scale else None, scale_max=a.scale[1] if a.scale else None, nlp=public_nlp(a.nlp),
    )  # NOTE: the transcript is deliberately not copied


def session_detail(db: Session, session_id: uuid.UUID) -> SessionDetail:
    """404 for an unknown session. Reuses the Day 6 loader, so the scoping and sanitising rules are identical."""
    data = load_session_data(db, session_id)
    radar, reason = aggregate_criteria(data.answers)
    if data.stored_overall_score is not None:
        score, source = data.stored_overall_score, "stored_report"
    elif data.average_score is not None:
        score, source = data.average_score, "average_of_answers"
    else:
        score, source = None, None
    return SessionDetail(
        session_id=session_id, candidate_name=(data.candidate_name or "").strip() or None, interview_title=data.interview_title,
        interview_date=data.interview_date, status=data.session_status, question_count=len(data.answers),
        evaluated_count=len(data.evaluated), is_complete=data.is_complete, overall_score=score, score_source=source,
        recommendation=data.stored_recommendation, answers=[_answer_view(a) for a in data.answers],
        criteria_summary=CriteriaSummary(
            points=[RadarPointView(key=p.key, value=p.value, answers=p.answers) for p in radar.points] if radar else [],
            scale_min=radar.scale[0] if radar else None, scale_max=radar.scale[1] if radar else None, unavailable_reason=reason,
        ),
    )
