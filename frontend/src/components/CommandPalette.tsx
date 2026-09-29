import { useEffect, useRef, useState } from "react";
import { Modal } from "./Modal";

export type PaletteItem = { label: string; hint?: string; href: string };

/** Ctrl/⌘K: type part of a screen's name, Enter to go there. Every word
 * typed must appear in the label or its hint, in any order. */
export function CommandPalette({ items, onClose }: { items: PaletteItem[]; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  // After Modal's showModal(), which would otherwise focus its Close button.
  useEffect(() => input.current?.focus(), []);
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const matches = items.filter((it) => words.every((w) => `${it.label} ${it.hint ?? ""}`.toLowerCase().includes(w)));
  const current = Math.min(index, matches.length - 1);

  function go(item: PaletteItem | undefined) {
    if (!item) return;
    window.location.hash = item.href.replace(/^#/, "");
    onClose();
  }

  return (
    <Modal title="Jump to a screen" onClose={onClose} compact>
      <input
        className="palette-input"
        ref={input}
        role="combobox"
        aria-expanded="true"
        aria-controls="palette-list"
        aria-activedescendant={matches.length ? `palette-${current}` : undefined}
        placeholder="Type a screen, e.g. drafting, review, index"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setIndex(0);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setIndex(Math.min(current + 1, matches.length - 1));
          else if (e.key === "ArrowUp") setIndex(Math.max(current - 1, 0));
          else if (e.key === "Enter") go(matches[current]);
          else return;
          e.preventDefault();
        }}
      />
      <ul className="palette-list" id="palette-list" role="listbox" aria-label="Screens">
        {matches.map((it, i) => (
          <li
            key={it.href}
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
        {matches.length === 0 && <li className="muted">No screen matches “{query}”.</li>}
      </ul>
    </Modal>
  );
}
