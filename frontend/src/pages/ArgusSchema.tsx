import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { BatchToggle } from "../components/BatchToggle";
import { ruleMarkers, RulesList } from "../components/RulesList";
import { ScoringTemplatePicker } from "../components/RunScoring";
import { SchemaFieldsEditor } from "../components/SchemaFieldsEditor";
import { ruleInputs, sameRule } from "../lib/ruleSentence";
import { canStart, flowHref, newDocsLine, newestVersions, startLabel } from "../lib/argusFlow";
import type { ArgusFlow as Flow, DataPointSchema, FieldDefinition, RuleSuggestion } from "../types";

type SavedSchema = { schema_id: string; version: number; name: string; release_flag: boolean };
type Preset = { preset_id: string; name: string; field_count: number };
type Choice = NonNullable<Flow["schema_choice"]>;
const PROFILES: ["financials" | "tnfd", string][] = [
  ["financials", "Financials"],
  ["tnfd", "TNFD"],
];

const asChoice = (c: Partial<Choice> & Pick<Choice, "kind">): Choice => ({ schema_id: null, version: null, profile: null, ...c });

const blankField = (n: number): FieldDefinition => ({
  field_id: `field_${n}`, name: "", description: "", data_type: "number", unit: null, extraction_instructions: "", required: false,
  source_doc_types: [], seed_keywords: [],
});

