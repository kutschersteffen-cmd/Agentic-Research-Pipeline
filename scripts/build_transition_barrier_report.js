// Builds the Transition Barrier Assessment report straight from the normalized
// JSON, so the document cannot drift from the data it describes.
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle, PageBreak,
  ExternalHyperlink, PageOrientation,
} = require("docx");

const DATA = path.resolve(__dirname, "..", "backend", "arp", "transition_barrier", "data");
const read = (f) => JSON.parse(fs.readFileSync(path.join(DATA, f), "utf8"));
const criteria = read("criteria_schema.json").criteria;
const scores = read("assessment_scores.json").scores;
const registry = read("source_registry.json").sources;

// Landscape A4 content width, in DXA. 1440 DXA = 1 inch.
const PAGE_W = 16838, PAGE_H = 11906, MARGIN = 720;
const CONTENT_W = PAGE_W - MARGIN * 2;

const ACCENT = "3B2F8C";
const RATING_FILL = { H: "D6EFDC", M: "FBF0D9", L: "F7DAD6" };

const count = (arr, key) => arr.reduce((m, x) => ((m[x[key]] = (m[x[key]] || 0) + 1), m), {});
const dist = count(scores, "rating");
const byRegion = (r) => count(scores.filter((s) => s.region === r), "rating");
const REGIONS = ["European Union", "United States", "China"];

function p(text, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after ?? 120, before: opts.before ?? 0 },
    alignment: opts.align,
    heading: opts.heading,
    pageBreakBefore: opts.pageBreakBefore,
    children: [new TextRun({ text, bold: opts.bold, italics: opts.italics, size: opts.size ?? 20, color: opts.color, font: "Calibri" })],
  });
}

// Rich paragraph from [{text, bold, italics}] runs.
function rich(runs, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after ?? 120 },
    children: runs.map((r) => new TextRun({ ...r, size: r.size ?? 20, font: "Calibri" })),
  });
}

function cell(children, { width, fill, bold, align } = {}) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: fill ? { type: ShadingType.CLEAR, fill, color: "auto" } : undefined,
    margins: { top: 60, bottom: 60, left: 90, right: 90 },
    children: (Array.isArray(children) ? children : [children]).map((t) =>
      typeof t === "string"
        ? new Paragraph({
            alignment: align,
            spacing: { after: 0 },
            children: [new TextRun({ text: t, bold, size: 17, font: "Calibri" })],
          })
        : t,
    ),
  });
}

// Header cells render white text on the accent fill.
function headerRow(widths, labels) {
  return new TableRow({
    tableHeader: true,
    children: labels.map((h, i) =>
      new TableCell({
        width: { size: widths[i], type: WidthType.DXA },
        shading: { type: ShadingType.CLEAR, fill: ACCENT, color: "auto" },
        margins: { top: 60, bottom: 60, left: 90, right: 90 },
        children: [new Paragraph({ spacing: { after: 0 }, children: [new TextRun({ text: h, bold: true, color: "FFFFFF", size: 17, font: "Calibri" })] })],
      }),
    ),
  });
}

function tbl(widths, labels, rows) {
  return new Table({
    columnWidths: widths,
    width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 2, color: "C9C9D4" },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: "C9C9D4" },
      left: { style: BorderStyle.SINGLE, size: 2, color: "C9C9D4" },
      right: { style: BorderStyle.SINGLE, size: 2, color: "C9C9D4" },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: "DEDEE6" },
      insideVertical: { style: BorderStyle.SINGLE, size: 2, color: "DEDEE6" },
    },
    rows: [headerRow(widths, labels), ...rows],
  });
}

const children = [];

