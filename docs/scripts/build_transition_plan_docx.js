const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, PageBreak,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle, LevelFormat,
  TableOfContents, Header, Footer, PageNumber, convertInchesToTwip,
} = require('docx');

// Regenerates docs/Transition_Plan_Assessment.docx from the single source of
// truth for the criteria -- backend/arp/transition_plan/data/indicators.json --
// so the document never drifts from what the pipeline actually asks.
//   npm install docx && node docs/scripts/build_transition_plan_docx.js
const REPO = path.resolve(__dirname, '..', '..');
const OUT = process.argv[2] || path.join(REPO, 'docs', 'Transition_Plan_Assessment.docx');
const indicators = JSON.parse(fs.readFileSync(path.join(REPO, 'backend/arp/transition_plan/data/indicators.json'), 'utf8'));

const ACCENT = '1F4E5A';
const ACCENT_LIGHT = 'E8F0F2';
const MUTED = '5A6B72';
const RULE = 'C7D3D8';

const CATEGORY_ORDER = ['target', 'governance', 'strategy', 'tracking'];
const CATEGORY_LABEL = { target: 'Target', governance: 'Governance', strategy: 'Strategy', tracking: 'Tracking' };
const CATEGORY_BLURB = {
  target: 'What the company has committed to: the existence, ambition, scope coverage, interim pathway and offsetting treatment of its emission reduction targets.',
  governance: 'Who is accountable: board structure, climate skills and capacity, oversight cadence, remuneration linkage, assurance and reporting boundaries.',
  strategy: 'How the transition is to be delivered: business-model integration, capex/opex/R&D planning, value-chain and policy engagement, fossil fuel phase-out, just transition and biosphere impacts.',
  tracking: 'What the company can actually show: reported scope 1/2/3 emissions, five-year emission and intensity trends, aligned and misaligned capex and revenues, and progress against stated targets.',
};

// ---------- derived statistics ----------
const byCategory = {};
for (const c of CATEGORY_ORDER) byCategory[c] = indicators.filter((i) => i.category === c);
const walkCount = indicators.filter((i) => i.walk_or_talk === 'walk').length;
const talkCount = indicators.filter((i) => i.walk_or_talk === 'talk').length;
const catWalk = (c) => byCategory[c].filter((i) => i.walk_or_talk === 'walk').length;
const catTalk = (c) => byCategory[c].filter((i) => i.walk_or_talk === 'talk').length;

// ---------- helpers ----------
const P = (text, opts = {}) => new Paragraph({
  spacing: { after: opts.after === undefined ? 120 : opts.after, line: 276 },
  alignment: opts.alignment,
  indent: opts.indent,
  children: [new TextRun({ text, size: opts.size || 21, color: opts.color, bold: opts.bold, italics: opts.italics, font: opts.font })],
  ...(opts.border ? { border: opts.border } : {}),
});

const H1 = (text) => new Paragraph({ text, heading: HeadingLevel.HEADING_1, spacing: { before: 360, after: 180 } });
const H2 = (text) => new Paragraph({ text, heading: HeadingLevel.HEADING_2, spacing: { before: 280, after: 140 } });
const H3 = (text) => new Paragraph({ text, heading: HeadingLevel.HEADING_3, spacing: { before: 220, after: 100 } });

const BULLET = (text, opts = {}) => new Paragraph({
  numbering: { reference: 'arp-bullets', level: 0 },
  spacing: { after: 90, line: 276 },
  children: [new TextRun({ text, size: 21 })],
  ...opts,
});

const RICH_BULLET = (runs) => new Paragraph({
  numbering: { reference: 'arp-bullets', level: 0 },
  spacing: { after: 90, line: 276 },
  children: runs,
});

const labelRun = (t) => new TextRun({ text: t, bold: true, size: 21, color: ACCENT });
const bodyRun = (t) => new TextRun({ text: t, size: 21 });
const codeRun = (t) => new TextRun({ text: t, size: 19, font: 'Consolas' });

const CELL_MARGINS = { top: 80, bottom: 80, left: 120, right: 120 };

function tableCell(children, { width, shading, bold, size, align, color }) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    margins: CELL_MARGINS,
    shading: shading ? { type: ShadingType.CLEAR, fill: shading, color: 'auto' } : undefined,
    children: Array.isArray(children)
      ? children
      : [new Paragraph({
          alignment: align,
          spacing: { after: 0, line: 260 },
          children: [new TextRun({ text: String(children), bold, size: size || 20, color })],
        })],
  });
}

