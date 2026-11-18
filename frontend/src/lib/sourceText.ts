import type { ActiveSource } from "../components/SourcePanel";
/** Splits page text around a highlighted span and the line it sits on; null for an invalid span. */
export function highlightParts(text: string, start: number, end: number) {
  if (!(start >= 0 && start < end && end <= text.length)) return null;
  const ls = start === 0 ? 0 : text.lastIndexOf("\n", start - 1) + 1;
  const nl = text.indexOf("\n", end);
  const le = nl === -1 ? text.length : nl;
  return { before: text.slice(0, ls), lineBefore: text.slice(ls, start), mark: text.slice(start, end), lineAfter: text.slice(end, le), after: text.slice(le) };
}

/** Sentence starts: 0 and every position right after ". ", "? ", "! " or a newline. */
function sentenceStarts(text: string): number[] {
  const starts = [0];
  for (let i = 1; i < text.length; i++) {
    if (text[i - 1] === "\n" || (text[i - 1] === " " && ".?!".includes(text[i - 2] ?? ""))) starts.push(i);
  }
  return starts;
}

const LIMIT = 240;

/** The cited span with its sentence and the sentences either side, for the source excerpt card;
 * null for an invalid span. Only whitespace is trimmed and only lead/trail are cut, so every
 * part is text from the source. */
export function excerptParts(text: string, start: number, end: number) {
  if (!(start >= 0 && start < end && end <= text.length)) return null;
  const starts = sentenceStarts(text);
  const last = (pred: (s: number) => boolean) => starts.reduce((acc, s, i) => (pred(s) ? i : acc), 0);
  const si = last((s) => s <= start);
  const ei = last((s) => s < end);
  const at = (i: number) => (i >= 0 && i < starts.length ? text.slice(starts[i], starts[i + 1] ?? text.length).trim() : "");
  const lead = at(si - 1);
  const trail = at(ei + 1);
  return {
    lead: lead.slice(-LIMIT),
    before: text.slice(starts[si], start).trimStart(),
    mark: text.slice(start, end).trim(),
    after: text.slice(end, starts[ei + 1] ?? text.length).trimEnd(),
    trail: trail.slice(0, LIMIT),
  };
}

/** What the source panel's excerpt card shows: the stored page around the span, else the quote, else nothing. */
export function excerptView(source: ActiveSource) {
  const t = source.text;
  const caption = source.title + (typeof t?.page === "number" && t.page >= 1 ? ` · p. ${t.page}` : "");
  const parts = t && t.char_start != null && t.char_end != null ? excerptParts(t.page_text, t.char_start, t.char_end) : null;
  if (parts) return { caption, parts };
  const quote = source.quote?.trim();
  return quote ? { caption, quote } : null;
}
