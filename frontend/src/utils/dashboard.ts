import type { Advice, SessionRow } from "../types/dashboard";

/** Scores keep their stored precision (at most 2 decimals, no trailing zeros). null/undefined = "no score", never 0. */
export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Not scored";
  return String(Number(value.toFixed(2)));
}

/** Position of a value on a [min, max] scale as 0-100 (clamped). Invalid scales give 0. */
export function scalePercent(value: number, min: number | null, max: number | null): number {
  if (min === null || max === null || max <= min || !Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
}

export const STATUS_LABELS: Record<string, string> = {
  created: "Not started", in_progress: "In progress", submitted: "Submitted", processing: "Evaluating", evaluated: "Evaluated", failed: "Evaluation failed",
};
export const statusLabel = (status: string) => STATUS_LABELS[status] ?? status;

export const ADVICE_LABELS: Record<Advice, string> = { proceed: "Proceed", hold: "Hold", reject: "Reject" };
export const adviceLabel = (value: Advice) => ADVICE_LABELS[value];

export function candidateLabel(row: { candidate_name: string | null; session_id: string }): string {
  return row.candidate_name?.trim() || `Unnamed candidate (${row.session_id.slice(0, 8)})`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
}

export function humanizeKey(key: string): string {
  const text = key.replace(/_/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : key;
}

/** Which stored advice a row carries, as short chips ("Proceed 2"); empty when no answer is evaluated. */
export function adviceSummary(row: Pick<SessionRow, "advice">): { advice: Advice; count: number }[] {
  return (["proceed", "hold", "reject"] as const).map((advice) => ({ advice, count: row.advice[advice] })).filter((item) => item.count > 0);
}

export function describeScoreSource(source: SessionRow["score_source"], evaluated: number): string {
  if (source === "stored_report") return "Stored session score";
  if (source === "average_of_answers") return `Average of ${evaluated} evaluated answer${evaluated === 1 ? "" : "s"}`;
  return "";
}

export function pageCount(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(total / Math.max(1, pageSize)));
}

/** Saves a Blob through a temporary link. Injectable in tests (jsdom has no object URLs). */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
