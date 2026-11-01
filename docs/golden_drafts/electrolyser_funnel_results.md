# Funnel test: electrolyser manufacturers (2026-11-01)

First run of funnel steps 1–3 from `docs/COMPANY_EXPOSURE_MODEL_FUNNEL.md` on the golden-set draft
`electrolyser_manufacturers.md`. CPU only, about 3 minutes for 25 companies.

## Setup

| Item | Value |
|---|---|
| Activity | "Manufactures and sells electrolysers or electrolyser stacks for producing hydrogen from water" |
| Step 1 | Embeddings `paraphrase-multilingual-MiniLM-L12-v2` (the repo's model); passages of 3 sentences; max cosine similarity |
| Step 2 | Cross-encoder `cross-encoder/ms-marco-MiniLM-L6-v2` on the 8 most similar passages; max score |
| Step 3 | Zero-shot NLI `MoritzLaurer/deberta-v3-base-zeroshot-v2.0`, hypothesis "This company manufactures and sells electrolysers.", on the 3 best reranked passages; max entailment probability |
| Text per company | US filers (8): first ~1,200 words of 10-K Item 1 / 20-F Item 4 / 40-F annual information form. Others (17): the company's own "about" web page, 115–2,400 words |
| Missing | McPhy Energy and Green Hydrogen Systems (archived pages not reachable from the container); Chart Industries removed (acquired) |

Script: kept in the session scratchpad, not committed (exploration only).

## Results

| Company | Label | Sim (1) | Cross-enc. (2) | NLI (3) | Funnel verdict* |
|---|---|---|---|---|---|
| Nel ASA | core | 0.66 | 5.14 | 1.00 | ✅ found |
| ITM Power | core | 0.61 | 4.74 | 1.00 | ✅ found |
| thyssenkrupp nucera | core | 0.63 | 1.99 | 0.97 | ✅ found |
| HydrogenPro | core | 0.69 | 2.89 | 1.00 | ✅ found |
| Enapter | core | 0.63 | 2.66 | 0.87 | ✅ found |
| Plug Power | core | 0.71 | 4.47 | 0.99 | ✅ found |
| Siemens Energy | peripheral | 0.32 | −9.17 | 0.83 | ❌ missed |
| LONGi Green Energy | peripheral | 0.37 | −9.60 | 0.04 | ❌ missed |
| Sungrow Power | peripheral | 0.32 | −7.85 | 0.03 | ❌ missed |
| Bloom Energy | peripheral | 0.35 | 0.20 | 0.85 | ❌ missed (borderline) |
| Ceres Power | peripheral | 0.62 | 1.89 | 0.02 | ❌ missed (licenses, does not make) |
| GTT (Elogen) | peripheral | 0.31 | −8.27 | 0.00 | ❌ missed |
| Cummins (Accelera) | not (exited) | 0.41 | −6.40 | 0.04 | ✅ rejected |
| Johnson Matthey | not | 0.29 | −9.00 | 0.00 | ✅ rejected |
| Burckhardt Compression | not | 0.46 | −5.98 | 0.01 | ✅ rejected |
| Hexagon Purus | not | 0.47 | −5.11 | 0.04 | ✅ rejected |
| Linde | not | 0.60 | −0.91 | 0.03 | ✅ rejected |
| **Air Liquide** | not | 0.73 | 2.32 | 0.99 | ❌ **false positive** |
| Air Products | not | 0.65 | −2.58 | 0.86 | ✅ rejected (by step 2) |
| RWE | not | 0.47 | −2.90 | 0.13 | ✅ rejected |
| Shell | not | 0.26 | −7.83 | 0.02 | ✅ rejected |
| Ballard Power | not | 0.47 | −5.53 | 0.92 | ✅ rejected (by step 2) |
| Daimler Truck | not | 0.28 | −10.02 | 0.00 | ✅ rejected |
| Heidelberg Materials | not | 0.38 | −8.57 | 0.00 | ✅ rejected |
| Martin Marietta | not | 0.43 | −7.38 | 0.00 | ✅ rejected |

\* Verdict rule chosen after looking at the scores (so optimistic): cross-encoder > 1.5 **and** NLI > 0.8.

**Summary:** core 6/6 found; not 12/13 rejected (1 false positive); peripheral 0/6 found.

## What the misses show

1. **Peripheral companies are missed because of the text, not the models.** The group "about" pages of Siemens
   Energy, LONGi, Sungrow and GTT do not mention electrolysers at all (LONGi's best passage is about silicon
   crystal growth). A one-page group description cannot reveal a small subsidiary. Fix: use segment notes,
   subsidiary pages and press releases as passages; this is the "relevant ≠ material" limit seen from the other
   side.
2. **Operator vs maker (Air Liquide).** "Air Liquide inaugurated the world's largest PEM electrolyzer" passes both
   the cross-encoder and NLI: the models read "operates an electrolyser" as "makes one". Fix: a second NLI
   hypothesis ("The company buys or operates electrolysers made by others") and keep only companies where
   "manufactures" beats "operates"; or leave it to the LLM debate (step 6).
3. **NLI alone is noisy; the cross-encoder filters it.** NLI gave 0.92 to Ballard (a fuel-cell JV passage), 0.86
   to Air Products and 0.83 to Siemens Energy on a careers sentence. The cross-encoder scored all three negative.
   Using both steps together is what made the result clean.
4. **Licensing is caught.** Ceres Power scores high on similarity and the cross-encoder, but NLI says no
   (0.02): its text says it *licenses* the technology. That matches the hard-case label, and is the kind of
   distinction the funnel should make.
5. **Step 1 (embeddings) alone separates poorly.** Core companies score 0.61–0.71, but so do Air Liquide (0.73),
   Air Products (0.65) and Linde (0.60). As intended, step 1 is only a recall filter: a cut at 0.55 keeps all six
   core companies and drops 16 of 19 others.

## Limits of this test

- 25 companies, one text each, thresholds set after seeing the scores. Indicative only, not a measured
  precision or recall.
- Mixed sources: 10-K text for US filers and marketing pages for the others, so source and label are partly
  confounded.
- English models only for steps 2–3; all texts happened to be English.
- The labels were checked by web research on 2026-11-01 (see `electrolyser_manufacturers.md`); several "ok"
  verdicts rest on older sources.

## Next steps

1. Replace the about pages with annual-report "business" and segment sections for all companies (fixes
   finding 1, and makes sources comparable).
2. Add the second NLI hypothesis for operators (finding 2).
3. Grow the set to about 60 companies, including private makers if relevant, and fix thresholds on a held-out half.
