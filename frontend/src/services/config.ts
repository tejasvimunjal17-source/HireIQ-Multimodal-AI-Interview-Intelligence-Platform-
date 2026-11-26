const env = import.meta.env;

function positiveNumber(raw: string | undefined, fallback: number): number {
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

export const config = {
  apiBaseUrl: (env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, ""),
  demoMode: env.VITE_DEMO_MODE === "true",
  uploadTimeoutMs: positiveNumber(env.VITE_UPLOAD_TIMEOUT_MS, 60_000),
  requestTimeoutMs: 15_000,
  /** Used when a question has no time limit of its own. */
  defaultQuestionLimitSeconds: 120,
};
