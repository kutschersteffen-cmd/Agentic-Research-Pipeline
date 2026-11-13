import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { BatchToggle } from "../components/BatchToggle";
import { ruleMarkers, RulesList } from "../components/RulesList";
import { ScoringTemplatePicker } from "../components/RunScoring";
import { SchemaFieldsEditor } from "../components/SchemaFieldsEditor";
import { ruleInputs, sameRule } from "../lib/ruleSentence";
import { bumpChangedFields, canStart, draftHint, flowHref, lastRunText, newDocsLine, newFieldId, newestVersions, plainError, presetCountText, releaseQuestion, startLabel } from "../lib/argusFlow";
import type { ArgusFlow as Flow, DataPointSchema, FieldDefinition, RuleSuggestion, RunManifest } from "../types";

type SavedSchema = { schema_id: string; version: number; name: string; release_flag: boolean; field_count: number };
type Preset = { preset_id: string; name: string; field_count: number };
type Choice = NonNullable<Flow["schema_choice"]>;
const PROFILES: ["financials" | "tnfd", string][] = [
  ["financials", "Financials"],
  ["tnfd", "TNFD"],
];

const asChoice = (c: Partial<Choice> & Pick<Choice, "kind">): Choice => ({ schema_id: null, version: null, profile: null, ...c });

const blankField = (): FieldDefinition => ({
  field_id: newFieldId(), name: "", description: "", data_type: "number", unit: null, extraction_instructions: "", required: false,
  source_doc_types: [], seed_keywords: [],
});

/** The unsaved fields and the typed description of one flow, kept in this tab so a reload does not lose them. */
type StoredDraft = { editing: DataPointSchema; words: string };
const draftKey = (flowId: string) => `argus-draft:${flowId}`;
function storedDraft(flowId: string): StoredDraft | null {
  try {
    return JSON.parse(sessionStorage.getItem(draftKey(flowId)) ?? "null");
  } catch {
    return null; // storage blocked or not JSON: start without a draft
  }
}