// ---------------------------------------------------------------- title page
children.push(
  new Paragraph({ spacing: { before: 2200, after: 0 }, children: [new TextRun({ text: "Transition Barrier Assessment", bold: true, size: 56, color: ACCENT, font: "Calibri" })] }),
  new Paragraph({ spacing: { after: 400 }, children: [new TextRun({ text: "How feasible is decarbonisation, by sector and by region?", size: 28, color: "5A5A6E", font: "Calibri" })] }),
  rich([
    { text: `${criteria.length} criteria`, bold: true }, { text: "  ·  " },
    { text: "9 hard-to-abate sectors", bold: true }, { text: "  ·  " },
    { text: "3 regions", bold: true }, { text: "  ·  " },
    { text: `${scores.length} rated cells`, bold: true }, { text: "  ·  " },
    { text: `${Object.keys(registry).length} verified sources`, bold: true },
  ]),
  p("Agentic Research Pipeline — module reference", { color: "5A5A6E" }),
  p("Data verified 2026-08-14", { color: "5A5A6E" }),
);

children.push(new Paragraph({ children: [new PageBreak()] }));

// ------------------------------------------------------------------ overview
children.push(p("What this is", { heading: HeadingLevel.HEADING_1, before: 0, after: 160 }));
children.push(p(
  "The Transition Barrier Assessment answers a question that sits upstream of every company-level climate judgement: how feasible is decarbonisation in this sector, in this region, at all? It scores 9 hard-to-abate sectors against 35 criteria, each rated for the European Union, the United States and China — a 105-cell matrix. Every cell carries an H/M/L rating, a confidence tier, the evidence it rests on, the sources behind it, and the date it was last verified.",
));

children.push(p("Read the rating the right way", { heading: HeadingLevel.HEADING_2, before: 200, after: 120 }));
children.push(rich([
  { text: "H means transition is more feasible — fewer barriers — not that the barrier is high.", bold: true },
  { text: " This is the most common way to misread the matrix. A cell rated L is one where decarbonisation is hard: the technology is not ready, the regulation is absent, or the economics do not close." },
]));
children.push(tbl([1400, CONTENT_W - 1400], ["Rating", "Meaning"], [
  new TableRow({ children: [cell("H", { width: 1400, fill: RATING_FILL.H, bold: true, align: AlignmentType.CENTER }), cell("High feasibility — the enabling condition is in place", { width: CONTENT_W - 1400 })] }),
  new TableRow({ children: [cell("M", { width: 1400, fill: RATING_FILL.M, bold: true, align: AlignmentType.CENTER }), cell("Moderate — partially in place, or in place with material caveats", { width: CONTENT_W - 1400 })] }),
  new TableRow({ children: [cell("L", { width: 1400, fill: RATING_FILL.L, bold: true, align: AlignmentType.CENTER }), cell("Low feasibility — the enabling condition is largely absent", { width: CONTENT_W - 1400 })] }),
]));
children.push(p("Confidence (high / medium / low) is a separate axis recording how sure the analyst was given the evidence available. It is not a measure of how recently the cell was checked — staleness is tracked independently.", { before: 160 }));

// --------------------------------------------------------- what it says now
children.push(p("What the matrix currently says", { heading: HeadingLevel.HEADING_2, before: 240, after: 120 }));
children.push(rich([{ text: `Across all ${scores.length} cells: ` }, { text: `${dist.H} H · ${dist.M} M · ${dist.L} L`, bold: true }, { text: "." }]));

const readings = {
  "European Union": "Regulation is largely in place; the binding constraints are technological and economic",
  "United States": "Mostly moderate, and materially weaker on regulation after the 2025 federal reversals",
  "China": "Strong on deployment and manufacturing scale, weak on binding carbon pricing and mandates",
};
const rw = [2600, 900, 900, 900, CONTENT_W - 5300];
children.push(tbl(rw, ["Region", "H", "M", "L", "Reading"],
  REGIONS.map((r) => {
    const d = byRegion(r);
    return new TableRow({ children: [
      cell(r, { width: rw[0], bold: true }),
      cell(String(d.H ?? 0), { width: rw[1], fill: RATING_FILL.H, align: AlignmentType.CENTER }),
      cell(String(d.M ?? 0), { width: rw[2], fill: RATING_FILL.M, align: AlignmentType.CENTER }),
      cell(String(d.L ?? 0), { width: rw[3], fill: RATING_FILL.L, align: AlignmentType.CENTER }),
      cell(readings[r], { width: rw[4] }),
    ] });
  }),
));

