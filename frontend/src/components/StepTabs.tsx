import type { KeyboardEvent } from "react";

export interface StepTab { id: string; label: string; badge?: number | null; mark?: "done" | "waiting" | "attention" | null; disabled?: boolean }

const MARKS = { done: ["✓", "done"], waiting: ["⏸", "waiting on you"], attention: ["!", "needs attention"] } as const;

/** A tab bar with roving focus: ArrowLeft / ArrowRight move to the next enabled tab and select it. */
export function StepTabs(p: { label: string; tabs: StepTab[]; active: string; onSelect: (id: string) => void }) {
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const step = e.key === "ArrowRight" ? 1 : -1;
    const n = p.tabs.length;
    const from = p.tabs.findIndex((t) => t.id === p.active);
    for (let i = 1; i <= n; i++) {
      const t = p.tabs[(((from + step * i) % n) + n) % n];
      if (t.disabled) continue;
      e.preventDefault();
      p.onSelect(t.id);
      e.currentTarget.querySelector<HTMLButtonElement>(`[data-tab="${CSS.escape(t.id)}"]`)?.focus();
      return;
    }
  }

  return (
    <div className="sub-nav step-tabs" role="tablist" aria-label={p.label} onKeyDown={onKeyDown}>
      {p.tabs.map((t) => {
        const on = t.id === p.active;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            data-tab={t.id}
            className={on ? "nav-tab active" : "nav-tab"}
            aria-selected={on}
            tabIndex={on ? 0 : -1}
            disabled={t.disabled}
            onClick={() => p.onSelect(t.id)}
          >
            {t.label}
            {t.mark && (
              <span className="tab-mark" role="img" aria-label={MARKS[t.mark][1]}>
                {MARKS[t.mark][0]}
              </span>
            )}
            {t.badge != null && t.badge > 0 && <span className="tab-badge">{t.badge}</span>}
          </button>
        );
      })}
    </div>
  );
}