/** A long "Look in" text shows three lines and Show more; a text that fits shows no button. */
function Clamped({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const [clipped, setClipped] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || open) return; // while open nothing is clipped: keep the button for Show less
    const measure = () => setClipped(el.scrollHeight > el.clientHeight + 1);
    measure();
    const ro = new ResizeObserver(measure); // a narrower column clips a text that fitted
    ro.observe(el);
    return () => ro.disconnect();
  }, [open, text]);
  return (
    <div>
      <div ref={ref} className={open ? undefined : "argus-clamp"}>{text}</div>
      {clipped && (
        <button type="button" className="link-button" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

/** Step 3 of an Argus flow: what to extract, its fields, optional settings, the repeat warning and the start. */
export function ArgusSchema({ flow, busy, act }: { flow: Flow; busy: boolean; act: (fn: () => Promise<Flow | void>) => void }) {
  const [saved, setSaved] = useState<SavedSchema[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [schema, setSchema] = useState<DataPointSchema | null>(null);
  const id = flow.flow_id;
  const [stored] = useState(() => storedDraft(id));
  const [editing, setEditing] = useState<DataPointSchema | null>(stored?.editing ?? null); // unsaved fields: drafted, added or being edited
  // Rule suggestions for the unsaved fields: waiting ones block saving; dropped ones are not suggested again.
  const [waiting, setWaiting] = useState<RuleSuggestion[]>([]);
  const [dropped, setDropped] = useState<RuleSuggestion[]>([]);
  const [suggesting, setSuggesting] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [ruleError, setRuleError] = useState("");
  const latest = useRef(editing); // patches after an await apply to the fields as they are then
  latest.current = editing;
  const [words, setWords] = useState(stored?.words ?? "");
  useEffect(() => {
    try {
      if (editing) sessionStorage.setItem(draftKey(id), JSON.stringify({ editing, words } satisfies StoredDraft));
      else sessionStorage.removeItem(draftKey(id)); // saved, cancelled or replaced by another choice
    } catch {
      /* storage blocked or full: the draft then lives in the page only, as before */
    }
  }, [id, editing, words]);
  const [gone, setGone] = useState(false); // the chosen schema no longer exists
  const [role, setRole] = useState<string | null>(null);
  const [loadError, setLoadError] = useState("");
  const [evidence, setEvidence] = useState(flow.settings.evidence_passages?.toString() ?? ""); // saved on blur and before Start
  const starting = useRef(false);
  const [indicatorCount, setIndicatorCount] = useState<number | null>(null);
  const [pastRuns, setPastRuns] = useState<RunManifest[] | null>(null);
  const choice = flow.schema_choice ?? null;

  useEffect(() => {
    api.listSchemas().then((s) => setSaved(newestVersions(s)), (e: Error) => setLoadError(plainError(e.message)));
    api.listPresets().then(setPresets, (e: Error) => setLoadError(plainError(e.message)));
    api.getMe().then((m) => setRole(m.role), () => setRole(null));
    api.getTransitionPlanIndicators().then((i) => setIndicatorCount(i.length), () => setIndicatorCount(null));
  }, []);
  const runType = choice?.kind === "profile" ? choice.profile! : "extraction";
  useEffect(() => {
    setPastRuns(null);
    if (!choice) return;
    let live = true;
    api.listRuns(runType).then((r) => live && setPastRuns((r as { runs: RunManifest[] }).runs), () => live && setPastRuns(null));
    return () => {
      live = false;
    };
  }, [runType, choice?.schema_id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setSchema(null);
    if (choice?.kind) setGone(false);
    if (choice?.kind !== "schema" || !choice.schema_id || !choice.version) return;
    let live = true; // a slower answer for an earlier choice must not replace this one
    api.getSchema(choice.schema_id, choice.version).then((s) => live && setSchema(s), (e: Error) => {
      if (!live) return;
      if (!/^404: /.test(e.message)) return setLoadError(plainError(e.message));
      setGone(true); // deleted since it was chosen: clear the choice, or the start button waits on it for ever
      act(() => api.patchArgusFlow(id, { schema_choice: null, repeat: {} }));
    });
    return () => {
      live = false;
    };
  }, [choice?.kind, choice?.schema_id, choice?.version, act, id]);

  const choose = (c: Partial<Choice> & Pick<Choice, "kind">) =>
    act(async () => {
      edit(null);
      return api.patchArgusFlow(id, { schema_choice: asChoice(c), repeat: {} });
    });
  const saveEditing = () =>
    act(async () => {
      if (!editing) return;
      const kept = { ...editing, fields: editing.fields.filter((f) => f.name.trim()) };
      const s = await api.registerSchema(bumpChangedFields(schema?.schema_id === editing.schema_id ? schema : null, kept));
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
      setRuleError(`Rule suggestions failed: ${plainError((err as Error).message)}`);
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
    : editing ? "Save the schema to continue" : "Choose what to extract";
  const ready = !!choice && !editing && (choice.kind === "profile" || !!schema) && companies.length > 0 && canStart(flow.repeat_rows, flow.repeat);
  const isChosen = (s: SavedSchema) => choice?.kind === "schema" && choice.schema_id === s.schema_id && choice.version === s.version;

  return (
    <div className="argus-schema">
      {loadError && <p className="error-text" role="alert">{loadError}</p>}
      {gone && <p className="error-text" role="alert">The schema chosen earlier no longer exists. Choose another.</p>}
      <div className="argus-schema-cols">
        <section className="card argus-schema-pick" aria-label="What to extract">
          <h2>Saved schemas</h2>
          {saved.length === 0 ? (
            <p className="muted">None saved yet.</p>
          ) : (
            <label className="field-label">
              Saved schema
              <select
                id="argus-saved-schema"
                value={String(saved.findIndex(isChosen))}
                disabled={busy}
                onChange={(e) => {
                  const s = saved[Number(e.target.value)];
                  if (s) choose({ kind: "schema", schema_id: s.schema_id, version: s.version });
                }}
              >
                <option value="-1" disabled>Choose one…</option>
                {[true, false].map((rel) => (
                  <optgroup key={String(rel)} label={rel ? "Released" : "Draft"}>
                    {saved.map((s, i) => !!s.release_flag === rel && (
                      <option key={`${s.schema_id}:${s.version}`} value={i}>
                        {s.name} v{s.version} · {s.field_count} {s.field_count === 1 ? "field" : "fields"}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
          )}
          <h2>Templates</h2>
          <label className="field-label">
            Template
            <select
              id="argus-template"
              value={choice?.kind === "profile" ? `f:${choice.profile}` : ""}
              disabled={busy}
              onChange={(e) => {
                const [kind, key] = [e.target.value.slice(0, 1), e.target.value.slice(2)];
                if (kind === "f") choose({ kind: "profile", profile: key as (typeof PROFILES)[number][0] });
                else if (kind === "p")
                  act(async () => {
                    const s = await api.installPreset(key);
                    edit(null);
                    setSaved(newestVersions(await api.listSchemas()));
                    return api.patchArgusFlow(id, { schema_choice: asChoice({ kind: "schema", schema_id: s.schema_id, version: s.version }), repeat: {} });
                  });
              }}
            >
              <option value="" disabled>Choose one…</option>
              <optgroup label="Schema templates">
                {presets.map((p) => <option key={p.preset_id} value={`p:${p.preset_id}`}>{p.name} · {presetCountText(p, indicatorCount)}</option>)}
              </optgroup>
              <optgroup label="Fixed profiles">
                {PROFILES.map(([p, name]) => <option key={p} value={`f:${p}`}>{name} · fixed fields</option>)}
              </optgroup>
            </select>
          </label>
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
                setDrafting(true);
                try {
                  const drafted = (await api.draftSchema(words)) as DataPointSchema;
                  edit(drafted);
                  latest.current = drafted;
                  void suggest(drafted);
                } finally {
                  setDrafting(false);
                }
              })
            }
          >
            Draft fields
          </button>
          {drafting && <span className="muted" role="status"> Drafting fields…</span>}
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
                          <td data-label="Look in">{f.extraction_instructions ? <Clamped text={f.extraction_instructions} /> : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="row-actions">
                <button type="button" className="secondary" disabled={busy} onClick={() => setEditing({ ...(editing ?? shown), fields: [...(editing ?? shown).fields, blankField()] })}>
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
                        <button type="button" className="secondary" disabled={busy} onClick={() => {
                          if (!window.confirm(releaseQuestion(schema.name, schema.version ?? 1, companies.length))) return;
                          act(async () => {
                            setSchema(await api.releaseSchema(schema.schema_id, schema.version ?? 1));
                            setSaved(newestVersions(await api.listSchemas()));
                          });
                        }}>
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
              disabled={busy}
              onChange={(e) => setEvidence(e.target.value)}
              onBlur={() => {
                const v = evidenceValue();
                if (v !== (flow.settings.evidence_passages ?? null)) act(() => api.patchArgusFlow(id, { settings: { ...flow.settings, evidence_passages: v } }));
              }}
            />
          </label>
          <BatchToggle checked={flow.settings.batch} disabled={busy} onChange={(batch) => act(() => api.patchArgusFlow(id, { settings: { ...flow.settings, batch } }))} />
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
        {choice && pastRuns && (
          <span className="muted" role="note">
            {lastRunText(pastRuns.filter((r) => choice.kind === "profile" || r.params.schema_id === choice.schema_id))}
          </span>
        )}
        {choice?.kind === "schema" && schema && draftHint(released, companies.length, role === "approver") && (
          <span className="muted" role="note">{draftHint(released, companies.length, role === "approver")}</span>
        )}
      </div>
    </div>
  );
}
