export interface Fig {
  label: string;
  page: number;
  section: string;
  before: string;
  quote: string;
  after: string;
  model: string;
  source: string;
  hash: string;
}

const f = (label: string, page: number, section: string, before: string, quote: string, after: string, model: string, hash: string): Fig =>
  ({ label, page, section, before, quote, after, model, source: quote, hash });

export const FIGS: Fig[] = [
  f("Green capex", 14, "Sustainability", "In 2025 the Group committed ", "EUR 412 million", " to green capital expenditure, chiefly electrolyser lines.", "EUR 412m", "a91f3c07"),
  f("Prior-year capex", 14, "Sustainability", "The comparable figure for 2024 was ", "EUR 268 million", " after the Leipzig plant was deferred.", "EUR 268m", "5be20d4a"),
  f("R&D spend", 22, "Innovation", "Research and development expenses amounted to ", "EUR 187 million", " including EUR 31 million capitalised.", "EUR 187m", "c7740e12"),
  f("R&D ratio", 22, "Innovation", "This corresponds to an R&D ratio of ", "4.6 per cent", " of Group revenue.", "4.6%", "0d38be95"),
  f("Drive Systems", 31, "Segment report", "Drive Systems generated revenue of ", "EUR 1,904 million", " (2024: EUR 1,811 million).", "EUR 1,904m", "e1c9a6f3"),
  f("Grid & Storage", 33, "Segment report", "Grid & Storage contributed ", "EUR 1,362 million", " driven by utility-scale battery orders.", "EUR 1,326m", "7f02bd68"),
  f("Industrial Services", 35, "Segment report", "Industrial Services revenue was ", "EUR 842 million", " with a service backlog of EUR 2.1bn.", "EUR 842m", "b46d1190"),
  f("Group revenue", 8, "Key figures", "Consolidated revenue totalled ", "EUR 4,072 million", " for the year ended 31 December 2025.", "EUR 4,072m", "29ae5c7d"),
  f("Adj. EBIT margin", 9, "Key figures", "Adjusted EBIT margin improved to ", "11.3 per cent", " reflecting mix and procurement savings.", "11.3%", "f8631a0b"),
];

const norm = (s: string) => s.replace(" million", "m").replace(" per cent", "%");
export const failed = (f: Fig) => f.model !== norm(f.source);
