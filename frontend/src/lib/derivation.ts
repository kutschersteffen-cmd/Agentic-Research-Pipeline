// How an authoritative value was derived, as plain lines for the Decision Studio panel.

type Input = {
  value: unknown;
  status: string | null;
  source: string | null;
  provider: string | null;
  period_end: string | null;
};

type Derived = {
  value: unknown;
  unit: string | null;
  status: string;
  reason: string | null;
  derivation: { inputs: Record<string, Input>; trace: { expressions: string[] }[] };
};

const show = (x: unknown) => (x !== null && typeof x === "object" ? JSON.stringify(x) : String(x));

export function showValue(x: unknown): string {
  return show(x);
}

export function derivationLines(v: Derived): { value: string; inputs: string[]; expressions: string[] } {
  const value = v.status === "value" ? [show(v.value), v.unit].filter(Boolean).join(" ") : `No value (${v.reason})`;
  const inputs = Object.entries(v.derivation.inputs).map(([alias, i]) => {
    if (i.value == null) return `${alias} = —`;
    const source = [i.source, i.provider].filter(Boolean).join(" ");
    return [`${alias} = ${show(i.value)}`, i.status, source, i.period_end].filter(Boolean).join(" · ");
  });
  const expressions = [...new Set(v.derivation.trace.flatMap((n) => n.expressions))];
  return { value, inputs, expressions };
}
