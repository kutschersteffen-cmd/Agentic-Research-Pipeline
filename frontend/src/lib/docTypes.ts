import type { DocType } from "../types";

/** Document types a person picks when uploading, with their labels. */
export const DOC_TYPES: [DocType, string][] = [
  ["10-K", "Annual report"],
  ["sustainability_report", "Sustainability report"],
  ["DEF-14A", "Proxy statement"],
  ["earnings_transcript", "Earnings transcript"],
  ["investor_presentation", "Investor presentation"],
  ["transition_plan", "Transition plan"],
  ["other", "Other"],
];

export const uploadText = (name: string, label: string, duplicateOf: string | null | undefined) =>
  `${name} (${label}): ${duplicateOf ? `Duplicate of ${duplicateOf}, skipped` : "uploaded"}`;
