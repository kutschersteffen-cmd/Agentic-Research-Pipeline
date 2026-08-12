import { GroundedBadge } from "./ConfidenceBadge";
import type { ActivityDefinition, ActivityStandardsMapping } from "../types";

function CodeList({ label, codes }: { label: string; codes: { code: string; label: string }[] }) {
  if (codes.length === 0) return null;
  return (
    <span className="standards-chip">
      <strong>{label}:</strong> {codes.map((c) => `${c.code}${c.label ? ` (${c.label})` : ""}`).join(", ")}
    </span>
  );
}

function StandardsMappingDisplay({ mapping }: { mapping: ActivityStandardsMapping }) {
  const hasAny = mapping.nace_codes.length || mapping.naics_codes.length || mapping.sic_codes.length || mapping.gics.length;
  if (!hasAny && mapping.unmapped_isic_codes.length === 0) return null;
  return (
    <div className="standards-mapping">
      <CodeList label="NACE" codes={mapping.nace_codes} />
      <CodeList label="NAICS" codes={mapping.naics_codes} />
      <CodeList label="SIC" codes={mapping.sic_codes} />
      {mapping.gics.length > 0 && (
        <span className="standards-chip">
          <strong>GICS:</strong>{" "}
          {mapping.gics.map((g, i) => (
            <span key={g.code} title={g.rationale}>
              {i > 0 && ", "}
              {g.code} ({g.label})
            </span>
          ))}{" "}
          <span className="muted">[LLM-classified]</span>
        </span>
      )}
      {mapping.unmapped_isic_codes.length > 0 && (
        <span className="standards-chip muted">No crosswalk entry for ISIC {mapping.unmapped_isic_codes.join(", ")}</span>
      )}
    </div>
  );
}

interface Props {
  activities: ActivityDefinition[];
  onChange: (activities: ActivityDefinition[]) => void;
}

/** The editable in-scope/out-of-scope activity list shared by every taxonomy
 * draft review surface (new-taxonomy wizard, merge review, library detail
 * edit) -- each activity optionally carries a verbatim source_citation when
 * it was extracted from an authority document, shown as a grounded quote
 * rather than trusted on the model's say-so alone. */
export function ActivityEditorTable({ activities, onChange }: Props) {
  function update(idx: number, patch: Partial<ActivityDefinition>) {
    onChange(activities.map((a, i) => (i === idx ? { ...a, ...patch } : a)));
  }

  function remove(idx: number) {
    onChange(activities.filter((_, i) => i !== idx));
  }

  return (
    <>
      {activities.map((a, idx) => (
        <div className="activity-editor" key={a.activity_id}>
          <input value={a.name} onChange={(e) => update(idx, { name: e.target.value })} />
          <label className="field-label">In scope</label>
          <textarea rows={2} value={a.in_scope_description} onChange={(e) => update(idx, { in_scope_description: e.target.value })} />
          <label className="field-label">Out of scope</label>
          <textarea
            rows={2}
            value={a.out_of_scope_description}
            onChange={(e) => update(idx, { out_of_scope_description: e.target.value })}
          />
          <label className="field-label">Seed keywords (comma-separated)</label>
          <input
            value={a.seed_keywords.join(", ")}
            onChange={(e) => update(idx, { seed_keywords: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
          />
          {a.source_citation && (
            <p className="muted">
              <GroundedBadge grounded={a.source_citation.grounded} /> source: "{a.source_citation.quote}"
            </p>
          )}
          {a.standards_mapping && <StandardsMappingDisplay mapping={a.standards_mapping} />}
          <button className="link-button" onClick={() => remove(idx)}>
            Remove activity
          </button>
        </div>
      ))}
    </>
  );
}
