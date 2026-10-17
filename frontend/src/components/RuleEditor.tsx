import { useState } from "react";
import { ruleInputs, ruleSentence } from "../lib/ruleSentence";
import type { FieldDefinition, FieldRule, RuleScalar } from "../types";

const NUMERIC = ["number", "currency_amount", "percentage"];
const OPS = [">=", "<=", ">", "<", "="] as const;
const KINDS: FieldRule["kind"][] = ["requires", "threshold", "series", "label", "computed"];
const TRENDS = [["none", "No trend"], ["down", "Falling"], ["up", "Rising"]] as const;
type Option = [RuleScalar, string];

/** A rule of `kind` with its inputs still empty; numbers start as NaN, which the editor shows as an empty box. */
export function blankRule(kind: FieldRule["kind"], rule_id: string, when: RuleScalar | null = null): FieldRule {
  if (kind === "requires") return { rule_id, when, kind, field: "", equals: true };
  if (kind === "threshold") return { rule_id, when, kind, conditions: [{ field: "", op: ">=", value: NaN }] };
  if (kind === "series") return { rule_id, when, kind, field: "", years: 5, trend: "none" };
  if (kind === "label") return { rule_id, when, kind, field: "", not_in: [] };
  return { rule_id, when, kind, formula: "ratio_pct", inputs: ["", ""], tolerance: 0 };
}

/** Every input filled in and in range; the backend validates the rest when the schema is saved. */
function complete(rule: FieldRule, fieldId: string): boolean {
  const ids = rule.kind === "threshold" ? rule.conditions.map((c) => c.field) : rule.kind === "computed" ? rule.inputs : [rule.field];
  if (!fieldId || ids.some((id) => !id) || ruleInputs(rule).includes(fieldId)) return false;
  if (rule.kind === "requires") return rule.equals !== "" && !(typeof rule.equals === "number" && Number.isNaN(rule.equals));
  if (rule.kind === "threshold") return rule.conditions.length > 0 && rule.conditions.every((c) => Number.isFinite(c.value));
  if (rule.kind === "series") return Number.isInteger(rule.years) && rule.years >= 1 && rule.years <= 5;
  if (rule.kind === "label") return rule.not_in.length > 0;
  return Number.isFinite(rule.tolerance) && (rule.tolerance ?? 0) >= 0;
}

/** A field's possible values: YES / NO for a boolean, the allowed values for an enum. */
function valuesOf(f: FieldDefinition | undefined): Option[] {
  if (f?.data_type === "boolean") return [[true, "YES"], [false, "NO"]];
  return f?.data_type === "enum" ? (f.allowed_values ?? []).map((v) => [v, v]) : [];
}

function FieldSelect({ label, value, options, onChange }: { label: string; value: string; options: FieldDefinition[]; onChange: (id: string) => void }) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Choose a field</option>
      {options.map((f) => (
        <option key={f.field_id} value={f.field_id}>{f.name}</option>
      ))}
    </select>
  );
}

/** A select over values that may be booleans; `none` adds an empty first option. */
function ValueSelect({ label, value, options, none, onChange }: { label: string; value: RuleScalar | null | undefined; options: Option[]; none?: string; onChange: (v: RuleScalar | null) => void }) {
  const at = options.findIndex(([v]) => v === value);
  return (
    <select aria-label={label} value={at < 0 ? "" : String(at)} onChange={(e) => onChange(e.target.value === "" ? null : options[Number(e.target.value)][0])}>
      {(none != null || at < 0) && <option value="">{none ?? "Choose a value"}</option>}
      {options.map(([, text], i) => (
        <option key={text} value={i}>{text}</option>
      ))}
    </select>
  );
}

const num = (v: number | undefined) => (v == null || Number.isNaN(v) ? "" : v);

interface Props {
  /** Fields the rule may name: the schema's, plus a suggestion's helper fields. */
  fields: FieldDefinition[];
  /** The checked field; null lets the user pick it and the kind (+ Add a rule). */
  fieldId: string | null;
  rule: FieldRule;
  onSave: (fieldId: string, rule: FieldRule) => void;
  onCancel: () => void;
}

