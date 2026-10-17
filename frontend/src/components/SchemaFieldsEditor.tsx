import type { FieldDefinition } from "../types";

/** `markers`: a read-only rules note per field id (from the Rules list); clicking one calls `onMarkerClick`. */
export function SchemaFieldsEditor({
  fields,
  onChange,
  markers = {},
  onMarkerClick,
}: {
  fields: FieldDefinition[];
  onChange: (fields: FieldDefinition[]) => void;
  markers?: Record<string, string>;
  onMarkerClick?: (fieldId: string) => void;
}) {
  const update = (idx: number, patch: Partial<FieldDefinition>) =>
    onChange(fields.map((f, i) => (i === idx ? { ...f, ...patch } : f)));

  return (
    <>
    {fields.map((f, idx) => (
      <div className="activity-editor" key={f.field_id}>
        <input aria-label={`Field ${idx + 1} name`} value={f.name} onChange={(e) => update(idx, { name: e.target.value })} />
        {markers[f.field_id] && (
          <button type="button" className="secondary rules-marker" onClick={() => onMarkerClick?.(f.field_id)}>
            {markers[f.field_id]}
          </button>
        )}
        <label className="field-label">
          Description
          <textarea rows={2} value={f.description} onChange={(e) => update(idx, { description: e.target.value })} />
        </label>
        <label className="field-label">
          Extraction instructions
          <textarea
            rows={3}
            value={f.extraction_instructions}
            onChange={(e) => update(idx, { extraction_instructions: e.target.value })}
          />
        </label>
        <div className="field-label">Data type / unit</div>
        <div className="inline-fields">
          <span>{f.data_type}</span>
          <input
            aria-label={`Field ${idx + 1} unit`}
            placeholder="unit"
            value={f.unit ?? ""}
            onChange={(e) => update(idx, { unit: e.target.value })}
          />
        </div>
        <label className="field-label">
          Seed keywords (comma-separated)
          <input
            value={f.seed_keywords.join(", ")}
            onChange={(e) => update(idx, { seed_keywords: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
          />
        </label>
      </div>
    ))}
    </>
  );
}
