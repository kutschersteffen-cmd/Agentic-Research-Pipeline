# Model stack: published benchmarks and gaps

Research date: 2026-11-02. Scope: the 9 entries in `backend/arp/models/registry.json`.
Numbers are quoted as the source states them. Tags: **[primary]** = model card or paper read directly;
**[secondary]** = search-engine summary or third-party listing; **[memory]** = not re-checked in this session.

## Summary

| Model (registry key) | Task | Best published metric | Dataset | Source | Licence |
|---|---|---|---|---|---|
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (embed) | Dense embedding, 384-d, max 128 tokens | nDCG@10 **32.45** (MTEB retrieval avg, original English MTEB) [secondary] | MTEB retrieval | https://stat.paperswithcode.com/paper/mteb-massive-text-embedding-benchmark | Apache-2.0 |
| `BAAI/bge-reranker-v2-m3-int8` (rerank; fastembed int8 build of `BAAI/bge-reranker-v2-m3`) | Cross-encoder rerank | No numbers in card text (charts only). First-stage bge-m3 "All": MIRACL nDCG@10 **71.5** | MIRACL dev | https://huggingface.co/BAAI/bge-reranker-v2-m3 , https://arxiv.org/abs/2402.03216 | Apache-2.0 |
| `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` (nli) | NLI / zero-shot classify | XNLI test acc **0.871** (en), 0.824 (de), 0.744 (ur, lowest) | XNLI | https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7 | MIT |
| `urchade/gliner_multi-v2.1` (gliner) | Zero-shot NER spans | Paper: GLiNER-Multi MultiCoNER zero-shot avg F1 **32.9** (en 41.7, de 39.5); GLiNER-L CrossNER+MIT avg **60.9** (English model) | MultiCoNER; CrossNER+MIT | https://arxiv.org/html/2311.08526v1 | Apache-2.0 (training data `pile-mistral-v0.1`, check its terms) |
| `climatebert/distilroberta-base-climate-detector` | Paragraph: climate yes/no | **None reported** on card | climatebert/climate_detection (1,300 train / 400 test) | https://huggingface.co/climatebert/distilroberta-base-climate-detector | Model Apache-2.0; dataset CC BY-NC-SA 4.0 |
| `climatebert/distilroberta-base-climate-commitment` | Paragraph: commitment/action yes/no | **None found** (card lists accuracy as metric, no value) [secondary] | climatebert/climate_commitments_actions | https://huggingface.co/climatebert/distilroberta-base-climate-commitment | Apache-2.0 (dataset NC, see below) |
| `climatebert/distilroberta-base-climate-specificity` | Paragraph: specific/non-specific | **None found** | climatebert/climate_specificity | https://huggingface.co/climatebert/distilroberta-base-climate-specificity | Apache-2.0 (dataset NC, see below) |
| `yiyanghkust/finbert-fls` | Sentence: Specific-FLS / Non-specific FLS / Not-FLS | **None on card**; paper tables not reached | 3,500 MD&A sentences, Russell 3000 | https://huggingface.co/yiyanghkust/finbert-fls | Not stated on card; GitHub repo Apache-2.0 |
| `yiyanghkust/finbert-esg-9-categories` | Sentence: 9 ESG topics + non-ESG | **None on card** (links a PDF with results) | ~14,000 sentences from ESG + annual reports | https://huggingface.co/yiyanghkust/finbert-esg-9-categories | Not stated on card; GitHub repo Apache-2.0 |

Bottom line: only the NLI model has a clean, per-language published score on its card. Four of the five
`tag` classifiers ship with no reported metric at all, so ARP's own golden sets are the only evidence for them.

## 1. paraphrase-multilingual-MiniLM-L12-v2 (embed)

