import { GroundedBadge } from "./ConfidenceBadge";
import type { ActivityDefinition } from "../types";

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
          <button className="link-button" onClick={() => remove(idx)}>
            Remove activity
          </button>
        </div>
      ))}
    </>
  );
}
