import type { ReactNode } from "react";
import { Button } from "./Button";

export interface ActiveFilter {
  id: string;
  label: ReactNode;
  onClear: () => void;
}

interface FilterBarProps {
  /** The controls themselves. */
  children: ReactNode;
  /** What is currently narrowing the list, as removable chips -- so the
   *  reason a list looks empty is never hidden in a collapsed control. */
  active?: ActiveFilter[];
  onClearAll?: () => void;
  /** A line about what the list currently holds (count, total, span). */
  summary?: ReactNode;
}

export function FilterBar({ children, active = [], onClearAll, summary }: FilterBarProps) {
  return (
    <section className="card filter-bar">
      <div className="filter-bar-controls">{children}</div>
      {active.length > 0 && (
        <div className="chip-row" aria-label="Active filters">
          {active.map((f) => (
            <span className="chip filter-chip" key={f.id}>
              {f.label}
              <button type="button" className="filter-chip-clear" onClick={f.onClear} aria-label={`Clear filter`}>
                ×
              </button>
            </span>
          ))}
          {onClearAll && active.length > 1 && (
            <Button variant="ghost" size="sm" onClick={onClearAll}>
              Clear all
            </Button>
          )}
        </div>
      )}
      {summary && <p className="filter-bar-summary">{summary}</p>}
    </section>
  );
}
