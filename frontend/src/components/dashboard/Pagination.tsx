import { pageCount } from "../../utils/dashboard";

interface PaginationProps { page: number; pageSize: number; total: number; onPage: (page: number) => void }

export function Pagination({ page, pageSize, total, onPage }: PaginationProps) {
  const pages = pageCount(total, pageSize);
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(total, page * pageSize);
  return (
    <nav className="pagination" aria-label="Pagination">
      <span className="hint" role="status">{total === 0 ? "No sessions" : `Showing ${first}–${last} of ${total}`}</span>
      <div className="button-row">
        <button type="button" className="btn btn-secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
        <span className="page-indicator">Page {page} of {pages}</span>
        <button type="button" className="btn btn-secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </div>
    </nav>
  );
}