/** Inputs for one rule's parameters, with its sentence re-rendered as they change. */
export function RuleEditor({ fields, fieldId: fixed, rule: initial, onSave, onCancel }: Props) {
  const [fieldId, setFieldId] = useState(fixed ?? fields[0]?.field_id ?? "");
  const [rule, setRule] = useState<FieldRule>(initial);
  const set = (p: object) => setRule((r) => ({ ...r, ...p }) as FieldRule);
  const byId = (id: string) => fields.find((f) => f.field_id === id);
  const others = (types?: string[]) => fields.filter((f) => f.field_id !== fieldId && (!types || types.includes(f.data_type)));
  const whenOptions = valuesOf(byId(fieldId));
  if (rule.when != null && !whenOptions.some(([v]) => v === rule.when)) whenOptions.push([rule.when, String(rule.when)]);
  const ok = complete(rule, fieldId);

  let params;
  if (rule.kind === "requires") {
    const other = byId(rule.field);
    const choices = valuesOf(other);
    params = (
      <div className="inline-fields">
        <FieldSelect label="Needs field" value={rule.field} options={others()} onChange={(field) => set({ field, equals: valuesOf(byId(field))[0]?.[0] ?? "" })} />
        {choices.length ? (
          <ValueSelect label="To be" value={rule.equals} options={choices} onChange={(v) => set({ equals: v ?? "" })} />
        ) : other && NUMERIC.includes(other.data_type) ? (
          <input type="number" aria-label="To be" value={num(rule.equals as number)} onChange={(e) => set({ equals: e.target.valueAsNumber })} />
        ) : (
          <input aria-label="To be" value={String(rule.equals)} onChange={(e) => set({ equals: e.target.value })} />
        )}
      </div>
    );
  } else if (rule.kind === "threshold") {
    const cond = (i: number, p: object) => set({ conditions: rule.conditions.map((c, j) => (j === i ? { ...c, ...p } : c)) });
    params = (
      <>
        {rule.conditions.map((c, i) => (
          <div className="inline-fields" key={i}>
            <FieldSelect label={`Condition ${i + 1} field`} value={c.field} options={others(NUMERIC)} onChange={(field) => cond(i, { field })} />
            <select aria-label={`Condition ${i + 1} operator`} value={c.op} onChange={(e) => cond(i, { op: e.target.value })}>
              {OPS.map((op) => <option key={op}>{op}</option>)}
            </select>
            <input type="number" aria-label={`Condition ${i + 1} value`} placeholder="Value" value={num(c.value)} onChange={(e) => cond(i, { value: e.target.valueAsNumber })} />
            <button type="button" className="secondary" onClick={() => set({ conditions: rule.conditions.filter((_, j) => j !== i) })}>Remove</button>
          </div>
        ))}
        <div className="toolbar">
          <button type="button" className="secondary" onClick={() => set({ conditions: [...rule.conditions, { field: "", op: ">=", value: NaN }] })}>Add a condition</button>
        </div>
      </>
    );
  } else if (rule.kind === "series") {
    params = (
      <div className="rules-editor-grid">
        <label className="field-label">Field<FieldSelect label="Field" value={rule.field} options={others(NUMERIC)} onChange={(field) => set({ field })} /></label>
        <label className="field-label">Years<input type="number" min={1} max={5} value={num(rule.years)} onChange={(e) => set({ years: e.target.valueAsNumber })} /></label>
        <label className="field-label">
          Trend
          <select value={rule.trend ?? "none"} onChange={(e) => set({ trend: e.target.value })}>
            {TRENDS.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
          </select>
        </label>
      </div>
    );
  } else if (rule.kind === "label") {
    const values = byId(rule.field)?.allowed_values ?? [];
    params = (
      <>
        <label className="field-label">Field<FieldSelect label="Field" value={rule.field} options={others(["enum"])} onChange={(field) => set({ field, not_in: [] })} /></label>
        {values.length > 0 && (
          <fieldset className="rules-fieldset">
            <legend className="field-label">Must not be</legend>
            {values.map((v) => (
              <label className="checkbox-label" key={v}>
                <input type="checkbox" checked={rule.not_in.includes(v)} onChange={(e) => set({ not_in: e.target.checked ? [...rule.not_in, v] : rule.not_in.filter((x) => x !== v) })} />
                {v}
              </label>
            ))}
          </fieldset>
        )}
      </>
    );
  } else {
    const inputs = rule.inputs;
    const pad = (ids: string[]) => [...ids, "", ""].slice(0, Math.max(2, ids.length));
    params = (
      <>
        <div className="rules-editor-grid">
          <label className="field-label">
            Formula
            <select value={rule.formula} onChange={(e) => set({ formula: e.target.value, inputs: e.target.value === "ratio_pct" ? pad(inputs).slice(0, 2) : pad(inputs) })}>
              <option value="ratio_pct">Ratio × 100</option>
              <option value="sum">Sum</option>
            </select>
          </label>
          <label className="field-label">Tolerance<input type="number" min={0} value={num(rule.tolerance)} onChange={(e) => set({ tolerance: e.target.valueAsNumber })} /></label>
        </div>
        {inputs.map((id, i) => (
          <div className="inline-fields" key={i}>
            <FieldSelect label={`Input ${i + 1}`} value={id} options={others(NUMERIC)} onChange={(v) => set({ inputs: inputs.map((x, j) => (j === i ? v : x)) })} />
            {rule.formula === "sum" && inputs.length > 2 && (
              <button type="button" className="secondary" onClick={() => set({ inputs: inputs.filter((_, j) => j !== i) })}>Remove</button>
            )}
          </div>
        ))}
        {rule.formula === "sum" && (
          <div className="toolbar">
            <button type="button" className="secondary" onClick={() => set({ inputs: [...inputs, ""] })}>Add an input</button>
          </div>
        )}
      </>
    );
  }

  return (
    <>
      <div className="rules-top">
        <span className="rules-kind">{rule.kind} · editing</span>
        <span className="rules-actions">
          <button type="button" disabled={!ok} onClick={() => onSave(fieldId, rule)}>Save</button>
          <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
        </span>
      </div>
      <div className="rules-editor-grid">
        {fixed == null && (
          <label className="field-label">
            Checked field
            <select value={fieldId} onChange={(e) => { setFieldId(e.target.value); set({ when: null }); }}>
              {fields.map((f) => <option key={f.field_id} value={f.field_id}>{f.name}</option>)}
            </select>
          </label>
        )}
        <label className="field-label">
          When
          <ValueSelect label="When" value={rule.when} options={whenOptions} none="Whenever found" onChange={(when) => set({ when })} />
        </label>
        {fixed == null && (
          <label className="field-label">
            Kind
            <select value={rule.kind} onChange={(e) => setRule(blankRule(e.target.value as FieldRule["kind"], rule.rule_id, rule.when))}>
              {KINDS.map((k) => <option key={k}>{k}</option>)}
            </select>
          </label>
        )}
      </div>
      {params}
      <p className="rules-sentence" aria-live="polite">
        {ok ? ruleSentence(rule, fieldId, fields) : <span className="muted">Fill in every input to see the rule.</span>}
      </p>
    </>
  );
}
