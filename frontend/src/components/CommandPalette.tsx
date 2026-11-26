import { useEffect, useRef, useState } from "react";
import { Modal } from "./Modal";

import type { PaletteItem } from "../lib/commandPalette";
export type { PaletteItem };

/** Ctrl/⌘K: type part of a screen's name, Enter to go there. Every word
 * typed must appear in the label or its hint, in any order. With `onAsk`, a last
 * option sends the typed text to Ask ARP; Enter with no matching screen does too. */
export function CommandPalette({ items, onClose, onAsk }: { items: PaletteItem[]; onClose: () => void; onAsk?: (question: string) => void }) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  // After Modal's showModal(), which would otherwise focus its Close button.
  useEffect(() => input.current?.focus(), []);
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const matches = items.filter((it) => {
    const hay = ` ${it.label} ${it.hint ?? ""}`.toLowerCase().replace(/[^a-z0-9]+/g, " ");
    return words.every((w) => hay.includes(` ${w.replace(/[^a-z0-9]+/g, " ").trim()}`));
  });
  const question = query.trim();
  const askRow = onAsk && question ? matches.length : -1;
  const count = matches.length + (askRow >= 0 ? 1 : 0);
  const current = Math.max(0, Math.min(index, count - 1));

  function ask() {
    onClose();
    onAsk!(question);
  }

  function go(item: PaletteItem | undefined) {
    if (!item) return;
    window.location.hash = item.href.replace(/^#/, "");
    onClose();
  }

  return (
    <Modal title={onAsk ? "Search or ask" : "Jump to a screen or run"} onClose={onClose} compact>
      <input
        className="palette-input"
        ref={input}
        role="combobox"
        aria-label={onAsk ? "Search or ask" : "Jump to a screen or run"}
        aria-expanded="true"
        aria-controls="palette-list"
        aria-activedescendant={count ? `palette-${current}` : undefined}
        placeholder={onAsk ? "Type a screen, a run id or a question" : "Type a screen or run, e.g. drafting, voting, a run id"}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setIndex(0);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setIndex(count ? Math.min(current + 1, count - 1) : 0);
          else if (e.key === "ArrowUp") setIndex(Math.max(current - 1, 0));
          else if (e.key === "Enter") {
            if (count === 0) { e.preventDefault(); return; }
            if (askRow >= 0 && current === askRow) ask();
            else go(matches[current]);
          }
          else return;
          e.preventDefault();
        }}
      />
      <ul className="palette-list" id="palette-list" role="listbox" aria-label="Screens">
        {matches.map((it, i) => (
          <li
            key={`${i}:${it.href}`}
            id={`palette-${i}`}
            role="option"
            aria-selected={i === current}
            className={i === current ? "palette-item active" : "palette-item"}
            onMouseMove={() => setIndex(i)}
            onClick={() => go(it)}
          >
            {it.label}
            {it.hint && <span className="muted">{it.hint}</span>}
          </li>
        ))}
        {askRow >= 0 && (
          <li
            id={`palette-${askRow}`}
            role="option"
            aria-selected={current === askRow}
            className={current === askRow ? "palette-item active" : "palette-item"}
            onMouseMove={() => setIndex(askRow)}
            onClick={ask}
          >
            Ask ARP: “{question}”
          </li>
        )}
        {count === 0 && <li className="muted">No screen matches “{query}”.</li>}
      </ul>
    </Modal>
  );
}
