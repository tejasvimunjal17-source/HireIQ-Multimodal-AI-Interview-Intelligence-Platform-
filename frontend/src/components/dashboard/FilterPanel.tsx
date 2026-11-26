import type { InterviewSummary } from "../../types/interview";
import type { SessionFilters } from "../../types/dashboard";
import { ADVICE_LABELS, STATUS_LABELS } from "../../utils/dashboard";

interface FilterPanelProps {
  filters: SessionFilters;
  interviews: InterviewSummary[];
  onChange: (patch: Partial<SessionFilters>) => void;
  onClear: () => void;
}

const isActive = (f: SessionFilters) => Boolean(f.search || f.interviewId || f.status || f.recommendation);

export function FilterPanel({ filters, interviews, onChange, onClear }: FilterPanelProps) {
  return (
    <form className="filter-panel" role="search" aria-label="Filter interview sessions" onSubmit={(e) => e.preventDefault()}>
      <div className="field">
        <label htmlFor="f-search">Candidate name</label>
        <input id="f-search" type="search" value={filters.search} maxLength={100} placeholder="Search by name"
          onChange={(e) => onChange({ search: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor="f-interview">Interview / role</label>
        <select id="f-interview" value={filters.interviewId} onChange={(e) => onChange({ interviewId: e.target.value })}>
          <option value="">All interviews</option>
          {interviews.map((i) => <option key={i.id} value={i.id}>{i.title}</option>)}
        </select>
      </div>
      <div className="field">
        <label htmlFor="f-status">Status</label>
        <select id="f-status" value={filters.status} onChange={(e) => onChange({ status: e.target.value })}>
          <option value="">All statuses</option>
          {Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>
      <div className="field">
        <label htmlFor="f-advice">Answer advice</label>
        <select id="f-advice" value={filters.recommendation} onChange={(e) => onChange({ recommendation: e.target.value })}>
          <option value="">Any</option>
          {Object.entries(ADVICE_LABELS).map(([value, label]) => <option key={value} value={value}>Has a “{label}” answer</option>)}
        </select>
      </div>
      <button type="button" className="btn btn-secondary" onClick={onClear} disabled={!isActive(filters)}>Clear filters</button>
    </form>
  );
}
