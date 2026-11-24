/** Parsers for inputs that keep what is typed while they have focus (see DraftInput). */

export const parseList = (text: string): string[] =>
  text.split(",").map((p) => p.trim()).filter(Boolean);

export const listText = (items: string[]): string => items.join(", ");

export const parseNumberList = (text: string): number[] =>
  parseList(text).map(Number).filter(Number.isFinite);

/** One `value = factor` per line; a line that does not parse yet is left out, a repeated key keeps its last factor. */
export function parseMultipliers(text: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const line of text.split("\n")) {
    const at = line.indexOf("=");
    if (at < 0) continue;
    const key = line.slice(0, at).trim();
    const raw = line.slice(at + 1).trim();
    const factor = raw === "" ? NaN : Number(raw);
    if (key && Number.isFinite(factor) && factor > 0) out[key] = factor;
  }
  return out;
}

export const multipliersText = (m: Record<string, number>): string =>
  Object.entries(m).map(([k, v]) => `${k} = ${v}`).join("\n");