function buildTable({ columnWidths, header, rows, zebra = true }) {
  const total = columnWidths.reduce((a, b) => a + b, 0);
  const headerRow = new TableRow({
    tableHeader: true,
    children: header.map((h, idx) =>
      tableCell(h.text !== undefined ? h.text : h, {
        width: columnWidths[idx],
        shading: ACCENT,
        bold: true,
        color: 'FFFFFF',
        align: h.align,
      })),
  });
  const bodyRows = rows.map((r, rIdx) => new TableRow({
    children: r.map((c, idx) =>
      tableCell(c && c.text !== undefined ? c.text : c, {
        width: columnWidths[idx],
        shading: zebra && rIdx % 2 === 1 ? ACCENT_LIGHT : undefined,
        align: c && c.align,
        bold: c && c.bold,
      })),
  }));
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths,
    borders: {
      top: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      left: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      right: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      insideVertical: { style: BorderStyle.SINGLE, size: 2, color: RULE },
    },
    rows: [headerRow, ...bodyRows],
  });
}

const SPACER = () => new Paragraph({ spacing: { after: 160 }, children: [] });

// ---------- document body ----------
const children = [];

// Title page
children.push(
  new Paragraph({ spacing: { before: 2200, after: 0 }, children: [
    new TextRun({ text: 'AGENTIC RESEARCH PIPELINE', size: 20, bold: true, color: MUTED, characterSpacing: 40 }),
  ]}),
  new Paragraph({
    spacing: { before: 160, after: 80 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: ACCENT, space: 8 } },
    children: [new TextRun({ text: 'Transition Plan Assessment', size: 56, bold: true, color: ACCENT })],
  }),
  new Paragraph({ spacing: { before: 200, after: 400 }, children: [
    new TextRun({ text: 'Methodology and the complete catalogue of all 64 assessment criteria', size: 26, color: MUTED }),
  ]}),
  P('A replication of Colesanti Senni, Schimanski, Bingler, Ni & Leippold (2024), "Using AI to assess corporate climate transition disclosures", Environmental Research Communications — as implemented in backend/arp/transition_plan/.', { size: 21, color: MUTED, after: 600 }),
);

children.push(buildTable({
  columnWidths: [2600, 6400],
  header: [{ text: 'Document' }, { text: 'Detail' }],
  rows: [
    ['Scope', 'Transition Plan Assessment module — framework, scoring method, and all 64 indicators verbatim'],
    ['Criteria count', `64 (Target ${byCategory.target.length}, Governance ${byCategory.governance.length}, Strategy ${byCategory.strategy.length}, Tracking ${byCategory.tracking.length})`],
    ['Classification split', `${walkCount} "walk" indicators, ${talkCount} "talk" indicators`],
    ['Criteria source', 'backend/arp/transition_plan/data/indicators.json (from the paper’s reference implementation, github.com/tobischimanski/transition_NLP)'],
    ['Generated', new Date().toISOString().slice(0, 10)],
  ],
}));

children.push(new Paragraph({ children: [new PageBreak()] }));

// TOC
children.push(H1('Contents'));
children.push(new TableOfContents('Contents', { hyperlink: true, headingStyleRange: '1-3' }));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 1. Overview
children.push(H1('1. Overview'));
children.push(P('The Transition Plan Assessment scores a company’s climate-related disclosures against 64 fixed yes/no indicators drawn from Colesanti Senni, Schimanski, Bingler, Ni & Leippold (2024). Each indicator is answered once per company by a retrieval-augmented generation (RAG) step: the system retrieves the most relevant passages from the company’s own reports, asks a senior-sustainability-analyst persona for a YES / NO / NA verdict with a short critical explanation, and then independently re-verifies every quotation the model cites against the original document before the verdict is trusted.'));
children.push(P('Every indicator carries two fixed attributes: a category (Target, Governance, Strategy or Tracking) and a "walk or talk" classification. "Talk" indicators cover future targets and general management approaches — statements that are cheap to make. "Walk" indicators cover concrete, already-verifiable activity. Reporting the two separately is the point of the framework: the paper’s headline finding, across 143 Climate Action 100+ companies, is that corporate disclosure skews heavily toward talk and away from walk.'));

