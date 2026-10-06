import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { OutputItem, OutputKind } from "../types";

// Statuses a downstream step can rely on; the first such output is the default pick. Anything else (a draft, a
// failed run) stays pickable but is marked.
const USABLE = new Set(["published", "ratified", "approved", "completed", "partially_completed", "saved"]);

const outputLabel = (o: OutputItem): string =>
  [
    `${o.name}${o.version != null ? ` v${o.version}` : ""}`,
    o.as_of ? o.as_of.slice(0, 10) : null,
    USABLE.has(o.status) ? (o.status === "saved" || o.status === "completed" ? null : o.status) : o.status.replace(/_/g, " ").toUpperCase(),
    o.by,
  ]
    .filter(Boolean)
    .join(" · ");

interface Props {
  kind: OutputKind;
  label: string;
  value: string;
  onChange: (item: OutputItem | null) => void;
  /** Narrow the list, e.g. runs of one type. */
  filter?: (o: OutputItem) => boolean;
  /** Pick the newest usable output as soon as the list loads (only while nothing is picked). */
  autoSelect?: boolean;
}

/** One way to pick any stored output another step produced: newest first, with its date, status and author, from
 * the output catalog. Drafts and unfinished runs stay pickable but are marked. */
export function InputPicker({ kind, label, value, onChange, filter, autoSelect = false }: Props) {
  const [items, setItems] = useState<OutputItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listOutputs(kind).then((r) => setItems(r.outputs), (e: Error) => setError(e.message));
  }, [kind]);

  const shown = (items ?? []).filter((o) => !filter || filter(o));
  useEffect(() => {
    if (!autoSelect || value || !items) return;
    const first = shown.find((o) => USABLE.has(o.status));
    if (first) onChange(first);
    // `shown` is derived from `items`; re-running on it would re-pick after the user clears the field.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, autoSelect]);

  if (error) return <p className="error-text" role="alert">{label}: {error}</p>;
  return (
    <label className="field-label">
      {label}
      <select value={value} onChange={(e) => onChange(shown.find((o) => o.id === e.target.value) ?? null)} disabled={!items}>
        <option value="">{!items ? "Loading…" : shown.length === 0 ? "Nothing saved yet" : "Select…"}</option>
        {shown.map((o) => (
          <option key={o.id} value={o.id}>
            {outputLabel(o)}
          </option>
        ))}
      </select>
    </label>
  );
}
