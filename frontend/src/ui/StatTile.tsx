import type { ReactNode } from "react";

interface StatTileProps {
  label: ReactNode;
  value: ReactNode;
  /** What the number is measured against -- a window, a total, a comparison. */
  hint?: ReactNode;
  /** Where the number came from. A stat nobody can open is a dead end. */
  href?: string;
  tone?: "default" | "accent" | "warn";
}

/** Label first, then the number: the reader needs to know what they are
 *  looking at before the figure means anything. */
export function StatTile({ label, value, hint, href, tone = "default" }: StatTileProps) {
  const body = (
    <>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {hint && <span className="stat-hint">{hint}</span>}
    </>
  );
  if (href) {
    return (
      <a className="stat-tile" data-tone={tone} href={href}>
        {body}
      </a>
    );
  }
  return (
    <div className="stat-tile" data-tone={tone}>
      {body}
    </div>
  );
}
