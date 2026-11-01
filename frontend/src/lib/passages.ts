import type { DocumentPassage, DocumentPassages } from "../types";

// Data Library → Parsed documents → Passages (passage-view spec): the words for one document's passage list.

/** "48 passages · 2 under 200 characters · 5 without a section · pages 7, 8 have no text", zero parts dropped. */
export function passageSummary(s: DocumentPassages["summary"]): string {
  return [
    `${s.passages} passage${s.passages === 1 ? "" : "s"}`,
    s.short > 0 && `${s.short} under 200 characters`,
    s.no_section > 0 && `${s.no_section} without a section`,
    s.empty_pages.length > 0 && `page${s.empty_pages.length === 1 ? "" : "s"} ${s.empty_pages.join(", ")} ${s.empty_pages.length === 1 ? "has" : "have"} no text`,
  ].filter(Boolean).join(" · ");
}

/** "#3 · p. 2–3 · Item 7 · 3,412 chars"; a transcript passage names its speaker instead of a section. */
export function passageLabel(p: DocumentPassage): string {
  const pages = p.page_start == null ? null : p.page_start === p.page_end ? `p. ${p.page_start}` : `p. ${p.page_start}–${p.page_end}`;
  return [`#${p.index}`, pages, p.speaker ?? p.section ?? "no section", `${p.chars.toLocaleString("en-US")} chars`].filter(Boolean).join(" · ");
}