children.push(H2('1.1 Source and fidelity'));
children.push(BULLET('The indicator set — identifier, exact question text, expert-centric guideline and walk/talk classification — is bundled verbatim from the paper’s own reference implementation (questions_masterfile_100524.xlsx), not retyped from the PDF, so the wording matches exactly what the paper’s tool asked.'));
children.push(BULLET('The analyst persona and the substantive answering guidelines in the system prompt are verbatim from the paper’s Figure S.2 prompt template — the greenwashing skepticism, "cheap talk" awareness, and grounding instructions validated in the paper’s human evaluation with 28 domain experts across 26 institutions.'));
children.push(BULLET('The basic-company-information step (company, sector, location, resolved once per company and reused in all 64 prompts) mirrors the reference implementation’s basicInformation() function and its Figure S.1 prompt.'));

children.push(H2('1.2 Where it runs in the codebase'));
children.push(buildTable({
  columnWidths: [3400, 5600],
  header: [{ text: 'Component' }, { text: 'File' }],
  rows: [
    ['Criteria catalogue (static data)', 'backend/arp/transition_plan/data/indicators.json'],
    ['Catalogue loader', 'backend/arp/transition_plan/indicators.py'],
    ['Basic company information agent', 'backend/arp/transition_plan/basic_info_agent.py'],
    ['Per-indicator RAG agent and prompt', 'backend/arp/transition_plan/indicator_agent.py'],
    ['Per-indicator LangGraph flow', 'backend/arp/transition_plan/indicator_graph.py'],
    ['Verdict grounding and confidence', 'backend/arp/transition_plan/aggregator.py'],
    ['Per-company orchestration and scoring', 'backend/arp/transition_plan/company_assessment.py'],
    ['Batch run pipeline (universe scale)', 'backend/arp/transition_plan/pipeline.py'],
    ['Record and indicator schemas', 'backend/arp/schemas/transition_plan.py'],
    ['REST API', 'backend/arp/api/routers/transition_plan.py'],
    ['CLI', 'arp transition-plan indicators | run'],
    ['Frontend view', 'frontend/src/pages/TransitionPlanAssessment.tsx'],
  ],
}));

// 2. Framework structure
children.push(H1('2. The criteria framework'));
children.push(P('The 64 criteria are fixed — identical for every company, in every run — which is what makes scores comparable across a universe. They distribute across the four categories and the two classifications as follows.'));

children.push(H2('2.1 Distribution by category and classification'));
children.push(buildTable({
  columnWidths: [2400, 1500, 1500, 1500, 2100],
  header: [{ text: 'Category' }, { text: 'Criteria', align: AlignmentType.CENTER }, { text: 'Walk', align: AlignmentType.CENTER }, { text: 'Talk', align: AlignmentType.CENTER }, { text: 'Indicator numbers' }],
  rows: [
    ...CATEGORY_ORDER.map((c) => [
      CATEGORY_LABEL[c],
      { text: String(byCategory[c].length), align: AlignmentType.CENTER },
      { text: String(catWalk(c)), align: AlignmentType.CENTER },
      { text: String(catTalk(c)), align: AlignmentType.CENTER },
      `${byCategory[c][0].number}–${byCategory[c][byCategory[c].length - 1].number}`,
    ]),
    [
      { text: 'Total', bold: true },
      { text: '64', align: AlignmentType.CENTER, bold: true },
      { text: String(walkCount), align: AlignmentType.CENTER, bold: true },
      { text: String(talkCount), align: AlignmentType.CENTER, bold: true },
      { text: '1–64', bold: true },
    ],
  ],
}));

children.push(SPACER());
children.push(H2('2.2 What each category covers'));
for (const c of CATEGORY_ORDER) {
  children.push(new Paragraph({
    spacing: { before: 140, after: 60 },
    children: [labelRun(`${CATEGORY_LABEL[c]} (${byCategory[c].length} criteria) — `), bodyRun(CATEGORY_BLURB[c])],
  }));
}

