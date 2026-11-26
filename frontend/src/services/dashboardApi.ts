import type { InterviewSummary } from "../types/interview";
import type { DashboardApi, SessionDetail, SessionFilters, SessionPage, DashboardSummary } from "../types/dashboard";
import { PAGE_SIZE } from "../types/dashboard";
import { ApiError, httpErrorMessage } from "./api";
import { config } from "./config";

const NETWORK_MESSAGE = "Cannot reach the server. Check your connection and try again.";
const TIMEOUT_MESSAGE = "The server took too long to respond. Please try again.";

function detailOf(body: unknown): string | undefined {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    return typeof detail === "string" ? detail : undefined;
  }
  return undefined;
}

/** Dashboard-specific wording; everything else falls back to the shared messages. */
export function dashboardErrorMessage(status: number, detail?: string): string {
  if (status === 401) return "The access token was not accepted. Check it and try again.";
  if (status === 503) return "The dashboard is disabled on the server: REPORT_ACCESS_TOKEN is not configured.";
  if (status === 409) return detail ?? "This session has nothing evaluated yet.";
  if (status === 404) return "This interview session could not be found.";
  return httpErrorMessage(status, detail);
}

export function buildSessionQuery(filters: SessionFilters): string {
  const params = new URLSearchParams();
  const search = filters.search.trim();
  if (search) params.set("search", search);
  if (filters.interviewId) params.set("interview_id", filters.interviewId);
  if (filters.status) params.set("status", filters.status);
  if (filters.recommendation) params.set("recommendation", filters.recommendation);
  params.set("page", String(filters.page));
  params.set("page_size", String(PAGE_SIZE));
  return params.toString();
}

/**
 * `token` is the access token the manager typed in. It is only ever sent as a Bearer header; it is never stored
 * (no localStorage / sessionStorage), logged or put in a URL.
 */
export function createDashboardApi(token: string, baseUrl: string = config.apiBaseUrl): DashboardApi {
  async function request(path: string, accept: string): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30_000);
    try {
      const response = await fetch(`${baseUrl}${path}`, {
        headers: { Accept: accept, Authorization: `Bearer ${token}` }, signal: controller.signal, cache: "no-store",
      });
      if (!response.ok) {
        let detail: string | undefined;
        try {
          detail = detailOf(await response.json());
        } catch {
          detail = undefined;
        }
        throw new ApiError("http", dashboardErrorMessage(response.status, detail), response.status);
      }
      return response;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (error instanceof DOMException && error.name === "AbortError") throw new ApiError("timeout", TIMEOUT_MESSAGE);
      throw new ApiError("network", NETWORK_MESSAGE);
    } finally {
      clearTimeout(timer);
    }
  }
  const json = async <T>(path: string) => (await (await request(path, "application/json")).json()) as T;

  return {
    listInterviews: () => json<InterviewSummary[]>("/api/interviews"),
    getSummary: () => json<DashboardSummary>("/api/dashboard/summary"),
    listSessions: (filters) => json<SessionPage>(`/api/dashboard/sessions?${buildSessionQuery(filters)}`),
    getSessionDetail: (id) => json<SessionDetail>(`/api/dashboard/sessions/${encodeURIComponent(id)}`),
    downloadReport: async (id) => (await request(`/api/reports/${encodeURIComponent(id)}/pdf`, "application/pdf")).blob(),
  };
}
