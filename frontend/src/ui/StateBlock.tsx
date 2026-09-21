import type { ReactNode } from "react";
import { Button } from "./Button";

interface StateBlockProps {
  kind: "loading" | "empty" | "error";
  /** Error text, or the label shown while loading. */
  message?: ReactNode;
  /** Headline above the message: what is missing, or what failed. */
  title?: ReactNode;
  /** Loading only: render this many skeleton lines shaped like the content
   *  that is coming, so the layout does not jump when it lands. */
  rows?: number;
  /** Error only: re-runs the action that failed. */
  onRetry?: () => void;
  /** Empty only: the action that would fill this view. */
  action?: ReactNode;
  className?: string;
}

/** The one way this app reports loading, empty and failed states. */
export function StateBlock({ kind, message, title, rows, onRetry, action, className }: StateBlockProps) {
  const classes = className ? `state-block ${className}` : "state-block";

  if (kind === "loading") {
    return (
      <div className={classes} data-kind="loading" aria-live="polite" aria-busy="true">
        {rows ? (
          <div className="skeleton-stack">
            {Array.from({ length: rows }, (_, i) => (
              <span className="skeleton" key={i} style={{ width: `${100 - i * 7}%` }} />
            ))}
            <span className="sr-only">{message ?? "Loading"}</span>
          </div>
        ) : (
          <p className="state-block-message">
            <span className="btn-spinner" aria-hidden="true" />
            {message ?? "Loading..."}
          </p>
        )}
      </div>
    );
  }

  if (kind === "empty") {
    return (
      <div className={classes} data-kind="empty" data-full={title || action ? "true" : undefined}>
        {title && <span className="state-block-title">{title}</span>}
        {message && <p className="state-block-message">{message}</p>}
        {action}
      </div>
    );
  }

  return (
    <div className={classes} data-kind="error" role="alert">
      {title && <span className="state-block-title">{title}</span>}
      {message && <p className="state-block-message">{message}</p>}
      {onRetry && (
        <Button variant="ghost" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}