children.push(SPACER());
children.push(H2('2.3 Walk versus talk'));
children.push(new Paragraph({ spacing: { after: 100 }, children: [
  labelRun('Talk — '), bodyRun(`${talkCount} criteria. Future targets and general management approaches: a stated net zero ambition, a governance structure, a described strategy. These are costless to assert, so a YES here is evidence of intent, not of delivery.`),
]}));
children.push(new Paragraph({ spacing: { after: 100 }, children: [
  labelRun('Walk — '), bodyRun(`${walkCount} criteria. Concrete, already-verifiable activity: reported scope 1/2/3 emissions, five-year emission trends, capex and revenue alignment figures, fossil fuel phase-out activity, board information cadence. A YES here requires something that already happened and can be checked.`),
]}));
children.push(P('Because the two are counted separately, a company with a high overall disclosed count but a low walk share is visibly a talker — which is precisely the diagnostic the framework exists to produce.'));

// 3. Assessment method
children.push(H1('3. How a criterion is assessed'));
children.push(P('One company’s assessment runs the same flow 64 times, once per criterion, after a single per-company preparation step.'));

children.push(H3('Step 0 — Preparation (once per company)'));
children.push(BULLET('Every source document for the company is fetched through the document registry and chunked once.'));
children.push(BULLET('A basic-information call resolves company name, sector and headquarters location from the report itself. The resulting three-line block is injected into all 64 indicator prompts as shared context, exactly as in the paper’s tool.'));

children.push(H3('Step 1 — Evidence selection'));
children.push(BULLET('The criterion’s question text is used as the retrieval query; the top 8 chunks are selected, matching the paper’s Top-K retrieval parameter (Table S.6).'));
children.push(BULLET('Retrieval always returns its top chunks regardless of keyword overlap, so a genuinely silent report reaches the model and is answered NA, rather than being skipped before it is ever asked.'));
children.push(BULLET('If no evidence at all exists (no documents, no chunks), the criterion short-circuits to a NA verdict with confidence 0.0 and is not routed to human review — most companies are silent on most criteria, and that is reported plainly rather than as an exception.'));

children.push(H3('Step 2 — The grounded verdict'));
children.push(P('The model answers as a senior sustainability analyst under the paper’s own guidelines: be precise and grounded in specific extracts; acknowledge uncertainty rather than fabricate; stay within a 200-word answer cap; be skeptical of greenwashing and answer in a critical tone; treat cheap talk as cheap talk; acknowledge that everything disclosed is the company’s own view; and scrutinise whether the report rests on quantifiable data or on vague, unverifiable statements. It returns three things:'));
children.push(RICH_BULLET([labelRun('verdict — '), bodyRun('YES if the report discloses the requested information, NO if it does not, NA if the question does not apply (for example, a question that presupposes the use of carbon offsets when the company reports none).')]));
children.push(RICH_BULLET([labelRun('answer — '), bodyRun('a critical, evidence-grounded explanation of the verdict, capped at 200 words.')]));
children.push(RICH_BULLET([labelRun('citations — '), bodyRun('verbatim quotes, each tagged with the document it came from.')]));

children.push(H3('Step 3 — Programmatic grounding check'));
children.push(P('Each cited quote is re-checked in code against the real text of the document it claims to quote, using whitespace-normalised exact-or-near-exact matching. A model that fabricates a quotation is caught mechanically, every time, regardless of how confident its prose sounds. The verdict’s confidence and review routing follow directly from that check:'));
children.push(buildTable({
  columnWidths: [3600, 1400, 1600, 2400],
  header: [{ text: 'Case' }, { text: 'Confidence', align: AlignmentType.CENTER }, { text: 'Human review', align: AlignmentType.CENTER }, { text: 'Reading' }],
  rows: [
    ['At least one citation verified against the source', { text: '1.0', align: AlignmentType.CENTER }, { text: 'No', align: AlignmentType.CENTER }, 'Trusted'],
    ['Verdict is NA', { text: '1.0', align: AlignmentType.CENTER }, { text: 'No', align: AlignmentType.CENTER }, '"Does not apply" needs no quote'],
    ['Citations offered, none verified', { text: '0.3', align: AlignmentType.CENTER }, { text: 'Yes', align: AlignmentType.CENTER }, 'May be right; nothing backs it'],
    ['YES/NO verdict with no citations at all', { text: '0.2', align: AlignmentType.CENTER }, { text: 'Yes', align: AlignmentType.CENTER }, 'Least trustworthy case'],
    ['No relevant evidence found in any document', { text: '0.0', align: AlignmentType.CENTER }, { text: 'No', align: AlignmentType.CENTER }, 'Reported as NA, the common case'],
  ],
}));

