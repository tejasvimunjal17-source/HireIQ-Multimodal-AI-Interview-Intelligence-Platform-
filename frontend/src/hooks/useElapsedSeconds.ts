import { useEffect, useRef, useState } from "react";

/**
 * Counts seconds while `running` is true. Based on Date.now(), so it stays accurate
 * even if the browser slows timers in a background tab.
 */
export function useElapsedSeconds(running: boolean): number {
  const [elapsedMs, setElapsedMs] = useState(0);
  const baseRef = useRef(0);

  useEffect(() => {
    if (!running) return;
    const startedAt = Date.now();
    const id = window.setInterval(() => setElapsedMs(baseRef.current + Date.now() - startedAt), 500);
    return () => {
      window.clearInterval(id);
      baseRef.current += Date.now() - startedAt;
      setElapsedMs(baseRef.current);
    };
  }, [running]);

  return Math.floor(elapsedMs / 1000);
}
