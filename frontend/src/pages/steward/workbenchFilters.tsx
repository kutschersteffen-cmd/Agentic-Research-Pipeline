import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import type { Column } from "../../lib/workbench";
import {
  amount,
  bounds,
  categoryOptions,
  chipText,
  effectiveN,
  effectiveRange,
  indicators,
  newFilter,
  type Filter,
  type Indicator,
  type SchemaField,
} from "../../lib/workbenchFilters";
import type { WorklistRow } from "../../types";

const Sim = () => <span className="sim-tag">Simulated</span>;

/** Step ② of the Workbench: Add filter ▾, one chip per indicator with the control its type needs, Clear filters. The
 * filters live in the screen (they stay when the scope changes); this only edits them. */
export function FilterBuilder({ rows, columns, filters, onChange }: { rows: WorklistRow[]; columns: Column[]; filters: Filter[]; onChange: (f: Filter[]) => void }) {
  const [schema, setSchema] = useState<SchemaField[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  // The schema is read once the rows are on screen, as the screen does with its other side reads.
  const haveRows = rows.length > 0;
  useEffect(() => {
    if (haveRows && !schema.length) api.getSimulatedSchema().then((s) => setSchema(s.fields), () => undefined);
  }, [haveRows, schema.length]);
  const list = useMemo(() => indicators(columns, schema, rows), [columns, schema, rows]);

  const pick = (ind: Indicator) => {
    if (!filters.some((f) => f.ind.id === ind.id)) onChange([...filters, newFilter(ind)]);
    setOpen(ind.id);
  };
  const update = (id: string, change: Partial<Filter>) => onChange(filters.map((f) => (f.ind.id === id ? { ...f, ...change } : f)));

  return (
    <div className="wb-filters">
      <AddFilterMenu indicators={list} onPick={pick} />
      {filters.map((f) => (
        <FilterChip
          key={f.ind.id}
          filter={f}
          rows={rows}
          open={open === f.ind.id}
          onToggle={() => setOpen(open === f.ind.id ? null : f.ind.id)}
          onClose={() => setOpen(null)}
          onChange={(c) => update(f.ind.id, c)}
          onRemove={() => onChange(filters.filter((x) => x !== f))}
        />
      ))}
      {filters.length > 0 ? (
        <button className="link-button wb-clear" onClick={() => onChange([])}>
          Clear filters
        </button>
      ) : (
        <span className="muted">No filter set.</span>
      )}
    </div>
  );
}

function AddFilterMenu({ indicators: list, onPick }: { indicators: Indicator[]; onPick: (i: Indicator) => void }) {
  const ref = useRef<HTMLDetailsElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const q = query.trim().toLocaleLowerCase();
  const shown = q ? list.filter((i) => i.label.toLocaleLowerCase().includes(q)) : list;
  return (
    <details ref={ref} className="wb-menu" onToggle={(e) => ((e.target as HTMLDetailsElement).open ? search.current?.focus() : setQuery(""))}>
      <summary>Add filter ▾</summary>
      <div className="wb-menu-panel wb-filter-menu" role="group" aria-label="Add filter">
        <input type="search" aria-label="Find an indicator" placeholder="Find an indicator" value={query} ref={search} onChange={(e) => setQuery(e.target.value)} />
        <div className="wb-filter-options">
          {shown.map((i) => (
            <button
              key={i.id}
              className="link-button wb-menu-item"
              onClick={() => {
                if (ref.current) ref.current.open = false;
                onPick(i);
              }}
            >
              {i.label}
              {i.simulated && <Sim />}
            </button>
          ))}
          {shown.length === 0 && <p className="muted">No indicator matches.</p>}
        </div>
      </div>
    </details>
  );
}

function FilterChip({
  filter: f, rows, open, onToggle, onClose, onChange, onRemove,
}: {
  filter: Filter;
  rows: WorklistRow[];
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  onChange: (c: Partial<Filter>) => void;
  onRemove: () => void;
}) {
  const text = chipText(f, rows);
  const chip = useRef<HTMLButtonElement>(null);
  const close = () => {
    onClose();
    chip.current?.focus();
  };
  return (
    <span className="wb-filter" onKeyDown={(e) => e.key === "Escape" && open && close()}>
      <span className="chip wb-sort-chip wb-filter-chip">
        <button ref={chip} className="link-button wb-filter-text" aria-expanded={open} title={text} onClick={onToggle}>
          {text}
        </button>
        <button className="link-button" aria-label={`Remove the ${f.ind.label} filter`} title="Remove this filter" onClick={onRemove}>
          ✕
        </button>
      </span>
      {open && (
        <div className="wb-menu-panel wb-filter-panel" role="group" aria-label={`Filter: ${f.ind.label}`}>
          <FilterControl filter={f} rows={rows} onChange={onChange} />
          <div className="wb-filter-foot">
            <label className="checkbox-label">
              <input type="checkbox" checked={f.includeEmpty} onChange={(e) => onChange({ includeEmpty: e.target.checked })} />
              Include empty
            </label>
            <button className="secondary" onClick={close}>
              Done
            </button>
          </div>
        </div>
      )}
    </span>
  );
}

function FilterControl({ filter: f, rows, onChange }: { filter: Filter; rows: WorklistRow[]; onChange: (c: Partial<Filter>) => void }) {
  const { ind } = f;
  const b = useMemo(() => (ind.kind === "range" || ind.kind === "count" || ind.kind === "days" ? bounds(ind, rows) : null), [ind, rows]);
  const options = useMemo(() => (ind.kind === "category" ? categoryOptions(ind, rows) : []), [ind, rows]);
  switch (ind.kind) {
    case "range": {
      if (!b) return <p className="muted">No company in this scope has a value.</p>;
      const d = ind.decimals ?? 2;
      const step = 10 ** -d;
      const eff = effectiveRange(f, b);
      const lo = eff.lo ?? b.min, hi = eff.hi ?? b.max;
      const round = (v: number) => Number(v.toFixed(d));
      // A handle at its bound stores null, so the full range follows the scope.
      const setLo = (v: number) => onChange({ lo: round(Math.min(v, hi)) <= b.min ? null : round(Math.min(v, hi)) });
      const setHi = (v: number) => onChange({ hi: round(Math.max(v, lo)) >= b.max ? null : round(Math.max(v, lo)) });
      return (
        <>
          <div className="wb-range">
            <input type="range" aria-label={`Lowest ${ind.label}`} aria-valuetext={amount(lo, ind)} min={b.min} max={b.max} step={step} value={lo} onChange={(e) => setLo(Number(e.target.value))} />
            <input type="range" aria-label={`Highest ${ind.label}`} aria-valuetext={amount(hi, ind)} min={b.min} max={b.max} step={step} value={hi} onChange={(e) => setHi(Number(e.target.value))} />
          </div>
          <div className="wb-range-boxes">
            <NumberBox label={`Lowest ${ind.label}`} value={lo} decimals={d} min={b.min} max={b.max} onChange={setLo} />
            <span aria-hidden="true">–</span>
            <NumberBox label={`Highest ${ind.label}`} value={hi} decimals={d} min={b.min} max={b.max} onChange={setHi} />
            {ind.unit && <span className="muted">{ind.unit}</span>}
          </div>
          <p className="muted wb-range-ends">
            In this scope: {amount(b.min, ind)} to {amount(b.max, ind)}
          </p>
        </>
      );
    }
    case "count":
    case "days": {
      const n = effectiveN(f, b);
      const max = b?.max ?? n;
      const words = ind.kind === "count" ? `At least ${n}` : `At most ${n} days`;
      return (
        <label className="wb-slider-label">
          <span>{words}</span>
          <input type="range" aria-label={ind.label} aria-valuetext={words} min={0} max={max} step={1} value={n} onChange={(e) => onChange({ n: Number(e.target.value) })} />
          <span className="muted">0 to {max}</span>
        </label>
      );
    }
    case "yesno":
      return (
        <div className="wb-checks">
          <label className="checkbox-label">
            <input type="checkbox" checked={f.yes} onChange={(e) => onChange({ yes: e.target.checked })} />
            Yes
          </label>
          <label className="checkbox-label">
            <input type="checkbox" checked={f.no} onChange={(e) => onChange({ no: e.target.checked })} />
            No
          </label>
        </div>
      );
    case "category":
      return options.length ? (
        <div className="wb-checks wb-checklist">
          {options.map((o) => (
            <label key={o} className="checkbox-label">
              <input
                type="checkbox"
                checked={f.values.includes(o)}
                onChange={(e) => onChange({ values: e.target.checked ? [...f.values, o] : f.values.filter((x) => x !== o) })}
              />
              {o}
            </label>
          ))}
        </div>
      ) : (
        <p className="muted">No company in this scope has a value.</p>
      );
    case "text":
      return <input type="search" aria-label={`${ind.label} contains`} placeholder="Contains, any case" value={f.text} autoFocus onChange={(e) => onChange({ text: e.target.value })} />;
  }
}

/** A number box that lets the user type freely and applies each complete number as it is typed. */
function NumberBox({ label, value, decimals, min, max, onChange }: { label: string; value: number; decimals: number; min: number; max: number; onChange: (v: number) => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <input
      type="number"
      aria-label={label}
      step={10 ** -decimals}
      min={min}
      max={max}
      value={draft ?? value.toFixed(decimals)}
      onFocus={() => setDraft(value.toFixed(decimals))}
      onBlur={() => setDraft(null)}
      onChange={(e) => {
        setDraft(e.target.value);
        const v = Number(e.target.value);
        if (e.target.value.trim() !== "" && Number.isFinite(v)) onChange(v);
      }}
    />
  );
}