children.push(SPACER());
children.push(H2('3.1 Two deliberate deviations from the paper'));
children.push(RICH_BULLET([labelRun('Programmatic citation grounding instead of an LLM-self-reported source list. '), bodyRun('The paper’s tool asks the model which numbered source chunk it used and reports that as-is. Here, every quote is independently re-verified against the original document before the verdict is accepted, and an ungrounded YES/NO is routed to the review queue rather than taken at face value.')]));
children.push(RICH_BULLET([labelRun('BM25 evidence selection instead of embeddings. '), bodyRun('The paper’s RAG stack (LlamaIndex with text-embedding-ada-002, top-8) is replicated behaviourally — always retrieve the top 8 chunks, let the model answer NA when they are irrelevant — using this codebase’s deterministic, embedding-free BM25 retriever, adding no extra API cost.')]));
children.push(P('Everything else follows the paper’s design: one criterion, one retrieval, one LLM call (no second-pass verifier, unlike this codebase’s extraction pipelines — the paper’s tool is single-pass RAG and this replication keeps that shape), a 200-word answer cap, and a per-company walk/talk-annotated verdict grid.'));

// 4. Outputs
children.push(H1('4. Scoring and outputs'));
children.push(P('Each company’s record carries the full 64-criterion verdict grid plus the aggregate scores computed from it.'));
children.push(buildTable({
  columnWidths: [2800, 6200],
  header: [{ text: 'Metric' }, { text: 'Definition' }],
  rows: [
    ['disclosed_count', 'Number of YES verdicts out of 64 — the paper’s core disclosure-completeness score.'],
    ['walk_disclosed_count / walk_total_count', `YES verdicts among the ${walkCount} walk criteria — concrete, verifiable activity.`],
    ['talk_disclosed_count / talk_total_count', `YES verdicts among the ${talkCount} talk criteria — targets and stated approaches.`],
    ['by_category', 'Disclosed count out of total for each of Target, Governance, Strategy and Tracking.'],
    ['overall_confidence', 'Mean confidence across all answered (non-NA) criteria.'],
    ['needs_review', 'True if any single criterion was routed to the human review queue.'],
    ['indicators[]', 'Per criterion: verdict, explanation, citations with their grounded flag, confidence and review flag.'],
  ],
}));
children.push(SPACER());
children.push(P('Runs are checkpointed and resumable: companies are processed with batch-level concurrency, results and errors are appended to per-run files, progress and cost are tracked per company, and an already-completed company is skipped on resume. A cancel request stops the batch cooperatively — in-flight companies still finish and checkpoint.'));

children.push(H2('4.1 Running an assessment'));
children.push(new Paragraph({ spacing: { after: 60 }, children: [codeRun('arp transition-plan indicators              # inspect the 64 criteria')] }));
children.push(new Paragraph({ spacing: { after: 60 }, children: [codeRun('arp transition-plan indicators --out x.json # export the catalogue as JSON')] }));
children.push(new Paragraph({ spacing: { after: 60 }, children: [codeRun('arp transition-plan run --universe companies.csv')] }));
children.push(new Paragraph({ spacing: { after: 160 }, children: [codeRun('arp runs show <run_id>                      # progress, cost, review count')] }));
children.push(P('The same surface is available over REST: GET /api/transition-plan/indicators returns the criteria catalogue; POST /api/transition-plan/runs starts a run over a company list or universe file; GET /api/transition-plan/runs/{run_id} and .../results return progress and per-company records; and the review-queue, review-decisions, review-history and review endpoints drive the human checkpoint for any criterion whose verdict could not be grounded.'));

children.push(new Paragraph({ children: [new PageBreak()] }));

// 5. Full catalogue
children.push(H1('5. The 64 assessment criteria'));
children.push(P('All 64 criteria in full, grouped by category and in the paper’s own numbering. For each: the exact question put to the model, and the expert-centric guideline that accompanies it in the prompt as binding interpretation guidance on how the question is to be answered. Both are reproduced verbatim from the criteria catalogue.'));