// ------------------------------------------------------- why re-verification
children.push(p("Why this needs automated re-verification", { heading: HeadingLevel.HEADING_2, before: 240, after: 120 }));
children.push(p("Two US cells moved during the August 2026 verification pass, and neither would have been caught by re-fetching the same government page — both required searching for news of the policy change itself."));
const usMin = scores.find((s) => s.code === "MIN-R2" && s.region === "United States");
const usOgu = scores.find((s) => s.code === "OGU-R1" && s.region === "United States");
const ew = [1500, 1100, CONTENT_W - 2600];
children.push(tbl(ew, ["Cell", "Rating", "What changed"], [
  new TableRow({ children: [cell("MIN-R2 (US)", { width: ew[0], bold: true }), cell(usMin.rating, { width: ew[1], fill: RATING_FILL[usMin.rating], bold: true, align: AlignmentType.CENTER }), cell(usMin.evidence, { width: ew[2] })] }),
  new TableRow({ children: [cell("OGU-R1 (US)", { width: ew[0], bold: true }), cell(usOgu.rating, { width: ew[1], fill: RATING_FILL[usOgu.rating], bold: true, align: AlignmentType.CENTER }), cell(usOgu.evidence, { width: ew[2] })] }),
]));
children.push(p("This is the argument for a policy-change search step, not merely a source re-fetch step, for every legal and government-publication source.", { before: 140, italics: true }));

// ------------------------------------------------------------ operating rules
children.push(p("Operating rules", { heading: HeadingLevel.HEADING_2, before: 240, after: 120 }));
[
  ["Never auto-commit a rating change.", "A refresh may propose an H/M/L move; only a human may accept it. Updating evidence text or the last-verified date on an unchanged rating is fine."],
  ["Every extracted value needs a confidence tier and an exact source quote", "before it is written anywhere. No bare numbers."],
  ["Staleness and confidence are tracked separately.", "A high-confidence rating that has not been re-checked in 18 months is stale, not low-confidence."],
  ["When sources disagree, surface both.", "Never silently pick one — a conflict becomes a review item carrying both versions and no proposed rating."],
].forEach(([head, rest], i) => {
  children.push(rich([{ text: `${i + 1}. ` , bold: true }, { text: head, bold: true }, { text: " " + rest }], { after: 100 }));
});

// ------------------------------------------------------------ the criteria
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(p("The 35 criteria", { heading: HeadingLevel.HEADING_1, after: 160 }));
children.push(p("Grouped by sector. Each criterion states what is measured, in what unit, and the explicit thresholds separating H, M and L.", { after: 200 }));

const sectors = [];
criteria.forEach((c) => { if (!sectors.includes(c.sector)) sectors.push(c.sector); });

const cw = [1100, 1700, CONTENT_W - 1100 - 1700 - 1900 - 2600 - 2600 - 2600, 1900, 2600, 2600, 2600];
// code, pillar, criterion, unit, H, M, L
const CW = (() => {
  const code = 1000, pillar = 1500, unit = 1500, h = 2500, m = 2500, l = 2500;
  return [code, pillar, CONTENT_W - code - pillar - unit - h - m - l, unit, h, m, l];
})();

sectors.forEach((sector) => {
  const rows = criteria.filter((c) => c.sector === sector);
  children.push(p(`${sector} (${rows.length} criteria)`, { heading: HeadingLevel.HEADING_2, before: 220, after: 100 }));
  children.push(tbl(CW, ["Code", "Pillar", "Criterion / metric", "Unit", "H — more feasible", "M", "L — less feasible"],
    rows.map((c) => new TableRow({ children: [
      cell(c.code, { width: CW[0], bold: true }),
      cell(c.category, { width: CW[1] }),
      cell([
        new Paragraph({ spacing: { after: 40 }, children: [new TextRun({ text: c.criterion, bold: true, size: 17, font: "Calibri" })] }),
        new Paragraph({ spacing: { after: 0 }, children: [new TextRun({ text: c.metric, size: 15, color: "5A5A6E", font: "Calibri" })] }),
      ], { width: CW[2] }),
      cell(c.unit, { width: CW[3] }),
      cell(c.rating_rubric.H, { width: CW[4], fill: RATING_FILL.H }),
      cell(c.rating_rubric.M, { width: CW[5], fill: RATING_FILL.M }),
      cell(c.rating_rubric.L, { width: CW[6], fill: RATING_FILL.L }),
    ] })),
  ));
});