/** Step 3 of an Argus flow: what to extract, its fields, optional settings, the repeat warning and the start. */
export function ArgusSchema({ flow, busy, act }: { flow: Flow; busy: boolean; act: (fn: () => Promise<Flow | void>) => void }) {
  const [saved, setSaved] = useState<SavedSchema[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [schema, setSchema] = useState<DataPointSchema | null>(null);
  const [editing, setEditing] = useState<DataPointSchema | null>(null); // unsaved fields: drafted, added or being edited
  // Rule suggestions for the unsaved fields: waiting ones block saving; dropped ones are not suggested again.
  const [waiting, setWaiting] = useState<RuleSuggestion[]>([]);
  const [dropped, setDropped] = useState<RuleSuggestion[]>([]);
  const [suggesting, setSuggesting] = useState(false);
  const [ruleError, setRuleError] = useState("");
  const latest = useRef(editing); // patches after an await apply to the fields as they are then
  latest.current = editing;
  const [words, setWords] = useState("");
  const [role, setRole] = useState<string | null>(null);
  const [loadError, setLoadError] = useState("");
  const [evidence, setEvidence] = useState(flow.settings.evidence_passages?.toString() ?? ""); // saved on blur and before Start
  const starting = useRef(false);
  const id = flow.flow_id;
  const choice = flow.schema_choice ?? null;

  useEffect(() => {
    api.listSchemas().then((s) => setSaved(newestVersions(s)), (e: Error) => setLoadError(e.message));
    api.listPresets().then(setPresets, (e: Error) => setLoadError(e.message));
    api.getMe().then((m) => setRole(m.role), () => setRole(null));
  }, []);
  useEffect(() => {
    setSchema(null);
    if (choice?.kind !== "schema" || !choice.schema_id || !choice.version) return;
    let live = true; // a slower answer for an earlier choice must not replace this one
    api.getSchema(choice.schema_id, choice.version).then((s) => live && setSchema(s), (e: Error) => live && setLoadError(e.message));
    return () => {
      live = false;
    };
  }, [choice?.kind, choice?.schema_id, choice?.version]);

  const choose = (c: Partial<Choice> & Pick<Choice, "kind">) =>
    act(async () => {
      edit(null);
      return api.patchArgusFlow(id, { schema_choice: asChoice(c), repeat: {} });
    });
  const saveEditing = () =>
    act(async () => {
      if (!editing) return;
      const s = await api.registerSchema({ ...editing, fields: editing.fields.filter((f) => f.name.trim()) });
      edit(null);
      setSaved(newestVersions(await api.listSchemas()));
      return api.patchArgusFlow(id, { schema_choice: asChoice({ kind: "schema", schema_id: s.schema_id, version: s.version ?? 1 }), repeat: {} });
    });
  const edit = (s: DataPointSchema | null) => {
    setEditing(s);
    setWaiting([]);
    setDropped([]);
    setRuleError("");
  };
  /** New suggestions replace the waiting ones, minus any matching an accepted rule or one dropped this session. */
  async function suggest(s: DataPointSchema) {
    setSuggesting(true);
    setRuleError("");
    try {
      const res = await api.suggestRules(s);
      const now = latest.current;
      if (now?.schema_id !== s.schema_id) return; // a new draft replaced the fields these rules name
      const known = [
        ...now.fields.flatMap((f) => (f.rules ?? []).map((rule) => ({ fieldId: f.field_id, rule }))),
        ...dropped.map((d) => ({ fieldId: d.field_id, rule: d.rule })),
      ];
      const helpers = res.helper_fields ?? [];
      setWaiting(
        (res.rules ?? [])
          .filter((r) => !known.some((k) => sameRule(k, { fieldId: r.field_id, rule: r.rule })))
          .map((r) => ({ ...r, helper_fields: helpers.filter((h) => h.field_id === r.field_id || ruleInputs(r.rule).includes(h.field_id)) })),
      );
    } catch (err) {
      setRuleError(`Rule suggestions failed: ${(err as Error).message}`);
    } finally {
      setSuggesting(false);
    }
  }
  /** A field marker's target: the field's first rule, else the first rule that reads it. */
  function showRules(fieldId: string) {
    const list = document.getElementById("argus-rules");
    const fid = CSS.escape(fieldId);
    const el = list?.querySelector<HTMLElement>(`[data-field="${fid}"]`) ?? list?.querySelector<HTMLElement>(`[data-reads~="${fid}"]`);
    el?.scrollIntoView({ block: "center" });
    el?.focus({ preventScroll: true });
  }

  const evidenceValue = () => (evidence.trim() ? Number(evidence) : null);
  const shown = editing ?? schema;
  const profileName = choice?.kind === "profile" ? PROFILES.find(([p]) => p === choice.profile)?.[1] ?? "" : "";
  const keptBy = new Map<string, number>();
  // as the run counts them: kept files with a content key (every stored file has one)
  for (const f of flow.files) if (f.state === "kept" && f.content_key) keptBy.set(f.company_id, (keptBy.get(f.company_id) ?? 0) + 1);
  const same = flow.repeat_rows.filter((r) => r.kind === "same");
  const skipped = (cid: string) => flow.repeat[cid] === "skip" && same.some((r) => r.company_id === cid); // a stale Skip counts for nothing
  const companies = flow.companies.filter((c) => keptBy.has(c.company_id) && !skipped(c.company_id));
  const added = new Map(flow.repeat_rows.filter((r) => r.kind === "added").map((r) => [r.company_id, r.added]));
  const nameOf = (cid: string) => flow.companies.find((c) => c.company_id === cid)?.name ?? cid;
  const released = choice?.kind === "profile" || !!schema?.release_flag;
  const label = choice
    ? startLabel(choice.kind === "profile" ? profileName : schema?.name ?? null, choice.kind === "profile" ? null : choice.version ?? null, released, companies.length)
    : "Choose what to extract";
  const ready = !!choice && !editing && (choice.kind === "profile" || !!schema) && companies.length > 0 && canStart(flow.repeat_rows, flow.repeat);
  const runType = choice?.kind === "profile" ? choice.profile! : "extraction";
  const isChosen = (s: SavedSchema) => choice?.kind === "schema" && choice.schema_id === s.schema_id && choice.version === s.version;

  return (
    <div className="argus-schema">
      {loadError && <p className="error-text" role="alert">{loadError}</p>}
      <div className="argus-schema-cols">
        <section className="card argus-schema-pick" aria-label="What to extract">
          <h2>Saved schemas</h2>
          {saved.length === 0 ? (
            <p className="muted">None saved yet.</p>
          ) : (
            <ul className="argus-pick-list">
              {saved.map((s) => (
                <li key={`${s.schema_id}:${s.version}`}>
                  <button type="button" className="link-button" aria-pressed={isChosen(s)} disabled={busy} onClick={() => choose({ kind: "schema", schema_id: s.schema_id, version: s.version })}>
                    {s.name} <span className="mono">v{s.version}</span>
                  </button>{" "}
                  <span className="muted">{s.release_flag ? "released" : "draft"}</span>
                </li>
              ))}
            </ul>
          )}
          <h2>Templates</h2>
          <ul className="argus-pick-list">
            {presets.map((p) => (
              <li key={p.preset_id}>
                <button
                  type="button"
                  className="link-button"
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      const s = await api.installPreset(p.preset_id);
                      edit(null);
                      setSaved(newestVersions(await api.listSchemas()));
                      return api.patchArgusFlow(id, { schema_choice: asChoice({ kind: "schema", schema_id: s.schema_id, version: s.version }), repeat: {} });
                    })
                  }
                >
                  {p.name}
                </button>{" "}
                <span className="muted">{p.field_count} fields</span>
              </li>
            ))}
            {PROFILES.map(([p, name]) => (
              <li key={p}>
                <button type="button" className="link-button" aria-pressed={choice?.kind === "profile" && choice.profile === p} disabled={busy} onClick={() => choose({ kind: "profile", profile: p })}>
                  {name}
                </button>{" "}
                <span className="muted">fixed fields</span>
              </li>
            ))}
          </ul>
          <h2>Describe it in words</h2>
          <label className="field-label">
            What should be extracted?
            <textarea id="argus-describe" rows={3} value={words} onChange={(e) => setWords(e.target.value)} placeholder="e.g. green capex and its share of total capex" />
          </label>
          <button
            type="button"
            className="secondary"
            disabled={busy || suggesting || !words.trim()}
            onClick={() =>
              act(async () => {
                const drafted = (await api.draftSchema(words)) as DataPointSchema;
                edit(drafted);
                latest.current = drafted;
                void suggest(drafted);
              })
            }
          >
            Draft fields
          </button>
        </section>

        <section className="argus-schema-fields" aria-label="Fields">
          {choice?.kind === "profile" && !editing ? (
            <p className="muted">{profileName} is a fixed profile: its fields are set by the app and cannot be edited here.</p>
          ) : !shown ? (
            <p className="muted">Choose a saved schema or a template, or describe what to extract.</p>
          ) : (
            <>
              <h2>
                {shown.name}
                {!editing && schema && <span className="muted"> v{schema.version} · {schema.release_flag ? "released" : "draft"}</span>}
                {editing && <span className="muted"> · not saved</span>}
              </h2>
              {editing ? (
                <>
                  <SchemaFieldsEditor
                    fields={editing.fields}
                    onChange={(fields) => setEditing({ ...editing, fields })}
                    markers={ruleMarkers(editing, waiting)}
                    onMarkerClick={showRules}
                  />
                  <div id="argus-rules">
                    <RulesList
                      schema={editing}
                      waiting={waiting}
                      busy={busy || suggesting}
                      onSuggestAgain={() => suggest(editing)}
                      onChange={(n) => {
                        setEditing(n.schema);
                        setWaiting(n.waiting);
                        setDropped([...dropped, ...n.dropped]);
                      }}
                    />
                  </div>
                  {suggesting && <p className="muted" role="status">Suggesting rules…</p>}
                  {ruleError && <p className="error-text" role="alert">{ruleError}</p>}
                </>
              ) : (
                <div className="table-wrap">
                  <table className="data-table stack-on-phone" aria-label="Fields to extract">
                    <thead>
                      <tr>
                        <th scope="col">Field</th>
                        <th scope="col">Type</th>
                        <th scope="col">Unit</th>
                        <th scope="col">What it means</th>
                        <th scope="col">Look in</th>
                      </tr>
                    </thead>
                    <tbody>
                      {shown.fields.map((f) => (
                        <tr key={f.field_id}>
                          <td data-label="Field">{f.name}</td>
                          <td data-label="Type" className="mono">{f.data_type}</td>
                          <td data-label="Unit">{f.unit || "—"}</td>
                          <td data-label="What it means">{f.description || "—"}</td>
                          <td data-label="Look in">{f.extraction_instructions || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="row-actions">
                <button type="button" className="secondary" disabled={busy} onClick={() => setEditing({ ...(editing ?? shown), fields: [...(editing ?? shown).fields, blankField((editing ?? shown).fields.length + 1)] })}>
                  Add field
                </button>
                {editing ? (
                  <>
                    <button type="button" disabled={busy || suggesting || waiting.length > 0 || !editing.fields.some((f) => f.name.trim())} onClick={saveEditing}>
                      {waiting.length
                        ? `${waiting.length} rule ${waiting.length === 1 ? "suggestion" : "suggestions"} waiting`
                        : schema && editing.schema_id === schema.schema_id ? `Save as v${(schema.version ?? 0) + 1}` : "Save as a draft schema"}
                    </button>
                    <button type="button" className="link-button" onClick={() => edit(null)}>Cancel</button>
                  </>
                ) : (
                  schema && (
                    <>
                      <button type="button" className="secondary" disabled={busy} onClick={() => edit(schema)}>
                        Edit as v{(schema.version ?? 0) + 1}
                      </button>
                      {!schema.release_flag && role === "approver" && (
                        <button type="button" className="secondary" disabled={busy} onClick={() => act(async () => {
                          setSchema(await api.releaseSchema(schema.schema_id, schema.version ?? 1));
                          setSaved(newestVersions(await api.listSchemas()));
                        })}>
                          Release
                        </button>
                      )}
                    </>
                  )
                )}
              </div>
            </>
          )}
        </section>
      </div>

      <details className="card argus-settings">
        <summary>Settings (optional)</summary>
        <div className="argus-settings-body">
          <label className="field-label">
            Quality
            <select id="argus-mode" value={flow.settings.mode} disabled={busy} onChange={(e) => act(() => api.patchArgusFlow(id, { settings: { ...flow.settings, mode: e.target.value as Flow["settings"]["mode"] } }))}>
              <option value="cheap">Cheap</option>
              <option value="normal">Normal</option>
              <option value="max">Max</option>
            </select>
          </label>
          <label className="field-label">
            Evidence passages
            <input
              id="argus-evidence"
              type="number"
              min={1}
              max={50}
              value={evidence}
              placeholder="app default"
              onChange={(e) => setEvidence(e.target.value)}
              onBlur={() => {
                const v = evidenceValue();
                if (v !== (flow.settings.evidence_passages ?? null)) act(() => api.patchArgusFlow(id, { settings: { ...flow.settings, evidence_passages: v } }));
              }}
            />
          </label>
          <BatchToggle checked={flow.settings.batch} onChange={(batch) => act(() => api.patchArgusFlow(id, { settings: { ...flow.settings, batch } }))} />
          {choice && (
            <ScoringTemplatePicker
              runType={runType}
              fieldNames={schema?.fields.map((f) => f.name)}
              value={flow.settings.decision_framework_id ?? null}
              onChange={(fw) => act(() => api.patchArgusFlow(id, { settings: { ...flow.settings, decision_framework_id: fw, decision_framework_version: null } }))}
            />
          )}
        </div>
      </details>

      {same.length > 0 && (
        <section className="banner banner-warning argus-repeat" aria-label="Extracted before from the same files">
          <p>These companies were extracted before with this version from the same files. Choose for each one:</p>
          <ul>
            {same.map((r) => (
              <li key={r.company_id}>
                <span>
                  <strong>{nameOf(r.company_id)}</strong> · {r.date} · {r.approved} approved · {r.waiting} waiting
                </span>
                <span className="argus-repeat-choices">
                  <button type="button" className="secondary" aria-pressed={flow.repeat[r.company_id] === "skip"} disabled={busy}
                    onClick={() => act(() => api.patchArgusFlow(id, { repeat: { ...flow.repeat, [r.company_id]: "skip" } }))}>
                    Skip, keep earlier results
                  </button>
                  <button type="button" className="secondary" aria-pressed={flow.repeat[r.company_id] === "run"} disabled={busy}
                    onClick={() => act(() => api.patchArgusFlow(id, { repeat: { ...flow.repeat, [r.company_id]: "run" } }))}>
                    Run again
                  </button>
                  <a href={`#/review/${runType}/${encodeURIComponent(r.run_id)}`}>See earlier results</a>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-label="Companies in this run" className="argus-run-list">
        <h2>Companies</h2>
        <ul>
          {flow.companies.filter((c) => keptBy.has(c.company_id)).map((c) => (
            <li key={c.company_id}>
              {c.name} · {keptBy.get(c.company_id)} {keptBy.get(c.company_id) === 1 ? "file" : "files"}
              {skipped(c.company_id) && <span className="muted"> · skipped</span>}
              {newDocsLine(added.get(c.company_id) ?? 0) && <span className="muted"> · {newDocsLine(added.get(c.company_id) ?? 0)}</span>}
            </li>
          ))}
        </ul>
      </section>

      <div className="row-actions argus-flow-actions">
        <button
          type="button"
          disabled={busy || !ready}
          onClick={() => {
            if (starting.current) return; // one run per click, even before `busy` re-renders the button
            starting.current = true;
            act(async () => {
              try {
                const v = evidenceValue(); // a value typed but not yet saved (no blur before the click)
                if (v !== (flow.settings.evidence_passages ?? null)) await api.patchArgusFlow(id, { settings: { ...flow.settings, evidence_passages: v } });
                const f = await api.startArgusFlow(id);
                window.location.hash = flowHref(id, 4);
                return f;
              } finally {
                starting.current = false;
              }
            });
          }}
        >
          {label}
        </button>
      </div>
    </div>
  );
}
