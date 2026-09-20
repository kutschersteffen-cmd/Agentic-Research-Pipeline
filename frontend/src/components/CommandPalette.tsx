import { useEffect, useMemo, useRef, useState } from "react";
import { DESTINATIONS, type Destination } from "../nav";
import { navigate } from "../router";

interface Props {
  open: boolean;
  onClose: () => void;
}

function score(d: Destination, q: string): number {
  if (!q) return 0;
  const haystack = `${d.label} ${d.context ?? ""} ${d.group ?? ""}`.toLowerCase();
  const at = haystack.indexOf(q);
  if (at === -1) return -1;
  // A match on the destination's own name beats one on its page or group,
  // and an earlier match beats a later one.
  return (d.label.toLowerCase().includes(q) ? 0 : 100) + at;
}

/** Twenty-one pages plus their sub-tabs is more than anyone scans. Cmd/Ctrl-K
 *  searches every destination by name. */
export function CommandPalette({ open, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const restoreTo = useRef<HTMLElement | null>(null);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    return DESTINATIONS.map((d) => ({ d, s: score(d, q) }))
      .filter((r) => r.s >= 0)
      .sort((a, b) => a.s - b.s)
      .slice(0, 12)
      .map((r) => r.d);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    restoreTo.current = document.activeElement as HTMLElement | null;
    setQuery("");
    setCursor(0);
    inputRef.current?.focus();
    return () => restoreTo.current?.focus();
  }, [open]);

  useEffect(() => setCursor(0), [query]);

  if (!open) return null;

  function go(d: Destination) {
    navigate(d.tab, { sub: d.sub });
    onClose();
  }

  return (
    <div className="palette-overlay" onMouseDown={onClose}>
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Go to"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            onClose();
          } else if (e.key === "ArrowDown") {
            setCursor((c) => (results.length ? (c + 1) % results.length : 0));
          } else if (e.key === "ArrowUp") {
            setCursor((c) => (results.length ? (c - 1 + results.length) % results.length : 0));
          } else if (e.key === "Enter" && results[cursor]) {
            go(results[cursor]);
          } else if (e.key === "Tab") {
            // Nothing else in here is focusable; keep focus in the field.
            e.preventDefault();
          } else {
            return;
          }
          e.preventDefault();
        }}
      >
        <input
          ref={inputRef}
          className="palette-input"
          type="text"
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-results"
          aria-activedescendant={results[cursor] ? `palette-option-${cursor}` : undefined}
          aria-label="Search destinations"
          placeholder="Go to..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <ul className="palette-results" id="palette-results" role="listbox" aria-label="Destinations">
          {results.map((d, i) => (
            <li
              key={`${d.tab}/${d.sub ?? ""}`}
              id={`palette-option-${i}`}
              role="option"
              aria-selected={i === cursor}
              className={i === cursor ? "palette-option active" : "palette-option"}
              onMouseEnter={() => setCursor(i)}
              onClick={() => go(d)}
            >
              <span className="palette-option-label">{d.label}</span>
              <span className="palette-option-context">{d.context ?? d.group ?? ""}</span>
            </li>
          ))}
          {results.length === 0 && <li className="palette-empty">Nothing matches "{query}".</li>}
        </ul>
      </div>
    </div>
  );
}
