import type { Advice } from "../../types/dashboard";
import { adviceLabel } from "../../utils/dashboard";

/** The word is always printed; colour is only a hint. */
export function RecommendationBadge({ value, count }: { value: Advice; count?: number }) {
  return (
    <span className={`rec-badge rec-${value}`}>
      {adviceLabel(value)}
      {count !== undefined && <span className="rec-count"> {count}</span>}
    </span>
  );
}
