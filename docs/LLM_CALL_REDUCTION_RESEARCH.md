# Fewer LLM Calls in Report Extraction and Verification: What the Primary Sources Say

*Researched 2026-10-13. Sources: original papers (arXiv abstract pages, and the full PDF wherever a number comes from
the body), Anthropic's platform.claude.com docs and anthropic.com engineering posts, the SEC EDGAR API page, ESMA's
ESEF Reporting Manual (October 2025 update) and its December 2024 consultation paper, XBRL International
specifications and the XBRL US data-quality rules page. No blog summaries of papers are used. Pages that could not be
fetched are listed at the end.*

## Summary

The sources point to three ways of cutting calls that need not cost precision. First, do not call a model where a
deterministic source or check already decides: tagged XBRL facts
([SEC companyfacts](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)), quotes matched as
strings, arithmetic identities ([Calculations 1.1](https://www.xbrl.org/Specification/calculation-1.1/REC-2023-02-22/calculation-1.1-REC-2023-02-22.html)).
Second, ask for related fields in one call when they come from the same evidence. On document-extraction benchmarks a
joint prompt matched or beat one call per field ([Joint Extraction Matters](https://arxiv.org/abs/2503.16868)), but
that evidence covers receipts and forms with 2 to 6 fields, and accuracy falls as batches and contexts grow
([BatchPrompt](https://arxiv.org/abs/2309.00384), [Lost in the Middle](https://arxiv.org/abs/2307.03172)). Third,
spend a verification call only where a measured signal says it is needed. Cascades save roughly 50 to 98% of cost on
their own benchmarks ([FrugalGPT](https://arxiv.org/abs/2305.05176), [AutoMix](https://arxiv.org/abs/2310.12963)), but
their gates are learned from task data or built on agreement between samples. A model's self-reported confidence is a
weak gate: failure-prediction AUROC of 0.52 to 0.69 in the two studies that measure it
([Xiong et al.](https://arxiv.org/abs/2306.13063), and [ExtractConf](https://arxiv.org/abs/2606.24420) on document
field extraction). Verification catches more when the checker does not see the draft
([CoVe](https://arxiv.org/abs/2309.11495)), and agreement between two strong models is weaker evidence than it looks,
because their errors are correlated ([Kim et al.](https://arxiv.org/abs/2506.07962)). Provider features
([Message Batches](https://platform.claude.com/docs/en/build-with-claude/batch-processing),
[prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching),
[structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)) cut cost or retries,
not the number of logical calls. For this repo the safest cut is to stop calling the adjudicator on high-risk fields,
whose disagreements go to human review anyway. The largest cut is to group fields that share a table into one extractor
call and one blind-verifier call. The repo already does that for financials and TNFD; for the per-field graph it has
to be tested on the golden set first.

---

## 1. Multi-field and batched extraction

- **Batch prompting: several inputs, one call.** Cheng et al. put several samples in one prompt and report that it
  "reduces the LLM (Codex) inference token and time costs" by "up to 5x with six samples in batch" "while achieving
  better or comparable performance", with the benefits also holding for GPT-3.5 and GPT-4. They add that "the number of
  samples in each batch and the complexity of tasks affect its performance"
  ([Batch Prompting, EMNLP 2023 Industry](https://arxiv.org/abs/2301.08721)). This batches *different inputs* under
  one instruction, which is not the same as asking for many fields of one document.
- **Bigger batches in longer contexts lose accuracy.** Lin et al. find that "prompting with batched data in longer
  contexts will inevitably lead to worse performance, compared to single-data prompting", and that accuracy "is
  significantly correlated with the positions and order of the batched data". With their permutation-and-ensembling fix
  (which re-asks the batch in several orders, adding calls back) they reach single-prompt accuracy "using just 9%-16%
  the number of LLM calls" at batch size 32, e.g. BoolQ 90.6% to 90.9%
  ([BatchPrompt](https://arxiv.org/abs/2309.00384)).
- **Several instructions in one call can help.** On MTI Bench (25 tasks of 2 to 3 sub-tasks), multi-task inference
  "reduces the total inference time by 1.46 times", and Llama-2-Chat-70B and GPT-4 "show up to 7.3% and 12.4% improved
  performance" over one sub-task per call ([Multi-Task Inference, ACL 2024](https://arxiv.org/abs/2402.11597)).
- **The closest test of per-field vs joint extraction.** Loem and Hosaka compare one prompt per field with one prompt
  for several fields on document images and conclude that "jointly extracting fields often improves accuracy,
  especially when the fields share strong numeric or contextual dependencies"
  ([Joint Extraction Matters](https://arxiv.org/abs/2503.16868)). Document-level accuracy (all queried fields right),
  separate → joint, from Table 2 of the PDF:

  | Model | CORDv2 | SROIE | FUNSD |
  |---|---|---|---|
  | Qwen2-VL-2B | 0.77 → 0.83 | 0.94 → 0.95 | 0.57 → 0.71 |
  | Llama-3.2-11B | 0.40 → 0.71 | 0.81 → 0.83 | 0.73 → 0.79 |
  | GPT-4o | 0.96 → 0.98 | 0.97 → 0.98 | 0.79 → 0.97 |

  The gain was largest for numerically confusable fields (tax vs cash on receipts) and smallest for distinct ones.
  Varying the request from 2 to 6 fields, "separate extraction accuracy declines more rapidly for larger numbers of
  fields, likely due to errors compounding with each additional independent query". Limits: receipts and forms, at most
  6 fields, the whole document visible in every call, and the authors leave latency and cost "outside the scope of this
  work".
- **Per-field and whole-document prompts fail differently.** In a 55-field invoice benchmark, a field-guided call that
  fills each slot "under schema-slot completion pressure" "hallucinates values for absent fields", while a
  document-guided call "misses visually non-salient ones" ([ExtractConf](https://arxiv.org/abs/2606.24420), a
  single-author workshop paper). Absent fields are the per-field prompt's weak spot.
- **Limits on how much to pack into one prompt.** Even the best of 20 models "only achieve 68% accuracy at the max
  density of 500 instructions", with a "bias towards earlier instructions"
  ([IFScale](https://arxiv.org/abs/2507.11538)). In long inputs "performance is often highest when relevant information
  occurs at the beginning or end of the input context, and significantly degrades when models must access relevant
  information in the middle" ([Lost in the Middle, TACL](https://arxiv.org/abs/2307.03172)).
- **Domain systems group by item, not by schema.** ESGReveal runs one retrieval and one prompt per ESG indicator and asks
  for several attributes of that indicator at once, "<Disclosure, KPI, Topic, Value, Unit, Target, Action>" (PDF §3.4.2,
  [ESGReveal](https://arxiv.org/abs/2312.17264)). ChatReport runs one retrieval and one prompt per TCFD recommendation
  (PDF §3.1, [ChatReport](https://arxiv.org/abs/2307.15770)).
- **Gap.** No paper found compares per-field and grouped-field prompts on long annual or sustainability reports with
  per-field retrieval. The positive results above come from short documents or from QA/NLI benchmarks.

## 2. Cascades and routing

- **FrugalGPT.** A learned cascade "can match the performance of the best individual LLM (e.g. GPT-4) with up to 98% cost
  reduction or improve the accuracy over GPT-4 by 4% with the same cost"
  ([FrugalGPT](https://arxiv.org/abs/2305.05176)). The gate is "a simple regression model that learns whether a
  generation is correct" (a fine-tuned DistilBERT in the case study), so it needs labelled data. The 98% figure is on
  HEADLINES, a financial-news classification set, not extraction (PDF, experiments).
- **RouteLLM (ICLR 2025).** Routers trained on preference data cut cost "by over 2 times in certain cases"
  ([RouteLLM](https://arxiv.org/abs/2406.18665)). With half the calls going to GPT-4, MT Bench reached 95% of GPT-4's
  score. On MMLU, routers trained only on Arena data performed "at the level of the random router" because the questions
  were out of distribution; adding about 1,500 golden-labelled MMLU samples fixed that (PDF, MMLU results). A router needs
  in-domain labels.
- **Consistency as the escalation signal.** Yue et al. use the weak model's "answer consistency" across samples as a
  difficulty proxy; the cascade matches GPT-4 while needing "only 40% of its cost"
  ([MoT cascades, ICLR 2024](https://arxiv.org/abs/2310.03094)).
- **Self-verification as the signal.** AutoMix routes on a few-shot self-check but notes that "self-verification can be
  noisy" and adds a POMDP router on top, "reducing computational cost by over 50% for comparable performance"
  ([AutoMix, NeurIPS 2024](https://arxiv.org/abs/2310.12963)).
- **Speculative cascades.** Narasimhan et al. implement the cascade's deferral rule "through speculative execution",
  borrowing from speculative decoding ([Faster Cascades via Speculative Decoding](https://arxiv.org/abs/2405.19261)).
  My reading: this works at token level and needs both models' token distributions, which a hosted API call does not
  expose, so it does not apply here.
- **Anthropic's routing pattern.** "Routing classifies an input and directs it to a specialized followup task", e.g.
  "easy/common questions to smaller, cost-efficient models"
  ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)).
- **Domain caution.** On ESG data extraction from 166 Hong Kong reports, GPT-4 reached 76.9% accuracy against 54.9%
  (Qwen), 47.1% (GPT-3.5) and 46.2% (ChatGLM) (PDF §5.1.2, [ESGReveal](https://arxiv.org/abs/2312.17264)). With a gap
  that size, a cheap-first extractor would escalate often, and each escalation is an extra call.
- **Cascades cut cost, not call count.** Every escalation adds a call. They reduce calls only when the cheap step is a
  rule or a cached result instead of a model.

## 3. Selective verification: how good is confidence as a gate?

- **Self-knowledge in the best case.** Kadavath et al. find that "larger models are well-calibrated on diverse multiple
  choice and true/false questions" and that self-evaluation (P(True)) improves when a model sees many of its own
  samples, but models "struggle with calibration of P(IK) on new tasks"
  ([Language Models (Mostly) Know What They Know](https://arxiv.org/abs/2207.05221)).
- **Verbalised beats token probability for chat models.** For ChatGPT, GPT-4 and Claude, "verbalized confidences
  emitted as output tokens are typically better-calibrated than the model's conditional probabilities", "often reducing
  the expected calibration error by a relative 50%" ([Just Ask for Calibration, EMNLP 2023](https://arxiv.org/abs/2305.14975)).
- **But still overconfident and weak at failure prediction.** "LLMs, when verbalizing their confidence, tend to be
  overconfident"; white-box methods do better "but the gap is narrow, e.g., 0.522 to 0.605 in AUROC", and "all
  investigated methods struggle in challenging tasks, such as those requiring professional knowledge"
  ([Xiong et al., ICLR 2024](https://arxiv.org/abs/2306.13063)).
- **The one study on document field extraction.** On DocILE invoices (GPT-4o, 26% field failure rate), "logprob-mean
  achieves only 0.705 ROC AUC", "Verbalized self-assessed confidence fares similarly (0.692 AUC)", and self-consistency
  over five samples "achieves only 0.744 AUC … at 5× the single-call API cost". All three "collapse toward all-positive
  behaviour at practical thresholds". A classifier fusing cross-call disagreement with document signals reached 0.928
  AUC and "99.1%" accuracy "at 80% coverage" ([ExtractConf](https://arxiv.org/abs/2606.24420)). Caveat: scanned
  invoices with OCR noise, one author, workshop venue.
- **Sequence likelihood is a poor gate too.** Ren et al. cite "the limitations of using sequence-level probability
  estimates" and find token-level self-evaluation (multiple choice or true/false) correlates better with quality
  ([Self-Evaluation Improves Selective Generation](https://arxiv.org/abs/2312.09300)).
- **Sampling-based uncertainty costs calls.** Semantic entropy is "more predictive of model accuracy on question
  answering data sets than comparable baselines" but is computed over several sampled answers
  ([Semantic Uncertainty, ICLR 2023](https://arxiv.org/abs/2302.09664)).
- **Conformal methods turn a score into a guarantee, given labels.** Conformal risk control bounds "the expected value
  of any monotone loss function" ([Angelopoulos et al.](https://arxiv.org/abs/2208.02814)). Conformal factuality gives
  "80-90% correctness guarantees" and "requires very few human-annotated samples"
  ([Mohri & Hashimoto](https://arxiv.org/abs/2402.10978)). Trust or Escalate calibrates a cascade of LLM judges on a
  held-out set (|D_cal| = 500 in its experiments) and "guarantees over 80% human agreement with almost 80% test
  coverage"; 88.1% of covered items were judged by "substantially cheaper Mistral-7B or GPT-3.5 instead of GPT-4"
  ([Trust or Escalate](https://arxiv.org/abs/2407.18370), PDF introduction and experiments).
- **Answer to "how reliable is self-reported confidence as a gate?"** Not reliable enough to skip a check on its own. It
  is better than token probabilities for chat models, but its failure-prediction AUROC sits between about 0.5 and 0.7 in
  the studies above. Gates that work combine signals the model cannot fake (agreement between independent calls, grounding,
  document evidence) and are calibrated on labelled in-domain data.

## 4. Verification styles and what each call buys

| Style | Extra calls per item | What the evidence says |
|---|---|---|
| Independent verifier on another model | 1 | Errors are correlated across models: "models agree 60% of the time when both models err", and "larger and more accurate models have highly correlated errors, even with distinct architectures and providers" ([Kim et al., ICML 2025](https://arxiv.org/abs/2506.07962)). Agreement is weaker evidence than it looks. |
| Verifier shown the draft | 1 | CoVe: verification "should not attend to the original baseline response as they may be prone to repeating it"; yes/no checks did worse, with the model tending "to agree with facts in a yes/no question format whether they are right or wrong" (PDF §4.3, [CoVe](https://arxiv.org/abs/2309.11495)). Assistants "consistently exhibit sycophancy" and favour responses that "match user beliefs over truthful ones" ([Sharma et al.](https://arxiv.org/abs/2310.13548)). |
| Blind re-extraction compared in code | 1 | This is CoVe's 2-step/factored idea at item level. Factored beat joint on all tasks (FActScore 60.8 → 63.7) and 2-step beat joint on both list tasks; factor+revise reached 71.4 against a 55.9 baseline; Wikidata list precision rose from 0.17 to 0.36. Factored CoVe needs "many more LLM prompts", one per verification question (PDF §3.3, §4.3). ExtractConf found disagreement between two differently-prompted calls "independently informative". |
| Self-consistency, n samples | n − 1 | Large gains on reasoning (GSM8K +17.9%) ([Wang et al., ICLR 2023](https://arxiv.org/abs/2203.11171)). Adaptive stopping cuts the sample budget "up to 7.9 times" with under 0.1% accuracy drop ([Adaptive-Consistency, EMNLP 2023](https://arxiv.org/abs/2305.11860)). As an extraction gate: 0.744 AUC at 5× cost ([ExtractConf](https://arxiv.org/abs/2606.24420)). |
| Self-correction, same model, no external signal | 1+ | "LLMs struggle to self-correct their responses without external feedback, and at times, their performance even degrades" ([Huang et al., ICLR 2024](https://arxiv.org/abs/2310.01798)). |
| LLM-as-judge / adjudicator | 1 | GPT-4 reaches "over 80% agreement" with humans, but with "position, verbosity, and self-enhancement biases" ([Zheng et al., NeurIPS 2023 D&B](https://arxiv.org/abs/2306.05685)). Self-preference: an evaluator "scores its own outputs higher than others'" ([Panickssery et al.](https://arxiv.org/abs/2404.13076)). A panel of smaller models from different families beat a single large judge at "over seven times less expensive" cost, though with more calls ([PoLL](https://arxiv.org/abs/2404.18796)). |
| Multi-step self-verification for extraction | 3+ | Omission, evidence and prune steps on clinical IE give an average F1 gain of 0.056. The omission step "increases recall but at the cost of decreased precision"; the prune step "removes extraneous elements, thereby increasing precision". Folding the steps into "a single large prompt" did "slightly worse" than the plain one-call baseline (PDF §3, [Gero et al.](https://arxiv.org/abs/2306.00024)). |

- **Anthropic's guidance favours grounding over re-asking.** "ask Claude to extract word-for-word quotes first", and
  "If it can't find a quote, it must retract the claim"; it lists best-of-N comparison as an advanced technique and
  warns the techniques "don't eliminate" hallucinations
  ([Reduce hallucinations](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations)).
- **What catches what, per call.** A string check on quotes catches fabricated evidence for zero calls. A blind second
  extraction catches value, unit and period slips that the two calls do not share, for one call, and misses shared
  errors. A judge shown both sides adds one call and brings judge biases with it. Sampling the same model n times costs
  n − 1 calls and, for extraction, gave a weak signal.

## 5. Deterministic checks that replace calls

- **Quote grounding in code.** Anthropic's Citations API returns citations that "are guaranteed to contain valid
  pointers to the provided documents" ([Citations](https://platform.claude.com/docs/en/build-with-claude/citations)).
  ChatReport made answers traceable to sources and pages; its human evaluation still found content hallucination-free
  in only 83.63% (ChatGPT) and 69.09% (GPT-4) of answers (PDF Table 1,
  [ChatReport](https://arxiv.org/abs/2307.15770)). A valid pointer shows where a claim came from; whether the claim
  matches the quote is a separate check.
- **SEC tagged facts.** The companyfacts API "returns all the company concepts data for a company into a single API
  call", covering "forms 10-Q, 10-K,8-K, 20-F, 40-F, 6-K, and their variants". The aggregated APIs include only facts
  that "Use a non-custom taxonomy (e.g. us-gaap, ifrs-full, dei, or srt)" and "Apply to the entire filing entity", so
  company extensions and segment-level (dimensional) facts are not there. Data updates in real time with a "typical
  processing delay of under a minute"; companyfacts.zip is "republished nightly"; no API key is needed
  ([EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)).
- **ESEF tagged facts.** The RTS "requires to mark up all numbers in a declared currency presented in the Primary
  Financial Statements", while the notes need only block tags; ESMA recommends "the lowest level of granularity for
  block tagging" be "individual tables contained within a single note", and detailed tagging of notes is optional
  (Guidance 1.9.2–1.9.3, [ESEF Reporting Manual, Oct 2025](https://www.esma.europa.eu/sites/default/files/library/esma32-60-254_esef_reporting_manual.pdf)).
  So numbers in the notes usually still need extraction, but a block tag can tell retrieval which table to read.
  xBRL-JSON is "a standardised JSON-based representation of data in an XBRL Report", each fact carrying concept,
  entity, period and unit dimensions plus `decimals`
  ([xBRL-JSON 1.0](https://www.xbrl.org/Specification/xbrl-json/REC-2021-10-13/xbrl-json-REC-2021-10-13.html)).
  The [filings.xbrl.org](https://filings.xbrl.org/) index listed 26,009 ESEF filings when fetched.
- **Sustainability statements are not yet tagged.** ESMA's December 2024 consultation proposes "a phased implementation
  over three phases, each lasting two years" for marking up sustainability statements, starting from the financial year
  set by the amending RTS's publication date (§3.3.3,
  [ESMA consultation paper](https://www.esma.europa.eu/sites/default/files/2024-12/ESMA32-2009130576-3024_CP_ESEF_RTS_-_marking_up_rules_for_sustainability_reports_and_financial_notes_and_EEAP_RTS_-_amendments.pdf)).
  Most ESG KPIs will need a model for some years. (Whether the amendment has since been adopted was not checked.)
- **Tagged facts still need checks.** XBRL US publishes data-quality rules because filed facts carry errors, e.g.
  DQC_0015 "Elements that should not be reported with negative values", DQC_0084 "Two-way elements tagged with the
  inappropriate sign", DQC_0004 "Assets equal liabilities plus shareholders' equity"
  ([DQC rules](https://xbrl.us/data-quality/rules-guidance/)).
- **Cross-footing with rounding tolerance.** Calculations 1.1 checks summation-item relationships with interval
  arithmetic driven by `decimals`: "The calculation is deemed to be consistent if CT overlaps with RT". It was written to
  fix "erroneous consistency failures on rounded values"
  ([Calculations 1.1](https://www.xbrl.org/Specification/calculation-1.1/REC-2023-02-22/calculation-1.1-REC-2023-02-22.html)).
  The ESEF manual: "XBRL calculations tell a user of tagged data how line items roll up to (sub)totals presented in the
  Primary Financial Statements". The same interval rule works for checking extracted totals against extracted parts.
- **Do arithmetic in code.** On FinQA the best model reached 61.24% execution accuracy against 91.16% for human experts
  (PDF Table 2, [FinQA, EMNLP 2021](https://arxiv.org/abs/2109.00122)). Derived values are cheaper and safer computed
  than asked for.
- **Prior-period comparison.** No primary source was found that measures prior-period checks on LLM extraction; the
  case for them rests on the rules above and on practice, not on a study.

## 6. Provider features that cut calls or cost

- **Message Batches.** "reducing costs by 50%"; up to "100,000 Message requests or 256 MB"; "most batches completing
  within 1 hour"; batches "expire if processing does not complete within 24 hours"; results available "for 29 days".
  Caching works inside batches on "a best-effort basis", with "cache hit rates ranging from 30% to 98%", and the page
  suggests "the 1-hour cache duration" for batches with shared context
  ([Batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing)).
- **Prompt caching.** 5-minute writes cost "1.25 times" base input, 1-hour writes "2 times", reads "0.1 times"; on
  Claude Opus 5.5 and Sonnet 5.5 cache hits are "0.05x the base input price". The minimum cacheable prefix is 512 tokens
  for Opus 5.5 and Sonnet 5.5 (1,024 for Sonnet 5); shorter prompts are "processed without caching and no error is
  returned". The prefix order is "`tools`, `system`, then `messages`"; up to 4 breakpoints; cache keys are "a
  cryptographic hash of the prompts up to the cache control point"
  ([Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)). Batch and cache discounts
  stack. Per MTok: Sonnet 5.5 $2 in / $10 out, Opus 5.5 $4 / $20, Haiku 5.5 $0.10 / $0.50 for prompts up to 100k
  tokens ([Pricing](https://platform.claude.com/docs/en/about-claude/pricing)).
- **Forced tool use is gone on the current models; strict mode replaces it.** On Opus 5.5 and Sonnet 5.5, `tool_choice`
  `any` and `tool` "return a 400 error"; the docs say to use "`auto` with strict tool use to guarantee schema-valid tool
  inputs, or structured outputs when you need a response in a fixed JSON shape"
  ([Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools#forcing-tool-use)).
  Strict mode guarantees that "Tool `input` strictly follows the `input_schema`"
  ([Strict tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use)); under `auto` that
  holds when the model calls the tool, not that it will. Structured outputs (`output_config.format`) promise "No retries
  needed for schema violations", with exceptions for refusals, `max_tokens` cut-offs and enum casing. Limits: 20 strict
  tools, 24 optional parameters and 16 union-typed parameters per request across all strict schemas; `minimum`/`maximum`
  are unsupported, and the SDK helpers move them into the description and validate them client-side
  ([Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)).
- **Format restrictions and reasoning.** Tam et al. report "a significant decline in LLMs reasoning abilities under
  format restrictions", and "stricter format constraints generally lead to greater performance degradation in reasoning
  tasks" ([Let Me Speak Freely?](https://arxiv.org/abs/2408.02442)). Extraction is mostly copying, not multi-step
  reasoning, but this is a reason to compare on the golden set before switching.
- **Citations API.** Besides valid pointers, "`cited_text` does not count toward your output tokens", and Anthropic
  reports it "significantly more likely to cite the most relevant quotes" than prompt-based citing. But "Citations
  cannot be used together with structured outputs" (a 400 error)
  ([Citations](https://platform.claude.com/docs/en/build-with-claude/citations)).
- **Response caching on disk.** The provider cache is ephemeral (5 minutes or 1 hour), so it does not replace an
  application cache keyed on inputs across runs. The primary sources add nothing beyond that.

## 7. Domain systems: how they structure calls

- **ChatReport (TCFD).** Reports are cut into 500-character chunks; "We usually retrieve the top 20 related chunks";
  one summarisation prompt and one conformity-scoring prompt per TCFD recommendation; question-answering prompts beat
  summarisation prompts; source numbers on chunks make answers traceable. No separate verifier call. Content
  hallucination-free rate: 83.63% with ChatGPT, 69.09% with GPT-4 (PDF §3, Table 1,
  [ChatReport](https://arxiv.org/abs/2307.15770)).
- **ESGReveal (ESG KPIs).** One retrieval (vector search plus reranking) and one prompt per indicator returning a
  structured tuple. The ablation shows where accuracy came from: better preprocessing and retrieval raised GPT-4 data
  extraction from 52.2% to 74.0% (+21.8 points); adding ESG domain knowledge to the prompt added 2.9 more (PDF §5.1.3,
  [ESGReveal](https://arxiv.org/abs/2312.17264)).
- **FinanceBench (10-K QA).** GPT-4-Turbo with retrieval "incorrectly answered or refused to answer 81% of questions"
  ([abstract](https://arxiv.org/abs/2311.11944)). In the body, success ranged from 19% (one shared vector store) to 50%
  (one store per document), 79% (GPT-4-Turbo, long context), 76% (Claude 2, long context) and 85% (oracle evidence
  pages). Long-context runs failed mostly by answering wrongly (17% and 21%) rather than refusing (PDF §5).
- **DocFinQA.** Average context grows "from under 700 words in FinQA to 123k words"; both retrieval and long-context
  systems find it hard, most of all on the longest documents ([DocFinQA](https://arxiv.org/abs/2401.06915)).
- **Retrieval benchmarks for climate disclosures.** ClimRetrieve (30 reports, 16 questions, "over 8.5K unique
  question-source-answer pairs") finds "incorporating expert knowledge works" for retrieval and warns of "critical
  limitations of embeddings" in this domain ([ClimRetrieve](https://arxiv.org/abs/2406.09818)). Anthropic's Contextual
  Retrieval cut top-20 retrieval failures by 49% (contextual embeddings plus BM25) and 67% (with reranking), found top-20
  chunks better than top-10 or top-5, and costs "$1.02 per million document tokens" with caching, i.e. one extra call per
  chunk at ingest ([Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval)).
- **Small domain models as zero-LLM filters.** ClimateBERT, pretrained "on over 2 million paragraphs of climate-related
  texts", lowers error rates on climate classification tasks by 3.57% to 35.71%
  ([ClimateBert](https://arxiv.org/abs/2110.12010)). A classifier like this can screen passages without an LLM call.
- **Glitter or Gold?** Uses LLMs with in-context learning and RAG to pull structured ESG insights from sustainability
  reports; the abstract gives no accuracy figures ([Bronzini et al.](https://arxiv.org/abs/2310.05628)).

---

## What this means for this pipeline

Today a company × field costs 0 calls when the XBRL path, a rule-based skip, a derived rule, input-hash reuse, the disk
cache or empty evidence settles it, and otherwise 2 + d, where d is the share of fields whose verifier disagrees (the adjudicator call). The list below is ranked by
calls saved at an acceptable precision risk, safest first. A change with a larger saving sits lower when its precision
risk is unmeasured, in line with `docs/METHODOLOGY.md` ("precision, even at the cost of extra LLM calls").

Most changes need numbers the repo can already produce: d from the run's usages, retries from `LLMUsage.attempts`, and
per-check catch rates from the golden set and known-answer items. The bundled extraction golden set has 5 cases
(`backend/arp/golden_set/data/extraction_cases.json`); the gates in item 5 need hundreds of labelled cases (Trust or
Escalate calibrated on 500, RouteLLM needed about 1,500 in-domain labels), so they depend on the set grown from
reviewer corrections.

1. **Skip the adjudicator on high-risk fields.**
   *Saves:* 1 call per high-risk disagreement (d on high-risk fields). Every field of the EU Taxonomy preset is
   high-risk (38 per company in `backend/arp/presets/eu_taxonomy.py`), so the cut applies to that whole schema.
   *Precision risk:* none on auto-accepted output. `aggregator.py` sets `auto_accept = not field.high_risk and …`
   (line 184), so a high-risk disagreement goes to review whether or not the adjudicator settles it; the call only
   produces a suggested value for the reviewer.
   *Evidence:* the adjudicator runs on the verifier's model and rules on a dispute where one side is that model's
   output, which is the setting where self-preference ([Panickssery et al.](https://arxiv.org/abs/2404.13076)) and
   judge biases ([Zheng et al.](https://arxiv.org/abs/2306.05685)) apply. Before cutting it, measure how often reviewers
   keep the adjudicator's value; if they often do, the call saves reviewer time and the trade is call vs reviewer
   minutes.
   *File:* `backend/arp/extraction/field_graph.py` (`_route_after_verify`).

2. **Put more financial fields on the 0-call tagged path.**
   *Saves:* 2 + d calls per company × field that gains `xbrl_tags`.
   *Precision risk:* low for primary-statement items, provided the existing checks keep running on tagged values and a
   sign check and a balance identity in the style of DQC_0015/0084/0004 are added
   ([DQC rules](https://xbrl.us/data-quality/rules-guidance/)).
   *Limits:* SEC aggregated facts exclude custom and dimensional (segment) facts
   ([EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)); ESEF notes are
   block-tagged, not detail-tagged ([ESEF manual](https://www.esma.europa.eu/sites/default/files/library/esma32-60-254_esef_reporting_manual.pdf));
   sustainability tagging is only proposed ([ESMA CP](https://www.esma.europa.eu/sites/default/files/2024-12/ESMA32-2009130576-3024_CP_ESEF_RTS_-_marking_up_rules_for_sustainability_reports_and_financial_notes_and_EEAP_RTS_-_amendments.pdf)).
   So this helps financial fields and few ESG fields. The partial-period variant noted in `_try_tagged` would not cut
   calls, since the model still runs for the missing periods.
   No field definition in `backend/arp/presets/` sets `xbrl_tags` today, so the tagged path only fires for user
   schemas that set it. The preset candidates are few: most preset fields are EU Taxonomy, green-share, remuneration
   and transition-plan KPIs that no filing tags yet. The likeliest are the EU Taxonomy denominators
   (`eut_*_total_amount`); whether each equals a tagged us-gaap / ifrs-full total has to be checked field by field.
   *Files:* the presets in `backend/arp/presets/` (`FieldDefinition.xbrl_tags`),
   `backend/arp/extraction/field_graph.py` (`_try_tagged`), `backend/arp/checks/plausibility.py`.

3. **Group fields that share a table into one extractor call and one blind-verifier call.**
   *Saves:* about 2(1 − 1/k) calls per field for a group of k fields (k = 3: 1.33 of ~2 calls per field), with
   adjudication still per field.
   *Precision risk:* medium and unmeasured. Joint prompts matched or beat per-field prompts on receipts and forms, most
   on numerically confusable fields ([Joint Extraction Matters](https://arxiv.org/abs/2503.16868)), and multi-task calls
   did better on MTI Bench ([Son et al.](https://arxiv.org/abs/2402.11597)). Accuracy drops with long batched contexts,
   item position and instruction density ([BatchPrompt](https://arxiv.org/abs/2309.00384),
   [IFScale](https://arxiv.org/abs/2507.11538), [Lost in the Middle](https://arxiv.org/abs/2307.03172)), and none of
   these used long reports with per-field retrieval.
   *Example in this repo:* the EU Taxonomy preset asks 12 fields per KPI (turnover, CapEx, OpEx), all read from the
   same Article 8 KPI table, and already ties them with cross-field checks (`sum_of` with target 100, `part_of`,
   `le_of`). Today that is 36 × (2 + d) calls per company. Split into two groups of 6 per KPI (the headline shares,
   enabling, transitional and total; the six objective shares), it would be 12 calls plus per-field adjudication.
   These are the numerically dependent fields where joint prompts helped most, and the sum and part-of checks give an
   independent test of the grouped answer.
   *How to keep the risk down:* group only fields from the same table or note, keep k ≤ 6 (the largest tested), bound
   the merged evidence, and keep grounding, checks and the blind comparison per field in code. Run the grouped and per-field graphs side by side on the golden set before switching.
   `financials_graph.py` and `tnfd_graph.py` already follow this one-extract, one-verify shape.
   *Files:* a group key on the field definition, `backend/arp/extraction/extractor_agent.py` (multi-field draft),
   `backend/arp/extraction/verifier_agent.py` (`compare` per field), `backend/arp/extraction/field_graph.py`.

4. **Use structured outputs or strict tool use to remove validation retries.**
   *Saves:* exactly the current retry rate, which `LLMUsage.attempts` records; probably small.
   *Precision risk:* low. The calls already return JSON through a tool, so this does not add a format restriction,
   though constrained decoding is stricter than prompting ([Tam et al.](https://arxiv.org/abs/2408.02442)).
   *Evidence and limits:* structured outputs guarantee the response shape and say "No retries needed for schema
   violations"; strict mode under `tool_choice: auto` guarantees inputs only when the tool is called. The schema limits
   (24 optional and 16 union-typed parameters per request) may block a grouped schema that repeats `PeriodValue`
   (`value: str | float | bool | None`) per field, and `ge`/`le` bounds move to client-side validation
   ([Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)). The comment in
   `langchain_client.py` rules out `strict: True` because every nested object would need `additionalProperties: false`;
   the docs say the SDK helpers' schema transformation adds it "to all objects" and expose it in Python as
   `transform_schema()` (same page), so what remains is whether the measured retry rate is worth the change.
   *File:* `backend/arp/llm/langchain_client.py`.

5. **Skip the verifier on low-risk fields when cheap signals are clean, calibrated on labels.**
   *Saves:* up to 1 call per low-risk company × field that passes the gate.
   *Precision risk:* the highest on this list until measured. Gate on signals the model cannot fake: grounded quote,
   `number_in_span`, `caption_scale`, `row_label`, period and entity checks, prior-period jump, cross-source agreement.
   Never gate on the extractor's stated confidence (AUROC 0.52 to 0.69 in [Xiong et al.](https://arxiv.org/abs/2306.13063)
   and [ExtractConf](https://arxiv.org/abs/2606.24420)). Cascades that save roughly 50 to 98% gate on something learned from task data or on agreement
   between samples ([FrugalGPT](https://arxiv.org/abs/2305.05176), [RouteLLM](https://arxiv.org/abs/2406.18665),
   [MoT](https://arxiv.org/abs/2310.03094)); conformal risk control can set the threshold with a stated error bound
   ([Angelopoulos et al.](https://arxiv.org/abs/2208.02814), [Trust or Escalate](https://arxiv.org/abs/2407.18370)).
   Do this per field class, and only where the golden set shows the verifier catches nothing the checks miss.
   *Files:* `backend/arp/extraction/field_graph.py` (a route between `extract` and `verify`),
   `backend/arp/extraction/routing.py`.

6. **Make every verifier blind (call-neutral, precision-positive).**
   *Saves:* 0 calls; may add adjudicator calls if blind runs disagree more often.
   *Evidence:* non-high-risk fields use `verify_extraction`, which shows the draft and the "Extractor's stated
   confidence" (`verifier_agent.py` line 80). CoVe found draft-conditioned verification repeats errors and yes/no checks
   agree "whether they are right or wrong" ([CoVe](https://arxiv.org/abs/2309.11495)); assistants are sycophantic toward
   a stated answer ([Sharma et al.](https://arxiv.org/abs/2310.13548)). A blind pass also returns the extractor's schema,
   which item 3 needs. Correlated errors ([Kim et al.](https://arxiv.org/abs/2506.07962)) mean blind agreement is still
   not proof, so grounding and checks stay.
   *File:* `backend/arp/extraction/field_graph.py` (`_verify`).

7. **Use the 1-hour cache TTL in batch runs (cost only).**
   *Saves:* 0 calls; cuts input cost when cache hits rise from the 5-minute TTL's level.
   *Evidence:* the batch docs suggest it and report 30 to 98% hit rates
   ([Batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing)). The gain is limited
   here: the shared prefix is the tool schema plus a system prompt of about 380 tokens, while the evidence (12 chunks)
   differs per field, and a 1-hour write costs 2× base input.
   *File:* `backend/arp/llm/langchain_client.py` (`_CACHE_CONTROL`).

**Not recommended here, on this evidence:**

- *Self-consistency or best-of-N sampling:* n − 1 extra calls and a weak extraction signal (0.744 AUC at 5× cost,
  [ExtractConf](https://arxiv.org/abs/2606.24420)).
- *Factored CoVe or a judge panel:* more calls per item ([CoVe](https://arxiv.org/abs/2309.11495),
  [PoLL](https://arxiv.org/abs/2404.18796)); the blind re-extraction already gets CoVe's main benefit for one call.
- *A cheap-model-first extractor:* cuts cost, not calls, and the ESG capability gap
  ([ESGReveal](https://arxiv.org/abs/2312.17264)) suggests frequent escalation, each adding a call.
- *Gating on self-reported confidence:* see section 3. The existing `below_auto_accept_min` and `LOW_CONFIDENCE`
  reasons only add review, so they are harmless for precision; they should not be used to skip a call.
- *Whole-report long-context prompts* in place of retrieval: FinanceBench's long-context runs beat its retrieval runs
  (79% vs 50%), and with cache reads at 0.05× they are affordable, but long-context errors were mostly confident wrong
  answers and position effects are documented ([FinanceBench](https://arxiv.org/abs/2311.11944),
  [Lost in the Middle](https://arxiv.org/abs/2307.03172)). Worth a golden-set experiment, not a default.

Where the evidence is thin: no source tests grouped vs per-field extraction on long financial or sustainability
reports, the only extraction-specific calibration study is a single-author workshop paper on invoices, and the
cascade savings come from QA, classification and chat benchmarks. The repo's golden set is the only way to turn
items 3 and 5 from plausible into measured.

---

## Sources that could not be fetched

- https://www.nature.com/articles/s41586-024-07421-0 (Farquhar et al., semantic entropy, Nature 2024): redirected to a
  login page. The ICLR 2023 arXiv paper by the same group is cited instead.
- https://eur-lex.europa.eu/eli/reg_del/2019/815/oj and the CELEX HTML version (Delegated Regulation (EU) 2019/815,
  the ESEF RTS): empty responses. ESEF obligations are cited from ESMA's Reporting Manual, which quotes the RTS.
- https://www.esma.europa.eu/issuer-disclosure/electronic-reporting: timed out.
- https://openai.com/index/introducing-structured-outputs-in-the-api/: HTTP 403. Not cited; Anthropic's structured
  outputs docs are used.
- https://filings.xbrl.org/about: HTTP 404. Whether filings.xbrl.org offers an API or xBRL-JSON downloads was not
  confirmed.
- https://arxiv.org/abs/2303.08774 (GPT-4 Technical Report): only the abstract was read, and it says nothing on
  calibration, so the report's calibration findings are not cited.
