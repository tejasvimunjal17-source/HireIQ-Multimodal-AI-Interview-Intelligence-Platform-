import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../services/api";
import { makeDetail, makeFakeApi, makeRow, makeSummary } from "../../test/dashboardHelpers";
import { CandidateEvaluationView } from "./CandidateEvaluationView";
import { CriteriaChart } from "./CriteriaChart";
import { DashboardOverview } from "./DashboardOverview";
import { FilterPanel } from "./FilterPanel";
import { InterviewTable } from "./InterviewTable";
import { Pagination } from "./Pagination";
import { ReportDownloadButton } from "./ReportDownloadButton";
import { ScoreBar } from "./ScoreBar";

describe("DashboardOverview", () => {
  it("shows each metric exactly as computed by the backend", () => {
    render(<DashboardOverview summary={makeSummary()} />);
    const card = (label: string) => screen.getByText(label).closest(".metric-card") as HTMLElement;
    expect(within(card("Interview sessions")).getByText("6")).toBeInTheDocument();
    expect(within(card("Completed interviews")).getByText("5")).toBeInTheDocument();
    expect(within(card("Awaiting evaluation")).getByText("2")).toBeInTheDocument();
    expect(within(card("Evaluated sessions")).getByText("2")).toBeInTheDocument();
    expect(within(card("Evaluated sessions")).getByText("1 failed evaluation")).toBeInTheDocument();
    expect(within(card("Average score")).getByText("85")).toBeInTheDocument();
  });

  it("shows a dash, not 0, when there is no average", () => {
    render(<DashboardOverview summary={makeSummary({ average_score: null, scored_sessions: 0, total_sessions: 0 })} />);
    const card = screen.getByText("Average score").closest(".metric-card") as HTMLElement;
    expect(within(card).getByText("—")).toBeInTheDocument();
    expect(screen.getByText("No scored sessions yet.")).toBeInTheDocument();
  });

  it("renders the score distribution with the stored counts", () => {
    render(<DashboardOverview summary={makeSummary()} />);
    const list = screen.getByRole("list", { name: /per score range/ });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(within(items[3]).getByText("60-80")).toBeInTheDocument();
    expect(within(items[3]).getByText("1")).toBeInTheDocument();
  });
});

describe("InterviewTable", () => {
  it("lists the available fields for each session", () => {
    render(<InterviewTable rows={[makeRow()]} onOpen={() => {}} />);
    const row = screen.getByRole("row", { name: /Asha Verma/ });
    expect(within(row).getByText("Backend Engineer Screening")).toBeInTheDocument();
    expect(within(row).getByText("20 Nov 2026")).toBeInTheDocument();
    expect(within(row).getByText("Evaluated")).toBeInTheDocument();
    expect(within(row).getByText("69.75")).toBeInTheDocument();
    expect(within(row).getByText("Average of 2 evaluated answers")).toBeInTheDocument();
    expect(within(row).getByText("Not recorded")).toBeInTheDocument();
  });

  it("handles unevaluated, unnamed and very long-named sessions without inventing values", () => {
    const longName = "Bartholomew ".repeat(20).trim();
    render(
      <InterviewTable
        onOpen={() => {}}
        rows={[
          makeRow({ session_id: "aaaaaaaa-0000", candidate_name: null, status: "in_progress", overall_score: null, score_source: null, evaluated_count: 0, answered_count: 1, advice: { proceed: 0, hold: 0, reject: 0 } }),
          makeRow({ session_id: "bbbbbbbb-0000", candidate_name: longName }),
        ]}
      />,
    );
    expect(screen.getByText("Unnamed candidate (aaaaaaaa)")).toBeInTheDocument();
    expect(screen.getByText("Not scored")).toBeInTheDocument();
    expect(screen.getByText("0 of 2 answers evaluated")).toBeInTheDocument();
    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.getByText(longName)).toHaveAttribute("title", longName);
  });

  it("shows a stored session recommendation as a word, and answer advice separately", () => {
    render(<InterviewTable rows={[makeRow({ recommendation: "reject" })]} onOpen={() => {}} />);
    expect(screen.getAllByText("Reject").length).toBeGreaterThan(0);
    expect(screen.getByText(/Answer advice:/)).toBeInTheDocument();
  });

  it("opens a session from the View button", async () => {
    const onOpen = vi.fn();
    render(<InterviewTable rows={[makeRow()]} onOpen={onOpen} />);
    await userEvent.click(screen.getByRole("button", { name: "View evaluation of Asha Verma" }));
    expect(onOpen).toHaveBeenCalledWith("11111111-aaaa-bbbb-cccc-000000000001");
  });
});

