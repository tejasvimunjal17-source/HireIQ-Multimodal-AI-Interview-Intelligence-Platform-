import type { ReactNode } from "react";

export type AlertTone = "error" | "success" | "info" | "warning";

interface AlertProps {
  tone: AlertTone;
  title?: string;
  children: ReactNode;
  action?: ReactNode;
}

/** Errors use role="alert" (announced immediately); everything else uses role="status". */
export function Alert({ tone, title, children, action }: AlertProps) {
  return (
    <div className={`alert alert-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <div className="alert-body">
        {title && <strong className="alert-title">{title}</strong>}
        <span>{children}</span>
      </div>
      {action && <div className="alert-action">{action}</div>}
    </div>
  );
}
