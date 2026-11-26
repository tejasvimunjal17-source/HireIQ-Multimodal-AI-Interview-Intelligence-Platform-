interface ProgressBarProps {
  current: number; // 1-based question number
  total: number;
  answered: number;
}

export function ProgressBar({ current, total, answered }: ProgressBarProps) {
  const percent = total > 0 ? Math.round((answered / total) * 100) : 0;
  return (
    <div className="progress">
      <div className="progress-labels">
        <span>
          Question {current} of {total}
        </span>
        <span>
          {answered} of {total} answered
        </span>
      </div>
      <div
        className="progress-track"
        role="progressbar"
        aria-label="Interview progress"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={answered}
        aria-valuetext={`${answered} of ${total} questions answered`}
      >
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
