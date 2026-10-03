/** Pure helpers for files fetched with the bearer token (see fetchFile in api/client.ts). */

/** The filename from a Content-Disposition header, or the fallback. */
export function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const star = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      // malformed escape: fall through to the plain filename
    }
  }
  const plain = /filename\s*=\s*"([^"]*)"|filename\s*=\s*([^;]+)/.exec(header);
  const name = (plain?.[1] ?? plain?.[2] ?? "").trim();
  return name || fallback;
}

/** Types safe to show from a blob: URL, which runs with this app's origin.
 * HTML/SVG could run script there (and read the token), so those are
 * downloaded or shown in a sandboxed frame instead. */
export function inlineSafe(type: string): boolean {
  return /^(application\/pdf|image\/(png|jpe?g|gif|webp)|text\/(plain|csv)|application\/json)\b/i.test(type);
}
