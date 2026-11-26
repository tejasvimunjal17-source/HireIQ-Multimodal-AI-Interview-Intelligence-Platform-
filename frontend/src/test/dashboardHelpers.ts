import { vi } from "vitest";
import type { DashboardApi, DashboardSummary, SessionDetail, SessionPage, SessionRow } from "../types/dashboard";

export function makeRow(overrides: Partial<SessionRow> = {}): SessionRow {
  return {
    session_id: "11111111-aaaa-bbbb-cccc-000000000001", candidate_name: "Asha Verma", interview_id: "i-1", interview_title: "Backend Engineer Screening",
    interview_date: "2026-11-20T09:30:00Z", status: "evaluated", question_count: 2, answered_count: 2, evaluated_count: 2, overall_score: 69.75,
    score_source: "average_of_answers", recommendation: null, advice: { proceed: 1, hold: 1, reject: 0 }, ...overrides,
  };
}

export function makeSummary(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    total_sessions: 6, by_status: { created: 0, in_progress: 1, submitted: 1, processing: 1, evaluated: 2, failed: 1 }, completed_interviews: 5,
    awaiting_evaluation: 2, evaluation_failed: 1, evaluated_sessions: 2, scored_sessions: 2, average_score: 85,
    score_distribution: [
      { label: "0-20", min: 0, max: 20, count: 0 }, { label: "20-40", min: 20, max: 40, count: 0 }, { label: "40-60", min: 40, max: 60, count: 0 },
      { label: "60-80", min: 60, max: 80, count: 1 }, { label: "80-100", min: 80, max: 100, count: 1 },
    ], ...overrides,
  };
}

export function makeDetail(overrides: Partial<SessionDetail> = {}): SessionDetail {
  const criteria = ["technical_accuracy", "depth_of_understanding", "communication_clarity"].map((key, i) => ({
    key, score: 8 - i, weight: 0.33, explanation: `Explanation for ${key}.`, evidence_quotes: ["threads share memory"],
  }));
  return {
    session_id: "11111111-aaaa-bbbb-cccc-000000000001", candidate_name: "Asha Verma", interview_title: "Backend Engineer Screening",
    interview_date: "2026-11-20T09:30:00Z", status: "evaluated", question_count: 2, evaluated_count: 2, is_complete: true, overall_score: 69.75,
    score_source: "average_of_answers", recommendation: null,
    answers: [
      {
        position: 1, question: "Explain processes and threads.", status_text: "", overall_score: 75.5, recommendation: "proceed", summary: "A correct answer.",
        strengths: ["Clear distinction"], improvements: ["Discuss context switches"], criteria, scale_min: 0, scale_max: 10,
        nlp: { status: "completed", keywords: [{ text: "race condition", count: 1 }], entities: [], sentiment: { label: "positive", positive: 0.1, neutral: 0.8, negative: 0.1, compound: 0.4 }, confidence: { score: 0.71, label: "high" } },
      },
      { position: 2, question: "Describe an incident.", status_text: "Transcription not finished yet", overall_score: null, recommendation: null, summary: "", strengths: [], improvements: [], criteria: [], scale_min: null, scale_max: null, nlp: null },
    ],
    criteria_summary: { points: criteria.map((c) => ({ key: c.key, value: c.score, answers: 1 })), scale_min: 0, scale_max: 10, unavailable_reason: "" },
    ...overrides,
  };
}

export const page = (items: SessionRow[], total = items.length, pageNo = 1): SessionPage => ({ items, total, page: pageNo, page_size: 20 });

export function makeFakeApi(overrides: Partial<DashboardApi> = {}): DashboardApi {
  return {
    listInterviews: vi.fn().mockResolvedValue([{ id: "i-1", title: "Backend Engineer Screening", description: null, interview_type: "technical", question_count: 2, total_time_limit_seconds: null }]),
    getSummary: vi.fn().mockResolvedValue(makeSummary()),
    listSessions: vi.fn().mockResolvedValue(page([makeRow()])),
    getSessionDetail: vi.fn().mockResolvedValue(makeDetail()),
    downloadReport: vi.fn().mockResolvedValue(new Blob(["%PDF-1.4"], { type: "application/pdf" })),
    ...overrides,
  };
}
