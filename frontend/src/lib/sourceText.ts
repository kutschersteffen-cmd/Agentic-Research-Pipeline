/** Splits page text around a highlighted span and the line it sits on; null for an invalid span. */
export function highlightParts(text: string, start: number, end: number) {
  if (!(start >= 0 && start < end && end <= text.length)) return null;
  const ls = start === 0 ? 0 : text.lastIndexOf("\n", start - 1) + 1;
  const nl = text.indexOf("\n", end);
  const le = nl === -1 ? text.length : nl;
  return { before: text.slice(0, ls), lineBefore: text.slice(ls, start), mark: text.slice(start, end), lineAfter: text.slice(end, le), after: text.slice(le) };
}