describe("FilterPanel", () => {
  const interviews = [{ id: "i-1", title: "Backend", description: null, interview_type: "technical", question_count: 2, total_time_limit_seconds: null }];
  const base = { search: "", interviewId: "", status: "", recommendation: "", page: 1 };

  it("reports every control change and offers real options only", async () => {
    const onChange = vi.fn();
    render(<FilterPanel filters={base} interviews={interviews} onChange={onChange} onClear={() => {}} />);
    await userEvent.type(screen.getByLabelText("Candidate name"), "a");
    expect(onChange).toHaveBeenCalledWith({ search: "a" });
    await userEvent.selectOptions(screen.getByLabelText("Interview / role"), "i-1");
    expect(onChange).toHaveBeenCalledWith({ interviewId: "i-1" });
    await userEvent.selectOptions(screen.getByLabelText("Status"), "evaluated");
    expect(onChange).toHaveBeenCalledWith({ status: "evaluated" });
    await userEvent.selectOptions(screen.getByLabelText("Answer advice"), "hold");
    expect(onChange).toHaveBeenCalledWith({ recommendation: "hold" });
  });

  it("enables 'Clear filters' only when a filter is active", async () => {
    const onClear = vi.fn();
    const { rerender } = render(<FilterPanel filters={base} interviews={[]} onChange={() => {}} onClear={onClear} />);
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeDisabled();
    rerender(<FilterPanel filters={{ ...base, status: "failed" }} interviews={[]} onChange={() => {}} onClear={onClear} />);
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(onClear).toHaveBeenCalled();
  });
});

describe("Pagination", () => {
  it("shows the range and disables the unusable direction", async () => {
    const onPage = vi.fn();
    render(<Pagination page={1} pageSize={20} total={45} onPage={onPage} />);
    expect(screen.getByText("Showing 1–20 of 45")).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onPage).toHaveBeenCalledWith(2);
  });
  it("copes with an empty result", () => {
    render(<Pagination page={1} pageSize={20} total={0} onPage={() => {}} />);
    expect(screen.getByText("No sessions")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });
});

