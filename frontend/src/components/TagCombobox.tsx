import { useEffect, useId, useRef, useState } from "react";
import { api } from "../api/client";
import { announce } from "../lib/announce";
import { toggleTag } from "../lib/xbrlTags";
import type { XbrlTag } from "../types";

const PAGE = 50;
const TAXONOMIES = ["us-gaap", "ifrs-full", "dei"];
const tagIdOf = (t: XbrlTag) => `${t.taxonomy}:${t.concept}`;
const seenText = (n: number) =>
  n === 0 ? "not seen in any fetched company" : `used by ${n.toLocaleString()} ${n === 1 ? "company" : "companies"}`;

/** Multi-select over the whole tag registry (ARIA 1.2 combobox + listbox).
 * Options come from the server a page at a time as the user types; nothing
 * loads the registry whole. Chosen tags show as removable chips. */
export function TagCombobox({ selected, onChange }: { selected: string[]; onChange: (next: string[]) => void }) {
  const id = useId();
  const [q, setQ] = useState("");
  const [taxonomy, setTaxonomy] = useState("");
  const [extensionOnly, setExtensionOnly] = useState(false);
  const [seenOnly, setSeenOnly] = useState(false);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<XbrlTag[]>([]);
  const [total, setTotal] = useState(0);
  const [active, setActive] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0); // only the newest request may write results
  const input = useRef<HTMLInputElement>(null);
  const optId = (i: number) => `${id}-opt-${i}`;

  async function load(offset: number) {
    const mine = ++seq.current;
    setLoading(true);
    try {
      const res = await api.searchXbrlTags({ q, taxonomy, seenOnly, extensionOnly, offset, limit: PAGE });
      if (mine !== seq.current) return;
      setItems((prev) => (offset ? [...prev, ...res.items] : res.items));
      setTotal(res.total);
      setError(null);
      if (!offset) {
        setActive(-1);
        announce(res.total ? `${res.total.toLocaleString()} ${res.total === 1 ? "tag matches" : "tags match"}` : "No tag matches");
      }
    } catch (err) {
      if (mine !== seq.current) return;
      setError((err as Error).message);
      if (!offset) setItems([]);
      announce("Tag search failed");
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }

  // A new query or filter starts over at the first page, after a short pause in typing.
  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => load(0), 250);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, q, taxonomy, seenOnly, extensionOnly]);

  useEffect(() => {
    if (active >= 0) document.getElementById(optId(active))?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  const more = items.length < total;
  const loadMore = () => {
    if (more && !loading) load(items.length);
  };

  function remove(tag: string) {
    onChange(selected.filter((t) => t !== tag));
    announce(`Removed ${tag}`);
    input.current?.focus();
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      if (!open) setOpen(true);
      else if (active < items.length - 1) setActive(active + 1);
      else loadMore();
    } else if (e.key === "ArrowUp") {
      if (open) setActive(Math.max(active - 1, 0));
    } else if (e.key === "Enter") {
      if (!open || active < 0 || !items[active]) return;
      onChange(toggleTag(selected, tagIdOf(items[active])));
    } else if (e.key === "Escape") {
      if (open) setOpen(false);
      else setQ("");
    } else if (e.key === "Backspace") {
      if (q !== "" || !selected.length) return;
      remove(selected[selected.length - 1]);
    } else return;
    e.preventDefault();
  }

  const status = error
    ? `Tag search failed: ${error}`
    : loading && !items.length
      ? "Searching…"
      : !items.length
        ? q.trim()
          ? `No tag matches “${q.trim()}” with these filters.`
          : "No tags match these filters. If the registry is empty, update it below."
        : `Showing ${items.length.toLocaleString()} of ${total.toLocaleString()}${more ? "; scroll or press Down for more" : ""}.`;

  return (
    <div className="tag-combobox">
      <div className="inline-fields">
        <label className="field-label inline-label">
          Taxonomy
          <select value={taxonomy} onChange={(e) => setTaxonomy(e.target.value)}>
            <option value="">All taxonomies</option>
            {TAXONOMIES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        <label>
          <input type="checkbox" checked={extensionOnly} onChange={(e) => setExtensionOnly(e.target.checked)} />
          Company extensions only
        </label>
        <label>
          <input type="checkbox" checked={seenOnly} onChange={(e) => setSeenOnly(e.target.checked)} />
          Seen in fetched companies only
        </label>
      </div>

      <label className="field-label" htmlFor={`${id}-input`}>
        Find tags
      </label>
      <p className="help-text" id={`${id}-hint`}>
        Type part of a name or concept, e.g. revenue. Down and Up move through the list, Enter adds or removes a tag,
        Backspace in an empty box removes the last one.
      </p>
      <div
        className="tag-combobox-field"
        onBlur={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
        }}
      >
        <input
          ref={input}
          id={`${id}-input`}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={`${id}-list`}
          aria-activedescendant={open && active >= 0 ? optId(active) : undefined}
          aria-autocomplete="list"
          aria-describedby={`${id}-hint`}
          autoComplete="off"
          spellCheck={false}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onClick={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        <div className="tag-combobox-popup" hidden={!open}>
          <ul
            className="tag-combobox-list"
            id={`${id}-list`}
            role="listbox"
            aria-multiselectable="true"
            aria-label="Matching tags"
            // Keeps focus (and the active option) in the input while the mouse picks.
            onMouseDown={(e) => e.preventDefault()}
            onScroll={(e) => {
              const el = e.currentTarget;
              if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80) loadMore();
            }}
          >
            {items.map((t, i) => {
              const tid = tagIdOf(t);
              const isSelected = selected.includes(tid);
              return (
                <li
                  key={tid}
                  id={optId(i)}
                  role="option"
                  aria-selected={isSelected}
                  className={i === active ? "tag-option active" : "tag-option"}
                  onMouseMove={() => i !== active && setActive(i)}
                  onClick={() => onChange(toggleTag(selected, tid))}
                >
                  <span className="tag-option-check" aria-hidden="true">
                    {isSelected && (
                      <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.2">
                        <path d="M3 8.5 6.5 12 13 4.5" />
                      </svg>
                    )}
                  </span>
                  <span className="tag-option-body">
                    <span className="tag-option-label">{t.label ?? t.concept}</span>
                    <span className="tag-option-id">{tid}</span>
                    <span className="tag-option-meta">
                      {t.taxonomy} · {seenText(t.seen_count)}
                      {t.deprecated && " · Deprecated"}
                      {t.extension && " · Company extension"}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
          <p className={error ? "tag-combobox-status error-text" : "tag-combobox-status muted"}>{status}</p>
        </div>
      </div>

      {selected.length > 0 ? (
        <ul className="chip-row tag-chips" aria-label={`Chosen tags (${selected.length})`}>
          {selected.map((t) => (
            <li key={t}>
              <button type="button" className="tag-chip" aria-label={`Remove ${t}`} onClick={() => remove(t)}>
                {t}
                <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M4 4l8 8M12 4l-8 8" />
                </svg>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No tags chosen yet.</p>
      )}
    </div>
  );
}
