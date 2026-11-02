# Finding exposed companies with encoder models

How BERT-like models and related models help identify companies that are **active in a field** (a theme such
as green hydrogen) or **exposed to a risk** (such as water scarcity or the EU carbon price), and how that
fits ARP.

Status: concept note, 2026-11-01. Nothing here has been measured on ARP data yet; numbers marked
*illustrative* are examples, not results. It belongs to the approved umbrella spec
`docs/superpowers/specs/2026-11-01-model-stack-design.md` (roadmap phase 3, "Universe / Taxonomy").

## In one paragraph

The models work as a **funnel**. Cheap models narrow about 4,000 companies to a shortlist, more precise models
check the shortlist, and the LLM debate in the Thematic Universe Builder (function #1) decides only on what is
left, citing exact quotes. Each step reads text and scores how well it fits the theme. No step can judge on its
own *how much* of a company's business that is: that needs revenue data.

## 1. Two questions, one method

| Question | Example | Main text sources | Non-text sources |
|---|---|---|---|
| **Activity**: does the company do X? | "Makes electrolysers", "Operates data centres" | business description (10-K Item 1, annual report "Business model"), segment notes, product pages, press releases | segment revenue (XBRL), patents, project databases |
| **Risk exposure**: is the company affected by Y? | "Water scarcity", "EU carbon price", "Asbestos litigation" | risk sections (10-K Item 1A, risk report, ESRS materiality), MD&A, earnings calls | plant locations × hazard maps, supply-chain graph, regulation scope (EU ETS installations) |

The funnel is the same for both. Only the theme definition and the source documents change.

## 2. The funnel

```
 Theme or risk definition (Taxonomy Library)
            │
 4,000 companies × document passages
            │
 [1] Embeddings (bi-encoder) ── shortlist by similarity ─────────►  ~300
            │
 [2] Cross-encoder ── precise fit of activity vs passage ────────►  ~120
            │
 [3] Zero-shot NLI ── does the passage support the claim? ───────►  ~80
            │
 [4] GLiNER spans ── products, projects, customers, sites
 [5] Domain filters ── ClimateBERT, FinBERT-FLS: done vs planned
            │
 [6] LLM debate + revenue share ── decision with quotes ────────►  final list
            │
 Person reviews (Decision Studio / review queue)
```

*Company counts are illustrative.*

### Step 0: define the theme (no model)

The Taxonomy Library (#2) holds the theme as a set of activities, each with a short description in plain words.
Good descriptions matter more than the model: the models compare passages with these sentences.

*Example, green hydrogen:* "Manufactures electrolysers or electrolyser stacks"; "Produces hydrogen by
electrolysis with renewable power"; "Builds or operates hydrogen pipelines or storage"; "Supplies components
(compressors, valves, membranes) for hydrogen systems".

Keep **producer** and **supplier** activities apart from the start; step 2 can only separate what the
taxonomy separates.

### Step 1: shortlist with embeddings

**How it works:** an embedding model turns each text into a vector, a list of a few hundred numbers that encodes
its meaning. Texts with similar meaning get vectors that point in similar directions (high cosine similarity),
even without shared words. All company passages are embedded once and stored; each activity description is
embedded and compared with all of them in milliseconds.

**Example:** "We delivered 200 MW of PEM stacks to European customers" is close to "Manufactures electrolysers",
although the word "electrolyser" never appears.

**Models:** today `paraphrase-multilingual-MiniLM-L12-v2` (in `arp/retrieval/embeddings.py`); candidates
`bge-m3`, `multilingual-e5-large`.

**Setting:** keep the top *k* passages per activity and every company with at least one passage above a
similarity threshold. Set the threshold for **high recall**: a company dropped here never comes back.

### Step 2: sharpen with a cross-encoder

**How it works:** the cross-encoder reads the activity and the passage *together* and outputs one fit score. It
sees how the words relate, so it is more precise than step 1, but about 100× slower, so it runs only on the
shortlist.

**Example:** "We supply valves to hydrogen projects" scores high for "Supplies components", low for
"Manufactures electrolysers".

**Models:** `bge-reranker-v2-m3` (multilingual), `ms-marco-MiniLM-L-6-v2` (English, fast). ARP already has a
reranker in `arp/retrieval/rerank.py` and on the `arp-models` service.

### Step 3: is it real? (zero-shot NLI)

**How it works:** a natural-language-inference model answers whether a passage **supports**, **contradicts** or
**says nothing about** a statement. Turn each activity into a statement ("The company makes or sells
electrolysers") and keep companies with at least one supporting passage. No training data is needed.

**Example:**

| Passage | Verdict |
|---|---|
| "Order intake for electrolysers rose 40% to €310m." | supports |
| "We are evaluating opportunities in hydrogen." | neither (talk, not business) |
| "We exited the electrolyser business in 2024." | contradicts |

**Models:** `MoritzLaurer/deberta-v3-large-zeroshot-v2.0`, multilingual `mDeBERTa-v3-base-xnli`.

### Step 4: what exactly? (GLiNER spans)

**How it works:** GLiNER marks text spans for labels you name at run time, without training. It produces the
evidence a reviewer wants to see.

**Example:** "Our 100 MW electrolyser in Hamburg, built with Shell, starts in 2026" → product "electrolyser",
project "100 MW … Hamburg", partner "Shell", year "2026".

### Step 5: done vs planned (domain filters)

**How it works:** small fine-tuned classifiers separate actions from intentions and specific statements from
boilerplate.

| Model | Separates | Example |
|---|---|---|
| ClimateBERT commitment | action / commitment vs none | "commissioned a 20 MW unit" → yes |
| ClimateBERT specificity | specific vs vague | "€1.1bn for decarbonisation in 2025" → specific |
| FinBERT-FLS | forward-looking vs not | "will invest by 2030" → forward-looking |

### Step 6: decide (LLM debate + numbers)

The existing Universe Builder runs an Advocate, an Opposing agent and an Adjudicator over the evidence, each
citing quotes that `arp/grounding.py` re-verifies. The **size** of the exposure comes from numbers, not from
similarity: segment revenue from XBRL (#18) or the financials extraction (#4).

*Example:* "Electrolysers ≈ 35% of revenue (segment report, p. 112)" → core exposure; "Hydrogen projects < 1% of
revenue" → peripheral.

## 3. Risk exposure: what changes

| Step | Activity (theme) | Risk exposure |
|---|---|---|
| 0 | Activities | Risk statements: "The company is affected by water scarcity at its sites" |
| Sources | Business description, segments | Risk sections, ESRS materiality, MD&A, earnings calls |
| 3 (NLI) | "The company makes X" | "The company says it is affected by Y" |
| 6 (size) | Revenue share | Share of sites, capacity or revenue in affected regions; cost estimates the company gives |

*Example:* Heidelberg Materials FY2025 lists water consumption as a financial risk ("Financial effects due to
water scarcity and environmental regulations"), so steps 1–3 find it. Martin Marietta's 10-K mentions drought
only in passing; text alone would rank it lower.

**Exposure companies do not write about** needs non-text data:

- plant or asset locations crossed with hazard maps (water stress, flood, heat);
- the supply-chain graph (`arp/company_graph.py`) and input-output propagation (Indirect Exposure, #7);
- regulation scope lists (EU ETS installation register, CBAM sectors).

Text models only see what companies choose to disclose. Use both and flag the gap: "exposed by data, silent in
text" is itself an engagement question.

## 4. Limits and how each is handled

| Limit | Example | Handled by |
|---|---|---|
| Mentioning ≠ doing | "Hydrogen could play a role" scores like a product line | step 3 (NLI), step 5 (forward-looking filter) |
| Relevant ≠ material | A conglomerate with 0.5% hydrogen revenue looks as close as a pure player | step 6, revenue share |
| Supplier ≠ producer | Valve maker vs electrolyser maker | separate activities (step 0) + cross-encoder (step 2) |
| Old or missing text | New products not yet in last year's report | Document Discovery (#6), news, earnings calls |
| Language | German or French reports | multilingual models (bge-m3, mDeBERTa) or translation first |
| Boilerplate | Every report says "climate change may affect us" | specificity filter (step 5), peer comparison |
| Thresholds | Which score counts as "exposed"? | set on a golden set, see section 5 |

## 5. Setting thresholds and measuring quality

1. **Golden set:** about 50–100 companies per theme, hand-labelled as core / peripheral / not exposed, mixed by
   sector, region and language, with the hard cases (suppliers, announcers, divested).
2. **Recall first in steps 1–2.** Set the thresholds so ≥ 95% of truly exposed companies survive; precision
   comes later.
3. **Precision at the end.** Measure the share of companies in the final list that the labels confirm.
4. **Compare with and without the funnel** (umbrella-spec rule): same final quality with fewer LLM calls, or
   better quality at the same cost.
5. **Re-check per theme.** A threshold tuned for hydrogen does not carry over to water risk.

## 6. Cost and run time

For 4,000 companies × about 200 passages each (about 800k passages), *estimates, not benchmarks*:

| Step | Runs on | Time | Compute cost |
|---|---|---|---|
| 1 Embeddings | L4 GPU (CPU possible) | ~15 min GPU, a few hours CPU; once per document, reused across themes | < $1 |
| 2 Cross-encoder | L4 | ~300 companies × 20 passages × activities: minutes | < $1 |
| 3 NLI | L4 | minutes on the shortlist | < $1 |
| 4–5 GLiNER, domain filters | L4 | minutes | < $1 |
| 6 LLM debate | Claude API | only on ~80 companies instead of 4,000 | the main saving |

The embeddings are computed once per document and serve every theme and risk, which is what makes the funnel
cheap.

## 7. Where this lives in ARP

| Piece | Today | Change |
|---|---|---|
| Theme definitions | Taxonomy Library (#2) | none; producer/supplier split is a content task |
| Embeddings, reranker | `arp/retrieval/`, `arp-models` service | move behind `arp/models/` (umbrella spec) |
| NLI, GLiNER, domain classifiers | not present | `classify`, `spans`, `tag` in `arp/models/` (umbrella spec) |
| LLM debate | `arp/research/matcher_agents.py`, `match_graph.py` | receives the shortlist instead of every candidate |
| Revenue share | XBRL Facts (#18), Financials (#4) | none |
| Non-text exposure | `arp/company_graph.py`, Indirect Exposure (#7) | none |
| Review | Decision Studio, review queue | none |

Implementation is a child spec of the umbrella spec, behind a setting that is off by default, and becomes the
default only if the golden-set comparison in section 5 shows a gain.

## 8. Open questions

- Which theme to use for the first golden set (a well-defined one such as electrolysers, or a fuzzy one such as
  "AI infrastructure")?
- Passage source: annual reports only, or also product web pages and press releases (fresher, noisier)?
- Should "exposed by data, silent in text" feed engagement selection directly?
