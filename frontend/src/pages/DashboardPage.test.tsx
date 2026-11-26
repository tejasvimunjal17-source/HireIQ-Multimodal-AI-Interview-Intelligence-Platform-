import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../services/api";
import { makeDetail, makeFakeApi, makeRow, makeSummary, page } from "../test/dashboardHelpers";
import type { DashboardApi } from "../types/dashboard";
import { DashboardPage } from "./DashboardPage";

async function openDashboard(api: DashboardApi, extra: Partial<Parameters<typeof DashboardPage>[0]> = {}) {
  const createApi = vi.fn().mockReturnValue(api);
  render(<DashboardPage createApi={createApi} searchDelayMs={0} {...extra} />);
  await userEvent.type(screen.getByLabelText("Access token"), "a-long-test-token-1234");
  await userEvent.click(screen.getByRole("button", { name: "Open dashboard" }));
  return createApi;
}

describe("DashboardPage: access", () => {
  it("asks for the token first and calls nothing before it is entered", () => {
    const api = makeFakeApi();
    render(<DashboardPage createApi={() => api} />);
    expect(screen.getByRole("heading", { name: "Hiring manager access" })).toBeInTheDocument();
    expect(screen.getByLabelText("Access token")).toHaveAttribute("type", "password");
    expect(api.getSummary).not.toHaveBeenCalled();
  });

  it("hands the typed token to the API factory and keeps it out of web storage", async () => {
    const createApi = await openDashboard(makeFakeApi());
    expect(createApi).toHaveBeenCalledWith("a-long-test-token-1234");
    expect(JSON.stringify({ ...window.localStorage, ...window.sessionStorage })).not.toContain("a-long-test-token-1234");
  });

  it("returns to the token form with a message when the server rejects the token", async () => {
    const api = makeFakeApi({ getSummary: vi.fn().mockRejectedValue(new ApiError("http", "The access token was not accepted. Check it and try again.", 401)) });
    await openDashboard(api);
    expect(await screen.findByRole("alert")).toHaveTextContent("not accepted");
    expect(screen.getByLabelText("Access token")).toHaveValue("");
  });

  it("signs out and forgets the data", async () => {
    await openDashboard(makeFakeApi());
    await screen.findByText("Asha Verma");
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(screen.getByRole("heading", { name: "Hiring manager access" })).toBeInTheDocument();
    expect(screen.queryByText("Asha Verma")).not.toBeInTheDocument();
  });
});

