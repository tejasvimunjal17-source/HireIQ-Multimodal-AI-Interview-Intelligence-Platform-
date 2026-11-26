import { useCallback, useEffect, useRef, useState } from "react";
import { Alert } from "../components/Alert";
import { BrandHeader } from "../components/BrandHeader";
import { CandidateEvaluationView } from "../components/dashboard/CandidateEvaluationView";
import { DashboardOverview } from "../components/dashboard/DashboardOverview";
import { FilterPanel } from "../components/dashboard/FilterPanel";
import { InterviewTable } from "../components/dashboard/InterviewTable";
import { Pagination } from "../components/dashboard/Pagination";
import { TokenGate } from "../components/dashboard/TokenGate";
import { ApiError } from "../services/api";
import { createDashboardApi } from "../services/dashboardApi";
import type { DashboardApi, DashboardSummary, SessionDetail, SessionFilters, SessionPage } from "../types/dashboard";
import { PAGE_SIZE } from "../types/dashboard";
import type { InterviewSummary } from "../types/interview";

const NO_FILTERS: SessionFilters = { search: "", interviewId: "", status: "", recommendation: "", page: 1 };

interface DashboardPageProps {
  /** Builds the API for the token the manager typed. Tests inject a fake. */
  createApi?: (token: string) => DashboardApi;
  /** Debounce for the search box only (other filters apply at once). */
  searchDelayMs?: number;
  onSave?: (blob: Blob, filename: string) => void;
}

const messageOf = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong. Please try again.");
const isUnauthorised = (e: unknown) => e instanceof ApiError && (e.status === 401 || e.status === 503);

export function DashboardPage({ createApi = createDashboardApi, searchDelayMs = 300, onSave }: DashboardPageProps) {
  const [api, setApi] = useState<DashboardApi | null>(null);
  const [gateError, setGateError] = useState<string | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [interviews, setInterviews] = useState<InterviewSummary[]>([]);
  const [filters, setFilters] = useState<SessionFilters>(NO_FILTERS);
  const [applied, setApplied] = useState<SessionFilters>(NO_FILTERS); // `filters` after the search debounce
  const [list, setList] = useState<SessionPage | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const latest = useRef(0);

  const signOut = useCallback((message: string | null) => {
    setApi(null); setSummary(null); setList(null); setDetail(null); setOpenId(null);
    setFilters(NO_FILTERS); setApplied(NO_FILTERS); setGateError(message);
  }, []);

  const handleFailure = useCallback(
    (e: unknown, fallback: (message: string) => void) => {
      if (isUnauthorised(e)) signOut(messageOf(e));
      else fallback(messageOf(e));
    },
    [signOut],
  );

  // Debounce the search text; the other filters and the page number apply immediately.
  const appliedSearch = useRef("");
  useEffect(() => {
    const searchChanged = filters.search !== appliedSearch.current;
    if (!searchChanged || searchDelayMs <= 0) {
      appliedSearch.current = filters.search;
      setApplied(filters);
      return;
    }
    const timer = setTimeout(() => {
      appliedSearch.current = filters.search;
      setApplied(filters);
    }, searchDelayMs);
    return () => clearTimeout(timer);
  }, [filters, searchDelayMs]);

  const loadSummary = useCallback(
    (current: DashboardApi) => {
      setSummaryError(null);
      current.getSummary().then(setSummary).catch((e) => handleFailure(e, setSummaryError));
    },
    [handleFailure],
  );

  useEffect(() => {
    if (!api) return;
    loadSummary(api);
    api.listInterviews().then(setInterviews).catch(() => setInterviews([])); // the role filter simply stays empty
  }, [api, loadSummary]);

  useEffect(() => {
    if (!api) return;
    const ticket = ++latest.current; // ignore answers that arrive after a newer request was sent
    setLoading(true);
    setListError(null);
    api
      .listSessions(applied)
      .then((page) => { if (ticket === latest.current) setList(page); })
      .catch((e) => { if (ticket === latest.current) handleFailure(e, setListError); })
      .finally(() => { if (ticket === latest.current) setLoading(false); });
  }, [api, applied, handleFailure]);

  useEffect(() => {
    if (!api || !openId) { setDetail(null); return; }
    let cancelled = false;
    setDetail(null);
    setDetailLoading(true);
    setDetailError(null);
    api
      .getSessionDetail(openId)
      .then((d) => { if (!cancelled) setDetail(d); })
      .catch((e) => { if (!cancelled) handleFailure(e, setDetailError); })
      .finally(() => { if (!cancelled) setDetailLoading(false); });
    return () => { cancelled = true; };
  }, [api, openId, handleFailure]);

  const change = (patch: Partial<SessionFilters>) =>
    setFilters((f) => ({ ...f, ...patch, page: patch.page ?? 1 })); // any filter change returns to page 1
  const filtersActive = Boolean(applied.search.trim() || applied.interviewId || applied.status || applied.recommendation);

  return (
    <>
      <BrandHeader>
        {api && <button type="button" className="btn btn-header" onClick={() => signOut(null)}>Sign out</button>}
      </BrandHeader>
      <main className="page dash-page">
        <h1>Hiring manager dashboard</h1>
        {!api ? (
          <TokenGate error={gateError} onSubmit={(token) => { setGateError(null); setApi(createApi(token)); }} />
        ) : openId ? (
          <>
            {detailLoading && <p className="hint" role="status">Loading evaluation…</p>}
            {detailError && (
              <Alert tone="error" action={<button type="button" className="btn btn-secondary" onClick={() => setOpenId(null)}>Back to list</button>}>
                {detailError}
              </Alert>
            )}
            {detail && !detailLoading && <CandidateEvaluationView detail={detail} api={api} onSave={onSave} onBack={() => setOpenId(null)} />}
          </>
        ) : (
          <>
            {summaryError && (
              <Alert tone="error" action={<button type="button" className="btn btn-secondary" onClick={() => loadSummary(api)}>Retry</button>}>
                {summaryError}
              </Alert>
            )}
            {summary ? <DashboardOverview summary={summary} /> : !summaryError && <p className="hint" role="status">Loading overview…</p>}
            <section className="card" aria-labelledby="sessions-title">
              <h2 id="sessions-title">Interview sessions</h2>
              <FilterPanel filters={filters} interviews={interviews} onChange={change} onClear={() => setFilters(NO_FILTERS)} />
              {listError && (
                <Alert tone="error" action={<button type="button" className="btn btn-secondary" onClick={() => setApplied({ ...applied })}>Retry</button>}>
                  {listError}
                </Alert>
              )}
              {loading && !list && <p className="hint" role="status">Loading sessions…</p>}
              {list && (
                <div aria-busy={loading}>
                  {list.items.length === 0 ? (
                    <p className="empty-state" role="status">
                      {filtersActive
                        ? "No sessions match the current search and filters."
                        : "No interview sessions yet. They appear here once candidates start an interview."}
                    </p>
                  ) : (
                    <InterviewTable rows={list.items} onOpen={setOpenId} />
                  )}
                  <Pagination page={list.page} pageSize={PAGE_SIZE} total={list.total} onPage={(page) => change({ page })} />
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </>
  );
}
