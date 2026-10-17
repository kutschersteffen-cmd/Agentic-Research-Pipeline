import { useRef, useState } from "react";
import { api } from "../../api/client";
import { ruleMarkers, RulesList } from "../../components/RulesList";
import { SchemaFieldsEditor } from "../../components/SchemaFieldsEditor";
import { addCustomJob, jobReady, removeJob, type CustomJob, type Job } from "../../lib/jobs";
import { ruleInputs, sameRule } from "../../lib/ruleSentence";
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
  const [suggesting, setSuggesting] = useState<Record<string, boolean>>({});
  const [ruleErrors, setRuleErrors] = useState<Record<string, string | null>>({});
  // Patches after an await must apply to the jobs as they are then, not as they were at the click.
  const latest = useRef(jobs);
  latest.current = jobs;
  const custom = jobs.filter((j): j is CustomJob => j.profile === "custom");
  const setError = (id: string, e: string | null) => setErrors((s) => ({ ...s, [id]: e }));
  const patch = (id: string, p: Partial<CustomJob>) =>
    onChange(latest.current.map((j) => (j.id === id && j.profile === "custom" ? { ...j, ...p } : j)));

  async function draft(j: CustomJob) {
    setBusy((s) => ({ ...s, [j.id]: true }));
    setError(j.id, null);
    let schema: DataPointSchema;
    try {
      schema = (await api.draftSchema(j.request)) as DataPointSchema;
      patch(j.id, { schema, confirmed: false, waiting: [] });
    } catch (err) {
      setError(j.id, (err as Error).message);
      return;
    } finally {
      setBusy((s) => ({ ...s, [j.id]: false }));
    }
    await suggest(j.id, schema);
  }

  /** New suggestions replace the waiting ones, minus any matching an accepted rule or one dropped this session. */
  async function suggest(id: string, schema: DataPointSchema) {
    setSuggesting((s) => ({ ...s, [id]: true }));
    setRuleErrors((s) => ({ ...s, [id]: null }));
    try {
      const res = await api.suggestRules(schema);
      const now = latest.current.find((x): x is CustomJob => x.id === id && x.profile === "custom");
      if (now?.schema?.schema_id !== schema.schema_id) return; // a new draft replaced the schema these rules name
      const known = [
        ...now.schema.fields.flatMap((f) => (f.rules ?? []).map((rule) => ({ fieldId: f.field_id, rule }))),
        ...(now.dropped ?? []).map((d) => ({ fieldId: d.field_id, rule: d.rule })),
      ];
      const helpers = res.helper_fields ?? [];
      const waiting = (res.rules ?? [])
        .filter((s) => !known.some((k) => sameRule(k, { fieldId: s.field_id, rule: s.rule })))
        .map((s) => ({ ...s, helper_fields: helpers.filter((h) => h.field_id === s.field_id || ruleInputs(s.rule).includes(h.field_id)) }));
      patch(id, { waiting, ...(waiting.length ? { confirmed: false } : {}) });
    } catch (err) {
      setRuleErrors((s) => ({ ...s, [id]: `Rule suggestions failed: ${(err as Error).message}` }));
    } finally {
      setSuggesting((s) => ({ ...s, [id]: false }));
    }
  }

  /** A field marker's target: the field's first rule, else the first rule that reads it. */
  function showRules(jobId: string, fieldId: string) {
    const list = document.getElementById(`rules-${jobId}`);
    const id = CSS.escape(fieldId);
    const el = list?.querySelector<HTMLElement>(`[data-field="${id}"]`) ?? list?.querySelector<HTMLElement>(`[data-reads~="${id}"]`);
    el?.scrollIntoView({ block: "center" });
    el?.focus({ preventScroll: true });
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
          <button onClick={() => draft(j)} disabled={busy[j.id] || suggesting[j.id] || !j.request.trim()}>
            Draft extraction schema
          </button>{" "}
          <button onClick={() => remove(j.id)}>Remove</button>
          <p className="help-text">Or skip this and build a schema entirely by hand before starting a run.</p>
          {errors[j.id] && <p className="error-text" role="alert">{errors[j.id]}</p>}
          {j.schema && (
            <>
              <h2>Review &amp; edit fields</h2>
              <SchemaFieldsEditor
                fields={j.schema.fields}
                onChange={(fields) => patch(j.id, { schema: { ...j.schema!, fields }, confirmed: false })}
                markers={ruleMarkers(j.schema, j.waiting ?? [])}
                onMarkerClick={(fieldId) => showRules(j.id, fieldId)}
              />
              <div id={`rules-${j.id}`}>
                <RulesList
                  schema={j.schema}
                  waiting={j.waiting ?? []}
                  busy={!!(busy[j.id] || suggesting[j.id])}
                  onSuggestAgain={() => suggest(j.id, j.schema!)}
                  onChange={(n) =>
                    patch(j.id, { schema: n.schema, waiting: n.waiting, dropped: [...(j.dropped ?? []), ...n.dropped], ...(n.schema !== j.schema ? { confirmed: false } : {}) })
                  }
                />
              </div>
              {ruleErrors[j.id] && <p className="error-text" role="alert">{ruleErrors[j.id]}</p>}
              <div className="toolbar">
                {j.confirmed === false ? (
                  <button onClick={() => patch(j.id, { confirmed: true })} disabled={!j.schema.fields.length || !!j.waiting?.length}>
                    {j.waiting?.length
                      ? `${j.waiting.length} rule ${j.waiting.length === 1 ? "suggestion" : "suggestions"} waiting`
                      : `Confirm schema (${j.schema.fields.length} fields)`}
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