describe("DashboardPage: listing states", () => {
  it("shows loading, then the overview and the table", async () => {
    let resolve!: (v: ReturnType<typeof page>) => void;
    const api = makeFakeApi({ listSessions: vi.fn().mockReturnValue(new Promise((r) => { resolve = r; })) });
    await openDashboard(api);
    expect(await screen.findByText("Loading sessions…")).toBeInTheDocument();
    expect(await screen.findByText("Interview sessions", { selector: "dt" })).toBeInTheDocument();
    resolve(page([makeRow()]));
    expect(await screen.findByText("Asha Verma")).toBeInTheDocument();
  });

  it("shows the empty state for an empty database, with no fake rows", async () => {
    await openDashboard(makeFakeApi({ listSessions: vi.fn().mockResolvedValue(page([])), getSummary: vi.fn().mockResolvedValue(makeSummary({ total_sessions: 0, scored_sessions: 0, average_score: null })) }));
    expect(await screen.findByText(/No interview sessions yet/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows an error with a working retry", async () => {
    const listSessions = vi.fn().mockRejectedValueOnce(new ApiError("network", "Cannot reach the server.")).mockResolvedValue(page([makeRow()]));
    await openDashboard(makeFakeApi({ listSessions }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the server.");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Asha Verma")).toBeInTheDocument();
  });

  it("still shows the table when only the overview fails", async () => {
    await openDashboard(makeFakeApi({ getSummary: vi.fn().mockRejectedValue(new ApiError("http", "The server had a problem.", 500)) }));
    expect(await screen.findByText("Asha Verma")).toBeInTheDocument();
    expect(screen.getByText("The server had a problem.")).toBeInTheDocument();
  });
});

describe("DashboardPage: search and filters", () => {
  it("sends search and every filter together to the backend and returns to page 1", async () => {
    const listSessions = vi.fn().mockResolvedValue(page([makeRow()], 45));
    await openDashboard(makeFakeApi({ listSessions }));
    await screen.findByText("Asha Verma");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(listSessions).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 })));
    await userEvent.type(screen.getByLabelText("Candidate name"), "ash");
    await userEvent.selectOptions(screen.getByLabelText("Interview / role"), "i-1");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "evaluated");
    await userEvent.selectOptions(screen.getByLabelText("Answer advice"), "proceed");
    await waitFor(() =>
      expect(listSessions).toHaveBeenLastCalledWith({ search: "ash", interviewId: "i-1", status: "evaluated", recommendation: "proceed", page: 1 }),
    );
  });

  it("explains an empty result caused by filters and can clear them", async () => {
    const listSessions = vi.fn().mockImplementation(async (f) => (f.status ? page([]) : page([makeRow()])));
    await openDashboard(makeFakeApi({ listSessions }));
    await screen.findByText("Asha Verma");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "failed");
    expect(await screen.findByText("No sessions match the current search and filters.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByText("Asha Verma")).toBeInTheDocument();
  });

  it("debounces the search box", async () => {
    const listSessions = vi.fn().mockResolvedValue(page([makeRow()]));
    render(<DashboardPage createApi={() => makeFakeApi({ listSessions })} searchDelayMs={150} />);
    await userEvent.type(screen.getByLabelText("Access token"), "a-long-test-token-1234");
    await userEvent.click(screen.getByRole("button", { name: "Open dashboard" }));
    await screen.findByText("Asha Verma");
    listSessions.mockClear();
    await userEvent.type(screen.getByLabelText("Candidate name"), "abc");
    await waitFor(() => expect(listSessions).toHaveBeenCalledTimes(1));
    expect(listSessions).toHaveBeenCalledWith(expect.objectContaining({ search: "abc" }));
  });

  it("ignores a slow older response that arrives after a newer one", async () => {
    let first!: (v: unknown) => void;
    const listSessions = vi.fn()
      .mockReturnValueOnce(new Promise((r) => { first = r; }))
      .mockResolvedValue(page([makeRow({ candidate_name: "Newer Result" })]));
    await openDashboard(makeFakeApi({ listSessions }));
    await userEvent.selectOptions(await screen.findByLabelText("Status"), "evaluated");
    expect(await screen.findByText("Newer Result")).toBeInTheDocument();
    first(page([makeRow({ candidate_name: "Stale Result" })]));
    await waitFor(() => expect(screen.queryByText("Stale Result")).not.toBeInTheDocument());
  });
});

describe("DashboardPage: candidate details and PDF", () => {
  it("opens the evaluation, downloads the PDF through the API object and returns to the list", async () => {
    const api = makeFakeApi();
    const onSave = vi.fn();
    await openDashboard(api, { onSave });
    await userEvent.click(await screen.findByRole("button", { name: "View evaluation of Asha Verma" }));
    expect(api.getSessionDetail).toHaveBeenCalledWith("11111111-aaaa-bbbb-cccc-000000000001");
    const heading = await screen.findByRole("heading", { name: "Asha Verma" });
    expect(heading).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Download PDF report" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.any(Blob), "hireiq-evaluation-11111111-aaaa-bbbb-cccc-000000000001.pdf"));
    await userEvent.click(screen.getByRole("button", { name: /Back to list/ }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });

  it("shows a detail error with a way back", async () => {
    const api = makeFakeApi({ getSessionDetail: vi.fn().mockRejectedValue(new ApiError("http", "This interview session could not be found.", 404)) });
    await openDashboard(api);
    await userEvent.click(await screen.findByRole("button", { name: /View evaluation of/ }));
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("This interview session could not be found.")).toBeInTheDocument();
    await userEvent.click(within(alert).getByRole("button", { name: "Back to list" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });

  it("shows detail for an unevaluated session without scores", async () => {
    const detail = makeDetail({ evaluated_count: 0, is_complete: false, overall_score: null, score_source: null, criteria_summary: { points: [], scale_min: null, scale_max: null, unavailable_reason: "No criterion scores are available for this session." } });
    await openDashboard(makeFakeApi({ getSessionDetail: vi.fn().mockResolvedValue(detail) }));
    await userEvent.click(await screen.findByRole("button", { name: /View evaluation of/ }));
    expect(await screen.findByText("No criterion scores are available for this session.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download PDF report" })).toBeDisabled();
  });
});
