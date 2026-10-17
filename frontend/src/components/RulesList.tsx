import { useState } from "react";
import { blankRule, RuleEditor } from "./RuleEditor";
import { ruleInputs, ruleSentence } from "../lib/ruleSentence";
import type { DataPointSchema, FieldDefinition, FieldRule, RuleSuggestion } from "../types";

interface Change { schema: DataPointSchema; waiting: RuleSuggestion[]; dropped: RuleSuggestion[] }
interface Props {
  schema: DataPointSchema;
  waiting: RuleSuggestion[];
  /** `dropped`: the suggestions or accepted rules this change dropped. */
  onChange: (next: Change) => void;
  onSuggestAgain: () => void;
  busy: boolean;
}
interface Item { key: string; fieldId: string; rule: FieldRule; waiting?: RuleSuggestion }

/** Per field: `N rules · M waiting` (or `1 rule` / `N rules`), and `used by a rule` when an accepted rule reads it. */
export function ruleMarkers(schema: DataPointSchema, waiting: RuleSuggestion[]): Record<string, string> {
  const read = new Set(schema.fields.flatMap((f) => (f.rules ?? []).flatMap(ruleInputs)));
  const out: Record<string, string> = {};
  for (const f of schema.fields) {
    const m = waiting.filter((s) => s.field_id === f.field_id).length;
    const n = (f.rules?.length ?? 0) + m;
    const parts = [n ? `${n} ${n === 1 ? "rule" : "rules"}${m ? ` · ${m} waiting` : ""}` : "", read.has(f.field_id) ? "used by a rule" : ""].filter(Boolean);
    if (parts.length) out[f.field_id] = parts.join(" · ");
  }
  return out;
}

/** Accepted rules and waiting suggestions: by checked field in schema order, then the order they arrived or were added in. */
export function RulesList({ schema, waiting, onChange, onSuggestAgain, busy }: Props) {
  const [editing, setEditing] = useState<string | null>(null);
  const have = (id: string) => schema.fields.some((f) => f.field_id === id);
  const pos = (id: string) => (have(id) ? schema.fields.findIndex((f) => f.field_id === id) : schema.fields.length);
  const items: Item[] = [
    ...schema.fields.flatMap((f) => (f.rules ?? []).map((rule) => ({ key: `a:${rule.rule_id}`, fieldId: f.field_id, rule }))),
    ...waiting.map((s) => ({ key: `w:${s.rule.rule_id}`, fieldId: s.field_id, rule: s.rule, waiting: s })),
  ].sort((a, b) => pos(a.fieldId) - pos(b.fieldId));
  /** Helper fields a suggestion would still add: the ones its rule names that the schema lacks. */
  const adds = (s: RuleSuggestion) => s.helper_fields.filter((h) => !have(h.field_id) && (h.field_id === s.field_id || ruleInputs(s.rule).includes(h.field_id)));
  const fieldsFor = (x: Item): FieldDefinition[] => (x.waiting ? [...schema.fields, ...adds(x.waiting)] : schema.fields);
  const withRules = (fields: FieldDefinition[], fieldId: string, edit: (rules: FieldRule[]) => FieldRule[]) => ({
    ...schema,
    fields: fields.map((f) => (f.field_id === fieldId ? { ...f, rules: edit(f.rules ?? []) } : f)),
  });
  const done = (next: Partial<Change>) => {
    setEditing(null);
    onChange({ schema, waiting, dropped: [], ...next });
  };

  const accept = (s: RuleSuggestion) =>
    done({ schema: withRules([...schema.fields, ...adds(s)], s.field_id, (r) => [...r, s.rule]), waiting: waiting.filter((w) => w !== s) });
  // Drop on an accepted rule keeps the helper fields it brought.
  const drop = (x: Item) =>
    x.waiting
      ? done({ waiting: waiting.filter((w) => w !== x.waiting), dropped: [x.waiting] })
      : done({ schema: withRules(schema.fields, x.fieldId, (r) => r.filter((y) => y !== x.rule)), dropped: [{ field_id: x.fieldId, rule: x.rule, helper_fields: [] }] });
  const save = (x: Item, rule: FieldRule) =>
    x.waiting
      ? done({ waiting: waiting.map((w) => (w === x.waiting ? { ...w, rule } : w)) })
      : done({ schema: withRules(schema.fields, x.fieldId, (r) => r.map((y) => (y === x.rule ? rule : y))) });

  return (
    <div className="rules">
      <h3>Rules</h3>
      <p className="status-text" role="status">
        {busy ? "Suggesting rules…" : waiting.length > 0 && <span className="await-text">{waiting.length} waiting for you</span>}
      </p>
      {!items.length && editing !== "new" && !busy && <p className="help-text">No rules yet. A rule only flags an answer for review; it never changes it.</p>}
      <ul className="rules-list" aria-label="Rules">
        {items.map((x) => (
          <li key={x.key} className={x.waiting ? "rules-item rules-waiting" : "rules-item"} data-field={x.fieldId} data-reads={ruleInputs(x.rule).join(" ")} tabIndex={-1}>
            {editing === x.key ? (
              <RuleEditor fields={fieldsFor(x)} fieldId={x.fieldId} rule={x.rule} onSave={(_, rule) => save(x, rule)} onCancel={() => setEditing(null)} />
            ) : (
              <>
                <div className="rules-top">
                  <span className="rules-kind">{x.rule.kind}</span>
                  <span className="rules-actions">
                    {x.waiting ? <button type="button" onClick={() => accept(x.waiting!)}>Accept</button> : <span className="rules-accepted">Accepted</span>}
                    <button type="button" className="secondary" onClick={() => setEditing(x.key)}>Edit</button>
                    <button type="button" className="secondary" onClick={() => drop(x)}>Drop</button>
                  </span>
                </div>
                <p className="rules-sentence">{ruleSentence(x.rule, x.fieldId, fieldsFor(x))}</p>
                {x.waiting && adds(x.waiting).length > 0 && (
                  <p className="rules-adds">
                    Adds helper {adds(x.waiting).length === 1 ? "field" : "fields"}: {adds(x.waiting).map((h) => h.name).join(", ")}
                  </p>
                )}
              </>
            )}
          </li>
        ))}
        {editing === "new" && (
          <li className="rules-item">
            <RuleEditor
              fields={schema.fields}
              fieldId={null}
              rule={blankRule("threshold", `rule_${crypto.randomUUID()}`)}
              onSave={(fieldId, rule) => done({ schema: withRules(schema.fields, fieldId, (r) => [...r, rule]) })}
              onCancel={() => setEditing(null)}
            />
          </li>
        )}
      </ul>
      <div className="toolbar">
        <button type="button" className="secondary" onClick={() => setEditing("new")} disabled={editing === "new" || !schema.fields.length}>+ Add a rule</button>
        <button type="button" className="secondary" onClick={onSuggestAgain} disabled={busy}>Suggest again</button>
      </div>
    </div>
  );
}