children.push(H2('5.1 Criteria index'));
children.push(buildTable({
  columnWidths: [700, 2100, 1500, 1000, 3700],
  header: [{ text: '#', align: AlignmentType.CENTER }, { text: 'Identifier' }, { text: 'Category' }, { text: 'Class', align: AlignmentType.CENTER }, { text: 'Topic' }],
  rows: indicators.map((i) => [
    { text: String(i.number), align: AlignmentType.CENTER },
    i.identifier,
    CATEGORY_LABEL[i.category],
    { text: i.walk_or_talk === 'walk' ? 'Walk' : 'Talk', align: AlignmentType.CENTER },
    i.identifier.replace(/^A_/, '').replace(/_\d+$/, '').replace(/_/g, ' ').replace(/^\w/, (m) => m.toUpperCase()),
  ]),
}));

let section = 2;
for (const c of CATEGORY_ORDER) {
  children.push(new Paragraph({ children: [new PageBreak()] }));
  children.push(H2(`5.${++section - 1} ${CATEGORY_LABEL[c]} criteria (${byCategory[c].length})`));
  children.push(P(CATEGORY_BLURB[c], { color: MUTED }));
  for (const i of byCategory[c]) {
    children.push(new Paragraph({
      heading: HeadingLevel.HEADING_3,
      spacing: { before: 260, after: 60 },
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: RULE, space: 4 } },
      children: [
        new TextRun({ text: `${i.number}. ${i.identifier}`, bold: true }),
        new TextRun({ text: `   ·   ${CATEGORY_LABEL[i.category]} · ${i.walk_or_talk === 'walk' ? 'Walk' : 'Talk'}`, size: 18, color: MUTED, bold: false }),
      ],
    }));
    children.push(new Paragraph({
      spacing: { before: 100, after: 100, line: 276 },
      children: [labelRun('Question:  '), new TextRun({ text: i.question, size: 21, bold: true })],
    }));
    children.push(new Paragraph({
      spacing: { after: 140, line: 276 },
      children: [labelRun('Guideline:  '), bodyRun(i.guideline)],
    }));
  }
}

// Reference
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(H1('Reference'));
children.push(P('Colesanti Senni, C., Schimanski, T., Bingler, J., Ni, J., & Leippold, M. (2024). Using AI to assess corporate climate transition disclosures. Environmental Research Communications. Working paper: SSRN 4826207. Reference implementation: github.com/tobischimanski/transition_NLP.'));
children.push(P('Implementation mapping, including the two deliberate deviations described in section 3.1: docs/METHODOLOGY.md → "Transition Plan Assessment".'));

// ---------- assemble ----------
const doc = new Document({
  creator: 'Agentic Research Pipeline',
  title: 'Transition Plan Assessment — Methodology and Criteria',
  description: 'The Transition Plan Assessment module: framework, scoring method and all 64 assessment criteria.',
  styles: {
    default: {
      document: { run: { font: 'Calibri', size: 21, color: '20282B' } },
      heading1: { run: { font: 'Calibri', size: 32, bold: true, color: ACCENT }, paragraph: { spacing: { before: 360, after: 180 } } },
      heading2: { run: { font: 'Calibri', size: 26, bold: true, color: ACCENT }, paragraph: { spacing: { before: 280, after: 140 } } },
      heading3: { run: { font: 'Calibri', size: 22, bold: true, color: '2E3B40' }, paragraph: { spacing: { before: 220, after: 100 } } },
    },
  },
  numbering: {
    config: [{
      reference: 'arp-bullets',
      levels: [{
        level: 0,
        format: LevelFormat.BULLET,
        text: '•',
        alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: convertInchesToTwip(0.3), hanging: convertInchesToTwip(0.18) } } },
      }],
    }],
  },
  sections: [{
    properties: { page: { margin: { top: 1300, right: 1300, bottom: 1300, left: 1300 } } },
    headers: {
      default: new Header({ children: [new Paragraph({
        alignment: AlignmentType.RIGHT,
        spacing: { after: 100 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: RULE, space: 6 } },
        children: [new TextRun({ text: 'Transition Plan Assessment — Methodology and Criteria', size: 16, color: MUTED })],
      })]}),
    },
    footers: {
      default: new Footer({ children: [new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ children: ['Page ', PageNumber.CURRENT, ' of ', PageNumber.TOTAL_PAGES], size: 16, color: MUTED })],
      })]}),
    },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log(`Wrote ${OUT} (${(buf.length / 1024).toFixed(1)} KB), ${indicators.length} criteria`);
});
