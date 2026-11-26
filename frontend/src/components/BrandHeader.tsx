import type { ReactNode } from "react";

export function BrandHeader({ children }: { children?: ReactNode }) {
  return (
    <header className="brand-header">
      <div className="brand">
        <svg className="brand-logo" viewBox="0 0 32 32" width="32" height="32" aria-hidden="true" focusable="false">
          <rect width="32" height="32" rx="8" fill="currentColor" />
          <path d="M9 9v14M23 9v14M9 16h14" stroke="#fff" strokeWidth="3" strokeLinecap="round" />
        </svg>
        <span className="brand-name">
          Hire<span>IQ</span>
        </span>
      </div>
      <div className="brand-slot">{children}</div>
    </header>
  );
}