- **Card** [primary]: 384-d vectors, `max_seq_length: 128`, 50 languages, Apache-2.0. No benchmark numbers on the card.
- **Paper** [primary]: Reimers & Gurevych, "Making Monolingual Sentence Embeddings Multilingual using Knowledge Distillation", EMNLP 2020, https://arxiv.org/abs/2004.09813. Teacher–student distillation on parallel data, "50+ languages". The card itself cites Sentence-BERT (EMNLP 2019, arXiv:1908.10084).
- **MTEB** [secondary]: retrieval nDCG@10 **32.45** for "MiniLM-L12-multilingual" vs **42.69** for English MiniLM-L12 (original MTEB leaderboard via Papers with Code / HyperAI). This is English retrieval tasks only. MMTEB (https://arxiv.org/html/2502.13595v4) uses MiniLM-L12 as a reference model; I did not extract a per-task figure. STS figure: **Not confirmed** (the mteb/results file fetch 404'd).
- **Versus bge-m3 / mE5** [primary for those models]: bge-m3 paper Table 1, MIRACL nDCG@10 avg: M3 Dense **69.2**, M3 All **71.5**, mE5-large **66.6**; MKQA Recall@100: M3 Dense **75.1**, mE5-large **70.9**. MiniLM is not in that table. An independent cross-lingual fact-check retrieval study reports MiniLM-L12-v2 **0.3737** vs mE5-large **0.6324** vs bge-m3 **0.6754** (https://arxiv.org/pdf/2505.22118) [secondary, column labels not verified].
- **Caveats for ARP**: 128 tokens is roughly one paragraph; anything longer in a 10-K chunk is silently truncated. It is a paraphrase/STS model, not trained for asymmetric query→passage retrieval. The reranker partly compensates, but recall lost at stage one cannot be recovered.

## 2. bge-reranker-v2-m3 (int8, rerank)

- **Id note**: `BAAI/bge-reranker-v2-m3-int8` does not exist as a BAAI repo on the Hub (API returned 401). It is the name fastembed uses for its int8 ONNX export (`backend/arp/retrieval/rerank.py:18`; `docs/superpowers/plans/2026-10-13-retrieval-quality.md:39`). The cloud path uses full-precision `BAAI/bge-reranker-v2-m3` (`backend/arp/compute/client.py:32`). No published benchmark exists for the int8 build.
- **Card** [primary]: base model bge-m3, 0.6B params, Apache-2.0. Examples truncate at `max_length=512`. Evaluations (BEIR reranking top-100 of bge-en-v1.5/e5-mistral, CMTEB-retrieval, MIRACL reranking bge-m3 top-100, llama-index) are shown **only as images**, so no numbers are quoted here.
- **Papers**: BGE M3-Embedding (Chen et al. 2024, arXiv:2402.03216); "Making LLMs a better foundation for dense retrieval" (arXiv:2312.15503). No standalone reranker paper found.
- **Caveats**: int8 quantisation drift vs fp32 is unmeasured; 512-token window; general-domain training. Newer siblings on the card: `bge-reranker-v2-gemma`, `bge-reranker-v2-minicpm-layerwise` (larger, LLM-based).

## 3. mDeBERTa-v3-base-xnli-multilingual-nli-2mil7 (nli)

- **Card** [primary], XNLI test accuracy: ar 0.794, bg 0.822, de 0.824, el 0.809, en 0.871, es 0.832, fr 0.823, hi 0.769, ru 0.803, sw 0.746, th 0.786, tr 0.792, ur 0.744, vi 0.793, zh 0.803. bg/el/th were not in NLI training data (cross-lingual transfer).
- Training: multilingual-nli-26lang-2mil7 (2,730,000 pairs, 26 languages, **machine-translated** from MNLI, Fever-NLI, ANLI, LingNLI, WANLI) + XNLI validation; 3,287,280 pairs total. Card warns MT "reduces the quality", and that mDeBERTa "does not support FP16". MIT licence.
- **Papers** [primary]: Laurer, van Atteveldt, Casas, Welbers, "Less Annotating, More Classifying", *Political Analysis* 32(1):84–100 (2024), doi 10.1017/pan.2023.20: BERT-NLI with 100–2,500 texts is "on average 10.7 to 18.3 percentage points better" (F1 macro) than classical models; ~500 texts ≈ classical with ~5,000. "Building Efficient Universal Classifiers with Natural Language Inference" (arXiv:2312.17543): 33 datasets, 389 classes, zero-shot gain of "9.4%".
- **Caveats**: XNLI is short generic sentences, not disclosure language; zero-shot label quality depends heavily on hypothesis wording; max length not stated (DeBERTa-v3 tokenizer, typically 512 [memory]).

## 4. gliner_multi-v2.1 (spans)

- **Card** [primary]: Apache-2.0, multilingual, trained on `urchade/pile-mistral-v0.1`. Benchmarks shown only as an image.
- **Paper** [primary]: Zaratiana, Tomeh, Holat, Charnois, "GLiNER: Generalist Model for Named Entity Recognition using Bidirectional Transformer", NAACL 2024, pp. 5364–5376, doi 10.18653/v1/2024.naacl-long.300. Zero-shot avg F1 over 7 CrossNER+MIT sets: GLiNER-S 52.7, GLiNER-M 55.4, GLiNER-L **60.9**, ChatGPT 47.5, UniNER-7B 53.7, UniNER-13B 55.6. GLiNER-Multi on MultiCoNER (zero-shot): avg **32.9**; de 39.5, en 41.7, es 42.1, nl 38.9, ru 33.3, zh 24.3 — vs supervised XLM-R 54.9. Span length capped at K=12 tokens.
- **Caveats**: the paper evaluates v1 models; v2.1 numbers are not in text form. Multilingual zero-shot F1 ~33–42 is low; finance entity types (instruments, targets, facilities) are untested. Long monetary/target phrases can exceed the 12-token span cap.

## 5. ClimateBERT detector / commitment / specificity

- **Paper** [primary]: Webersinke, Kraus, Bingler, Leippold, "ClimateBert: A Pretrained Language Model for Climate-Related Text" (arXiv:2110.12010): "48% improvement on a masked language model objective", "lowering error rates by 3.57% to 35.71%" on downstream tasks. This is the base LM, not the three classifiers.
- **Classifier cards** [primary]: fine-tuned from `distilroberta-base-climate-f`; cite Bingler, Kraus, Leippold, Webersinke, "How Cheap Talk in Climate Disclosures Relates to Climate Initiatives, Corporate Emissions, and Reputation Risk" (2023, SSRN 3998435). **No accuracy/F1 on the cards.** Detector card: trained on paragraphs, "may not perform well on sentences".
- **Dataset** [primary]: climate_detection ≈1,700 paragraphs (1,300 train/400 test) "extracted from corporate annual reports and sustainability reports", mostly large listed firms; **CC BY-NC-SA 4.0**, commercial users asked to contact authors. The commitments and specificity datasets are presumably the same licence [memory, not checked].
- **Independent** [secondary]: a greenwashing study using the ClimateBERT family reports avg accuracy 86.34% / F1 0.67 on sustainability reports (arXiv:2311.01469) — different task, not comparable. ClimaBench: numbers **not retrieved**.
- **Caveats**: tiny test sets; paragraph-level only; DistilRoBERTa 512-token limit [memory]; English only; NC-licensed training data is a licence question for commercial ARP use.

## 6. FinBERT-FLS and FinBERT-ESG-9

- **Paper** [secondary for content]: Huang, Wang, Yang, "FinBERT: A Large Language Model for Extracting Information from Financial Text", *Contemporary Accounting Research* 40(2):806–841 (2023), doi 10.1111/1911-3846.12832. Claims FinBERT outperforms dictionary, ML and generic BERT baselines on sentiment and ESG. **FLS and ESG accuracy figures were not reachable** (paywalled; the 2020 arXiv precursor 2006.08097 covers sentiment only).
- **Cards** [primary]: FLS — 3,500 MD&A sentences from Russell 3000 annual reports, 3 labels. ESG-9 — ~14,000 sentences from ESG and annual reports, 9 topics + non-ESG; results in a linked PDF not read. No licence on either card; the GitHub repo (yya518/FinBERT) is Apache-2.0. Pretraining corpus: 10-K/10-Q 2.5B, earnings calls 1.3B, analyst reports 1.1B tokens.
- **Caveats**: closest domain match in the stack (US 10-K text), but English, sentence-level, US-only; ESG taxonomy is the authors' own and won't map 1:1 to ARP topics.

## Newer models of the same type (as of 2026)

All [memory/secondary] unless noted; verify on the MTEB leaderboard before switching.
- Embedding: `BAAI/bge-m3` (8192 tokens, MIRACL 69.2 dense [primary]), `intfloat/multilingual-e5-large(-instruct)`, `Qwen/Qwen3-Embedding-0.6B` — the latter two already ship in fastembed per the 2026-10-13 retrieval plan.
- Rerank: `jinaai/jina-reranker-v2-base-multilingual` (also in fastembed), bge-reranker-v2-gemma / minicpm-layerwise [primary, card].
- NLI/zero-shot: Laurer's later `deberta-v3-*-zeroshot-v2.0` family (2312.17543) is English-focused; multilingual successor not confirmed.
- NER: GLiNER v2.5 / multitask variants and "GLiNER2" [memory].
- ESG/climate: no clearly better open classifier found; LLM classification is the common alternative.

## Gaps: what is not benchmarked for our use case

1. No model is benchmarked on full annual reports / 10-K chunks of ARP's chunk length; only paragraphs (ClimateBERT) or sentences (FinBERT, XNLI).
2. Non-English annual reports (German, French) are untested for every `tag` model; all five are English-only.
3. Int8 reranker vs fp32: no published delta.
4. Embedder truncation at 128 tokens on ARP chunks: no published effect.
5. GLiNER on finance entity types (emission targets, capex amounts, years, facilities): untested.
6. Four `tag` models have no published test metric at all; calibration of their scores (ARP thresholds) is never reported.
7. Table text, footnotes, boilerplate and OCR noise from PDFs: no evaluation.

## Recommended own evaluations (map to ARP golden sets)

| Eval | Golden set | Measures |
|---|---|---|
| Retrieval recall@k / nDCG@10, MiniLM vs bge-m3 vs Qwen3-0.6B, with and without rerank | `backend/tests/golden/retrieval/` (cases.json, documents.json) | Stage-1 recall loss from 128-token truncation; reranker lift |
| Reranker int8 vs fp32 (cloud) agreement | same retrieval set | Ranking drift (Kendall tau, nDCG delta) |
| Climate detector/commitment/specificity, FLS, ESG precision/recall at ARP thresholds | `backend/arp/golden_set/data/extraction_cases.json`, `role_cases.json`; `backend/tests/golden/transition_barrier/` | Domain shift to 10-K/annual report text; sentence vs paragraph input |
| NLI zero-shot labels on German vs English text | add DE cases to extraction/role cases | Language gap (card shows en 0.871 vs de 0.824 on XNLI) |
| GLiNER span F1 on finance entity types | `transition_barrier` cases (targets, barriers) | Zero-shot entity quality, span-cap misses |

Each eval should record the registry `revision` so scores stay tied to the pinned snapshot.

## Not confirmed

- MTEB STS and MMTEB scores for paraphrase-multilingual-MiniLM-L12-v2 (only the 32.45 retrieval figure, from secondary listings).
- Any numeric BEIR / MIRACL / CMTEB result for bge-reranker-v2-m3 (card shows images only).
- GLiNER multi **v2.1** benchmark numbers (paper numbers are for v1 models).
- Accuracy/F1 of the three ClimateBERT classifiers in Bingler et al. 2023 (SSRN 3998435 not read).
- ClimaBench results.
- FinBERT-FLS and FinBERT-ESG-9 accuracy in Huang, Wang & Yang 2023 (paywalled; linked PDF not read).
- Licence of the climate_commitments_actions and climate_specificity datasets; licence of the two FinBERT model cards (none stated).
- Max sequence length of the NLI and ClimateBERT models (512 assumed from architecture).
- Successor-model claims in "Newer models" beyond what the cited cards state.