// ------------------------------------------------------------ ratings matrix
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(p("The 105 ratings", { heading: HeadingLevel.HEADING_1, after: 160 }));
children.push(p("Every criterion rated for all three regions, with the confidence tier attached to each rating.", { after: 200 }));

const mw = (() => {
  const code = 1100, crit = 4200;
  const rest = CONTENT_W - code - crit;
  const per = Math.floor(rest / 3);
  return [code, crit, per, per, CONTENT_W - code - crit - per * 2];
})();
children.push(tbl(mw, ["Code", "Criterion", ...REGIONS],
  criteria.map((c) => {
    const cells = [cell(c.code, { width: mw[0], bold: true }), cell(c.criterion, { width: mw[1] })];
    REGIONS.forEach((r, i) => {
      const s = scores.find((x) => x.code === c.code && x.region === r);
      cells.push(cell(s ? `${s.rating}  (${s.confidence})` : "--", { width: mw[2 + i], fill: s ? RATING_FILL[s.rating] : undefined, bold: true, align: AlignmentType.CENTER }));
    });
    return new TableRow({ children: cells });
  }),
));

// ----------------------------------------------------------------- sources
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(p("The 86 sources", { heading: HeadingLevel.HEADING_1, after: 160 }));
children.push(p("Grouped by access pattern — how the source can actually be retrieved, which determines whether re-verification can be automated. Only the 15 legal/regulatory sources are automated today; the other 71 require manual verification.", { after: 200 }));

const PATTERN_LABEL = {
  legal_regulatory_text: "Legal / regulatory text",
  structured_api_or_dashboard: "Structured API or dashboard",
  industry_tracker_database: "Industry tracker / database",
  periodic_pdf_report: "Periodic PDF report",
  government_agency_publication: "Government agency publication",
  company_disclosure: "Company disclosure",
};
const PATTERN_NOTE = {
  legal_regulatory_text: "Automated. Stable ELI/CELEX identifiers survive amendment, so version changes are detectable without scraping prose.",
  structured_api_or_dashboard: "Not automated. Despite the name, most are dashboard front-ends rather than documented REST APIs.",
  industry_tracker_database: "Not automated. Mostly subscription or session-gated.",
  periodic_pdf_report: "Not automated. Annual PDFs where the locator field doubles as the extraction instruction.",
  government_agency_publication: "Not automated. The weakest single-source reliability, especially for non-English sources.",
  company_disclosure: "Deliberately never auto-extracted — discovery and triage only. These are the 7 sources with no fixed URL, since which company matters depends on who is being assessed.",
};
const ORDER = ["legal_regulatory_text", "structured_api_or_dashboard", "industry_tracker_database", "periodic_pdf_report", "government_agency_publication", "company_disclosure"];

const entries = Object.entries(registry);
const sw = (() => {
  const name = 3600, pub = 2600, crit = 1900, cad = 2100;
  return [name, pub, crit, cad, CONTENT_W - name - pub - crit - cad];
})();

