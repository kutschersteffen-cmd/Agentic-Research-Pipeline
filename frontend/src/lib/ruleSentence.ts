import type { FieldDefinition, FieldRule, RuleScalar } from "../types";

// Mirrors backend/arp/checks/rules.py (rule_sentence, rule_inputs); both are tested on
// backend/tests/fixtures/rule_sentences.json.

// Booleans as YES/NO; numbers and strings as stored (String(50) is already "50").
const show = (v: RuleScalar) => (typeof v === "boolean" ? (v ? "YES" : "NO") : String(v));

export function ruleSentence(rule: FieldRule, fieldId: string, fields: FieldDefinition[]): string {
  const n = (id: string) => fields.find((f) => f.field_id === id)?.name ?? id; // unknown ids fall back to the id
  let body: string;
  if (rule.kind === "requires") body = `needs ${n(rule.field)} to be ${show(rule.equals)}.`;
  else if (rule.kind === "threshold") body = `needs ${rule.conditions.map((c) => `${n(c.field)} ${c.op} ${show(c.value)}`).join(" and ")}.`;
  else if (rule.kind === "series") {
    const trend = rule.trend === "down" ? ", falling" : rule.trend === "up" ? ", rising" : "";
    body = `needs ${n(rule.field)} for ${rule.years} years up to the report year${trend}.`;
  } else if (rule.kind === "label") body = `${n(rule.field)} must not be ${rule.not_in.join(" or ")}.`;
  else {
    const ins = rule.inputs.map(n);
    const expr = rule.formula === "ratio_pct" ? `${ins[0]} ÷ ${ins[1]} × 100` : ins.join(" + ");
    body = `${n(fieldId)} should equal ${expr}, within ${show(rule.tolerance ?? 0)}.`;
  }
  if (rule.when == null) return body[0].toUpperCase() + body.slice(1);
  return `When ${n(fieldId)} is ${show(rule.when)}: ${body}`;
}

/** Field ids the rule reads, in the order it names them. */
export function ruleInputs(rule: FieldRule): string[] {
  const ids = rule.kind === "threshold" ? rule.conditions.map((c) => c.field) : rule.kind === "computed" ? rule.inputs : [rule.field];
  return [...new Set(ids)];
}

// Key order is irrelevant; array order is not.
const canon = (v: unknown): string => JSON.stringify(v, (_, x) => (x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : 1))) : x));

type Placed = { fieldId: string; rule: FieldRule };

/** Same checked field, kind, `when` and parameters; `rule_id` is ignored. */
export function sameRule(a: Placed, b: Placed): boolean {
  const bare = ({ rule_id: _id, when, ...rest }: FieldRule) => ({ ...rest, when: when ?? null });
  return a.fieldId === b.fieldId && canon(bare(a.rule)) === canon(bare(b.rule));
}