describe("score visualisation", () => {
  it("ScoreBar draws the stored value on its scale and never draws a missing score as an empty bar", () => {
    const { rerender } = render(<ScoreBar value={7.5} min={5} max={10} label="Test" />);
    expect(screen.getByRole("img", { name: "Test: 7.5 on a 5 to 10 scale" })).toBeInTheDocument();
    expect(document.querySelector(".score-bar-fill")).toHaveStyle({ width: "50%" });
    rerender(<ScoreBar value={null} label="Test" />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("Not scored")).toBeInTheDocument();
  });

  it("CriteriaChart shows each criterion, its scale and marks partial criteria", () => {
    render(<CriteriaChart points={[{ key: "technical_accuracy", value: 8, answers: 2 }, { key: "communication_clarity", value: 6, answers: 1 }]} scaleMin={0} scaleMax={10} answersTotal={2} />);
    expect(screen.getByRole("img", { name: "Technical accuracy: 8 on a 0 to 10 scale" })).toBeInTheDocument();
    expect(screen.getByText("1 of 2 answers")).toBeInTheDocument();
    expect(screen.getByText(/scale 0–10/)).toBeInTheDocument();
  });

  it("CriteriaChart says why there is no chart instead of drawing zeros", () => {
    render(<CriteriaChart points={[]} scaleMin={null} scaleMax={null} unavailableReason="The answers were scored on different scales." />);
    expect(screen.getByText("The answers were scored on different scales.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

describe("CandidateEvaluationView", () => {
  it("shows score, interview info, summary, strengths, improvements, criteria and evidence", () => {
    render(<CandidateEvaluationView detail={makeDetail()} api={makeFakeApi()} onBack={() => {}} />);
    expect(screen.getByRole("heading", { name: "Asha Verma" })).toBeInTheDocument();
    expect(screen.getAllByText("Backend Engineer Screening").length).toBeGreaterThan(0);
    expect(screen.getByText("69.75")).toBeInTheDocument();
    expect(screen.getByText("Average of 2 evaluated answers")).toBeInTheDocument();
    expect(screen.getByText("A correct answer.")).toBeInTheDocument();
    expect(screen.getByText("Clear distinction")).toBeInTheDocument();
    expect(screen.getByText("Discuss context switches")).toBeInTheDocument();
    expect(screen.getByText("Explanation for technical_accuracy.")).toBeInTheDocument();
    expect(screen.getAllByText("threads share memory").length).toBeGreaterThan(0);
    expect(screen.getByText("No session-level recommendation is stored")).toBeInTheDocument();
  });

  it("labels NLP insights experimental and advisory, and says when they are unavailable", () => {
    render(<CandidateEvaluationView detail={makeDetail()} api={makeFakeApi()} onBack={() => {}} />);
    expect(screen.getByText("Experimental · advisory")).toBeInTheDocument();
    expect(screen.getByText(/play no part in the score or recommendation/)).toBeInTheDocument();
    expect(screen.getByText(/Sentiment \(tone of wording only\)/)).toBeInTheDocument();
    expect(screen.getByText(/Confidence indicator \(experimental heuristic\)/)).toBeInTheDocument();
  });

  it("explains an answer without evaluation and flags partial data", () => {
    render(<CandidateEvaluationView detail={makeDetail({ is_complete: false })} api={makeFakeApi()} onBack={() => {}} />);
    expect(screen.getByText(/Transcription not finished yet/)).toBeInTheDocument();
    expect(screen.getByText(/Partial data/)).toBeInTheDocument();
  });

  it("never shows a transcript", () => {
    render(<CandidateEvaluationView detail={makeDetail()} api={makeFakeApi()} onBack={() => {}} />);
    expect(screen.getByText(/Transcripts are not shown here/)).toBeInTheDocument();
  });

  it("disables the PDF button with a reason when nothing is evaluated", () => {
    render(<CandidateEvaluationView detail={makeDetail({ evaluated_count: 0, overall_score: null, score_source: null })} api={makeFakeApi()} onBack={() => {}} />);
    expect(screen.getByRole("button", { name: "Download PDF report" })).toBeDisabled();
    expect(screen.getByText(/no report to download/)).toBeInTheDocument();
    expect(screen.getByText("Not scored")).toBeInTheDocument();
  });

  it("goes back to the list", async () => {
    const onBack = vi.fn();
    render(<CandidateEvaluationView detail={makeDetail()} api={makeFakeApi()} onBack={onBack} />);
    await userEvent.click(screen.getByRole("button", { name: /Back to list/ }));
    expect(onBack).toHaveBeenCalled();
  });
});

describe("ReportDownloadButton", () => {
  it("downloads through the backend endpoint and saves the file under a session-id name", async () => {
    const api = makeFakeApi();
    const onSave = vi.fn();
    render(<ReportDownloadButton api={api} sessionId="sess-1" onSave={onSave} />);
    await userEvent.click(screen.getByRole("button", { name: "Download PDF report" }));
    expect(api.downloadReport).toHaveBeenCalledWith("sess-1");
    expect(onSave).toHaveBeenCalledWith(expect.any(Blob), "hireiq-evaluation-sess-1.pdf");
  });

  it("is disabled while preparing, then shows a readable error and allows a retry", async () => {
    let reject!: (e: Error) => void;
    const api = makeFakeApi({ downloadReport: vi.fn().mockReturnValue(new Promise((_, r) => { reject = r; })) });
    render(<ReportDownloadButton api={api} sessionId="s" onSave={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Download PDF report" }));
    expect(screen.getByRole("button", { name: "Preparing PDF…" })).toBeDisabled();
    reject(new ApiError("http", "This session has nothing evaluated yet.", 409));
    expect(await screen.findByRole("alert")).toHaveTextContent("This session has nothing evaluated yet.");
    expect(screen.getByRole("button", { name: "Download PDF report" })).toBeEnabled();
  });
});
