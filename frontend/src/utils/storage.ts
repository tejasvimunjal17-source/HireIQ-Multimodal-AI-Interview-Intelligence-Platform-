/** sessionStorage can throw (private mode, blocked cookies), so every call is guarded. */
const KEY = "hireiq.sessionId";

export function loadSessionId(): string | null {
  try {
    return window.sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function saveSessionId(id: string): void {
  try {
    window.sessionStorage.setItem(KEY, id);
  } catch {
    /* resume simply will not work */
  }
}

export function clearSessionId(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