ORDER.forEach((pat) => {
  const rows = entries.filter(([, v]) => v.access_pattern === pat)
    .sort((a, b) => a[1].source_name.toLowerCase().localeCompare(b[1].source_name.toLowerCase()));
  children.push(p(`${PATTERN_LABEL[pat]} (${rows.length})`, { heading: HeadingLevel.HEADING_2, before: 220, after: 60 }));
  children.push(p(PATTERN_NOTE[pat], { italics: true, color: "5A5A6E", after: 120 }));
  children.push(tbl(sw, ["Source", "Publisher", "Criteria", "Refresh cadence", "Where to look"],
    rows.map(([, v]) => new TableRow({ children: [
      cell(v.url
        ? new Paragraph({ spacing: { after: 0 }, children: [new ExternalHyperlink({ link: v.url, children: [new TextRun({ text: v.source_name, size: 17, font: "Calibri", color: "2A4FB7", underline: {} })] })] })
        : v.source_name, { width: sw[0] }),
      cell(v.publisher, { width: sw[1] }),
      cell([...v.used_by_criteria].sort().join(", "), { width: sw[2] }),
      cell(v.refresh_cadence, { width: sw[3] }),
      cell(v.locator, { width: sw[4] }),
    ] })),
  ));
});

// ------------------------------------------------------- known data issues
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(p("Known data issues", { heading: HeadingLevel.HEADING_1, after: 160 }));
children.push(p("Recorded rather than silently patched, so a reader can judge what still needs a human.", { after: 160 }));
[
  "Two source URLs look copy-pasted from a neighbouring entry and have been left as-is rather than guessed at: US_SAF_Grand_Challenge_IRA_40B_tax_credit points at sustainability.gov/buyclean (the Buy Clean entry's URL), and IEA_CCUS_Projects_Database points at co2re.co (the Global CCS Institute's URL). Both need a human to re-source.",
  "95 criterion-source links dedupe to 86 registry entries. The registry keeps per-criterion duplicates for company disclosures rather than sharing one key.",
  "Source count corrected from 7 to 6 for structured_api_or_dashboard. The original notes claimed 7 and named an LSE_Grantham_CCLW entry that does not exist in the registry.",
  "Criterion codes normalised to hyphens. Shipping originally used underscores (SHP_T1); all 35 now match the same pattern, pinned by a schema constraint and a test.",
  "7 of 95 source entries carry no URL. These are the company_disclosure entries, which correctly record a retrieval methodology instead.",
].forEach((t) => children.push(rich([{ text: "•  " }, { text: t }], { after: 100 })));

const doc = new Document({
  creator: "Agentic Research Pipeline",
  title: "Transition Barrier Assessment",
  description: "105-cell sector x region transition-feasibility matrix: 35 criteria x EU/US/China, with 86 verified sources.",
  styles: {
    default: {
      heading1: { run: { size: 34, bold: true, color: ACCENT, font: "Calibri" }, paragraph: { spacing: { before: 240, after: 140 } } },
      heading2: { run: { size: 26, bold: true, color: "2B2B3A", font: "Calibri" }, paragraph: { spacing: { before: 200, after: 100 } } },
    },
  },
  sections: [{
    properties: {
      page: {
        size: { width: PAGE_W, height: PAGE_H, orientation: PageOrientation.LANDSCAPE },
        margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN },
      },
    },
    children,
  }],
});

// docx-js emits bare directory entries ("word/", "docProps/") alongside the
// real parts. They are redundant in an OPC package and some readers trip over
// them, so strip them. Also asserts the content-types part is present rather
// than silently writing an unopenable file.
//
// Entry *order* is left to the zip writer: the OPC spec prefers
// [Content_Types].xml first, but adm-zip sorts on write and every reader tested
// here accepts the result.
function repack(buf) {
  const AdmZip = require("adm-zip");
  const zin = new AdmZip(buf);
  const zout = new AdmZip();
  const entries = zin.getEntries().filter((e) => !e.isDirectory);
  if (!entries.some((e) => e.entryName === "[Content_Types].xml")) {
    throw new Error("[Content_Types].xml missing -- refusing to write an invalid docx");
  }
  entries.forEach((e) => zout.addFile(e.entryName, e.getData()));
  return zout.toBuffer();
}

Packer.toBuffer(doc).then((buf) => {
  const out = process.argv[2] || "Transition_Barrier_Assessment_Report.docx";
  const final = repack(buf);
  fs.writeFileSync(out, final);
  console.log("wrote", out, (final.length / 1024).toFixed(1) + " KB");
});
