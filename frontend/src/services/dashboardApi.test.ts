import { afterEach, describe, expect, it, vi } from "vitest";
import { buildSessionQuery, createDashboardApi, dashboardErrorMessage } from "./dashboardApi";

const TOKEN = "secret-test-token-0123456789";
const filters = { search: "", interviewId: "", status: "", recommendation: "", page: 1 };

function respond(status: number, body: unknown, type = "application/json") {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  return new Response(status === 204 ? null : text, { status, headers: { "Content-Type": type } });
}

afterEach(() => vi.unstubAllGlobals());

describe("buildSessionQuery", () => {
  it("sends only the filters that are set, plus paging", () => {
    expect(buildSessionQuery(filters)).toBe("page=1&page_size=20");
    const q = new URLSearchParams(buildSessionQuery({ search: "  asha ", interviewId: "i-1", status: "evaluated", recommendation: "hold", page: 3 }));
    expect(Object.fromEntries(q)).toEqual({ search: "asha", interview_id: "i-1", status: "evaluated", recommendation: "hold", page: "3", page_size: "20" });
  });
  it("encodes special characters", () => {
    expect(buildSessionQuery({ ...filters, search: "a&b=c" })).toContain("search=a%26b%3Dc");
  });
});

describe("createDashboardApi", () => {
  it("sends the token only as a Bearer header, never in the URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(200, { total_sessions: 0 }));
    vi.stubGlobal("fetch", fetchMock);
    await createDashboardApi(TOKEN, "http://api").getSummary();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api/api/dashboard/summary");
    expect(String(url)).not.toContain(TOKEN);
    expect(init.headers.Authorization).toBe(`Bearer ${TOKEN}`);
  });

  it("calls the existing report endpoint and returns the PDF blob", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("%PDF-1.4 x", { status: 200, headers: { "Content-Type": "application/pdf" } }));
    vi.stubGlobal("fetch", fetchMock);
    const blob = await createDashboardApi(TOKEN, "http://api").downloadReport("abc-123");
    expect(fetchMock.mock.calls[0][0]).toBe("http://api/api/reports/abc-123/pdf");
    expect(blob).toBeInstanceOf(Blob);
    expect(await blob.text()).toContain("%PDF");
  });

  it("encodes ids and lists interviews through the existing public endpoint", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => respond(200, []));
    vi.stubGlobal("fetch", fetchMock);
    const api = createDashboardApi(TOKEN, "http://api");
    await api.getSessionDetail("a/b");
    await api.listInterviews();
    expect(fetchMock.mock.calls[0][0]).toBe("http://api/api/dashboard/sessions/a%2Fb");
    expect(fetchMock.mock.calls[1][0]).toBe("http://api/api/interviews");
  });

  it.each([
    [401, { detail: "Invalid or missing access token." }, /token was not accepted/],
    [503, { detail: "disabled" }, /dashboard is disabled/],
    [404, { detail: "Interview session not found." }, /could not be found/],
    [409, { detail: "No answer of this session has been evaluated yet." }, /evaluated yet/],
    [500, { detail: "Internal server error" }, /server had a problem/],
  ])("turns HTTP %i into a readable ApiError", async (status, body, pattern) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(status, body)));
    await expect(createDashboardApi(TOKEN, "http://api").downloadReport("x")).rejects.toMatchObject({ kind: "http", status, message: expect.stringMatching(pattern) });
  });

  it("reports a network failure and never leaks the token in the message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError(`failed ${TOKEN}`)));
    const error = await createDashboardApi(TOKEN, "http://api").getSummary().catch((e: Error) => e);
    expect(error).toMatchObject({ kind: "network" });
    expect((error as Error).message).not.toContain(TOKEN);
  });

  it("never writes the token to web storage", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(200, {})));
    await createDashboardApi(TOKEN, "http://api").getSummary();
    expect(JSON.stringify({ ...window.localStorage })).not.toContain(TOKEN);
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain(TOKEN);
  });
});

describe("dashboardErrorMessage", () => {
  it("falls back to the shared wording", () => {
    expect(dashboardErrorMessage(422, "bad")).toContain("bad");
  });
});
