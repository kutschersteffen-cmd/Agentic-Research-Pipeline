import { useState } from "react";
import { api } from "../../api/client";
import { SchemaFieldsEditor } from "../../components/SchemaFieldsEditor";
import { addCustomJob, jobReady, removeJob, type CustomJob, type Job } from "../../lib/jobs";
import type { DataPointSchema } from "../../types";

export const DEFAULT_CRITERIA =
  "Green capex: total green/sustainable capital expenditure in USD/EUR millions for the most recent fiscal " +
  "year, and as a % of total capex. Separately capture: (a) whether reported per the EU Taxonomy (eligible vs " +
  "aligned) vs. a self-defined/internal definition -- both if disclosed, clearly labeled; (b) breakdown by EU " +
  "Taxonomy environmental objective (climate mitigation, adaptation, water, circular economy, pollution, " +
  "biodiversity) where disclosed; (c) the company's own stated definition/methodology as a separate string " +
  "field with its own citation; (d) prior-year comparative figure; (e) forward-looking green capex " +
  "targets/guidance as a SEPARATE field from the actual reported figure -- extraction_instructions must " +
  "explicitly forbid conflating a target with an actual reported number.";

interface Props {
  jobs: Job[];
  onChange: (jobs: Job[]) => void;
  /** Opens Extract once every schema is confirmed. */
  onNext: () => void;
  nextCustomId: () => string;
  defaultRequest: string;
}

export function SchemaPanel({ jobs, onChange, onNext, nextCustomId, defaultRequest }: Props) {
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const custom = jobs.filter((j): j is CustomJob => j.profile === "custom");
  const setError = (id: string, e: string | null) => setErrors((s) => ({ ...s, [id]: e }));
  const patch = (id: string, p: Partial<CustomJob>) => onChange(jobs.map((j) => (j.id === id && j.profile === "custom" ? { ...j, ...p } : j)));

  async function draft(j: CustomJob) {
    setBusy((s) => ({ ...s, [j.id]: true }));
    setError(j.id, null);
    try {
      patch(j.id, { schema: (await api.draftSchema(j.request)) as DataPointSchema, confirmed: false });
    } catch (err) {
      setError(j.id, (err as Error).message);
    } finally {
      setBusy((s) => ({ ...s, [j.id]: false }));
    }
  }

  function remove(id: string) {
    const r = removeJob(jobs, id);
    setError(id, r.error);
    if (!r.error) onChange(r.jobs);
  }

  return (
    <>
      {custom.map((j, i) => (
        <section className="card" key={j.id} aria-label={`Schema ${i + 1}`}>
          <h2>{custom.length > 1 ? `Schema ${i + 1}: describe what to extract` : "Describe what to extract"}</h2>
          <label className="field-label">
            Research request
            <textarea rows={2} value={j.request} placeholder={defaultRequest} onChange={(e) => patch(j.id, { request: e.target.value })} />
          </label>
          <button onClick={() => draft(j)} disabled={busy[j.id] || !j.request.trim()}>
            Draft extraction schema
          </button>{" "}
          <button onClick={() => remove(j.id)}>Remove</button>
          <p className="help-text">Or skip this and build a schema entirely by hand before starting a run.</p>
          {errors[j.id] && <p className="error-text" role="alert">{errors[j.id]}</p>}
          {j.schema && (
            <>
              <h2>Review &amp; edit fields</h2>
              <SchemaFieldsEditor fields={j.schema.fields} onChange={(fields) => patch(j.id, { schema: { ...j.schema!, fields }, confirmed: false })} />
              <div className="toolbar">
                {j.confirmed === false ? (
                  <button onClick={() => patch(j.id, { confirmed: true })} disabled={!j.schema.fields.length}>
                    Confirm schema ({j.schema.fields.length} fields)
                  </button>
                ) : (
                  <span className="status-text" role="status">{"✓"} Schema confirmed. Editing a field asks for confirmation again.</span>
                )}
              </div>
            </>
          )}
        </section>
      ))}
      <div className="toolbar">
        <button className="secondary" onClick={() => onChange(addCustomJob(jobs, nextCustomId(), ""))}>Add another schema</button>
        <button onClick={onNext} disabled={!custom.every(jobReady)}>
          {custom.every(jobReady) ? "Next: Extract →" : "Confirm every schema to continue"}
        </button>
      </div>
    </>
  );
}
