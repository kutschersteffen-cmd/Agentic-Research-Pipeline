import { useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";

export interface TabDef {
  id: string;
  label: string;
  disabled?: boolean;
}

interface TabsProps {
  /** Namespaces the tab and panel ids; pass the same value to <TabPanel>. */
  id: string;
  tabs: readonly TabDef[];
  active: string;
  onChange: (id: string) => void;
  /** What this set of tabs switches between, for screen readers. */
  label: string;
}

/** Underline tabs for switching views inside a page -- deliberately unlike
 *  the sidebar, which moves between pages. Arrow keys move between tabs,
 *  Home/End jump to the ends, and only the active tab is a tab stop. */
export function Tabs({ id, tabs, active, onChange, label }: TabsProps) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function focusTab(next: TabDef) {
    onChange(next.id);
    refs.current[next.id]?.focus();
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const usable = tabs.filter((t) => !t.disabled);
    if (usable.length === 0) return;
    const at = usable.findIndex((t) => t.id === active);
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      const step = e.key === "ArrowRight" ? 1 : -1;
      const from = at === -1 ? 0 : at;
      focusTab(usable[(from + step + usable.length) % usable.length]);
    } else if (e.key === "Home") {
      focusTab(usable[0]);
    } else if (e.key === "End") {
      focusTab(usable[usable.length - 1]);
    } else {
      return;
    }
    e.preventDefault();
  }

  return (
    <div className="tabs" role="tablist" aria-label={label} onKeyDown={onKeyDown}>
      {tabs.map((t) => (
        <button
          key={t.id}
          ref={(el) => {
            refs.current[t.id] = el;
          }}
          type="button"
          role="tab"
          id={`${id}-tab-${t.id}`}
          className="tab"
          aria-controls={`${id}-panel-${t.id}`}
          aria-selected={t.id === active}
          tabIndex={t.id === active ? 0 : -1}
          disabled={t.disabled}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

interface TabPanelProps {
  id: string;
  active: string;
  children: ReactNode;
}

export function TabPanel({ id, active, children }: TabPanelProps) {
  return (
    <div role="tabpanel" id={`${id}-panel-${active}`} aria-labelledby={`${id}-tab-${active}`} tabIndex={-1}>
      {children}
    </div>
  );
}
