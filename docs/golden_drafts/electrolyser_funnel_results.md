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

---

# Rerun on full annual reports, with an operator test (2026-11-01)

Changes from run 1: one full document per company (FY2025 annual report or URD as PDF; 10-K / 20-F / 40-F for
US filers; McPhy's 2023 URD, its last), 467–2,491 passages each. Step 2 reranks the 25 most similar passages,
step 3 runs on the best 6. New second hypothesis: "This company buys or operates electrolysers made by another
company". Found = cross-encoder > 1.5 **and** "makes" > 0.8 **and** "makes" beats "operates" on the same passage.
Green Hydrogen Systems is out (no report published). About 60 min on CPU.

| Company | Label | Sim | Cross-enc. | Makes | Operates | Found |
|---|---|---|---|---|---|---|
| Nel ASA | core | 0.71 | 6.45 | 1.00 | 0.00 | ✅ |
| ITM Power | core | 0.65 | 4.97 | 0.99 | 0.00 | ✅ |
| thyssenkrupp nucera | core | 0.71 | 4.45 | 0.99 | 0.00 | ✅ |
| HydrogenPro | core | 0.75 | 5.34 | 0.99 | 0.00 | ✅ |
| Enapter | core | 0.68 | 7.75 | 1.00 | 0.01 | ✅ |
| Plug Power | core | 0.77 | 6.49 | 0.98 | 0.00 | ✅ |
| McPhy Energy | core (historic) | 0.76 | 5.02 | 1.00 | 0.00 | ✅ |
| Siemens Energy | peripheral | 0.56 | −0.12 | 0.94 | 0.02 | ❌ |
| LONGi Green Energy | peripheral | 0.73 | 3.70 | 0.98 | 0.01 | ✅ |
| Sungrow Power | peripheral | 0.77 | 3.79 | 0.99 | 0.02 | ✅ |
| Bloom Energy | peripheral | 0.69 | 3.77 | 0.99 | 0.03 | ✅ |
| Ceres Power | peripheral | 0.66 | 3.22 | 0.94 | 0.01 | ✅ |
| GTT (Elogen) | peripheral | 0.68 | 5.25 | 1.00 | 0.00 | ✅ |
| Cummins (Accelera) | not (exited) | 0.62 | −0.20 | 1.00 | 0.01 | ✅ rejected |
| **Johnson Matthey** | not | 0.76 | 2.86 | 0.98 | 0.01 | ❌ false positive |
| Burckhardt Compression | not | 0.61 | −1.59 | 0.63 | 0.21 | ✅ rejected |
| Hexagon Purus | not | 0.65 | −2.76 | 0.17 | 0.04 | ✅ rejected |
| Linde | not | 0.60 | −0.91 | 0.04 | 0.01 | ✅ rejected |
| **Air Liquide** | not | 0.80 | 4.20 | 0.95 | 0.02 | ❌ false positive |
| Air Products | not | 0.71 | −1.10 | 0.42 | 0.10 | ✅ rejected |
| RWE | not | 0.60 | −0.59 | 0.12 | 0.05 | ✅ rejected |
| Shell | not | 0.69 | 1.49 | 0.97 | **0.94** | ✅ rejected |
| Ballard Power | not | 0.62 | −0.34 | 0.98 | 0.01 | ✅ rejected |
| Daimler Truck | not | 0.60 | −5.32 | 0.28 | 0.04 | ✅ rejected |
| Heidelberg Materials | not | 0.50 | −6.13 | 0.05 | 0.00 | ✅ rejected |
| Martin Marietta | not | 0.44 | −7.38 | 0.00 | 0.01 | ✅ rejected |

**Summary:** core 7/7 found (run 1: 6/6), peripheral **5/6** found (run 1: 0/6), not 11/13 rejected (run 1: 12/13).

## What changed and why

1. **Full reports fix the peripheral misses.** LONGi ("our alkaline water electrolysis system for hydrogen
   production supports Central Asia's first … green-ammonia project"), Sungrow, Bloom, Ceres and GTT are now
   found from their own reports. Siemens Energy is still missed: its best passage is a generic segment list,
   because the electrolyser business sits inside a larger segment and is barely described.
2. **The operator test works where the text says "operates".** Shell scores 0.97 on "makes" but 0.94 on
   "operates" for its REFHYNE II electrolyser passage, so it is rejected. Without the test it would be a false
   positive.
3. **New false positives come from suppliers and competitor lists.** Johnson Matthey: "Electrolyser sales doubled
   … driven by higher catalyst sales", a component supplier whose own words say "electrolyser sales". Air Liquide:
   a passage listing hydrogen-technology competitors. A third hypothesis ("supplies components for
   electrolysers") and the LLM debate (step 6) are the fix; revenue sizing then shows these are small.
4. **Ceres is now found.** Its report describes its electrolyser technology at length; the licensing nuance only
   shows in other passages. The label "peripheral (licensor)" stays a judgement call for the debate.
5. **Cost of full documents:** about 2 minutes per report on CPU (passage embedding dominates). On the L4 GPU,
   or with a section filter (business review, segments) instead of the whole report, this drops to seconds.

## Next steps (updated)

1. Add the supplier hypothesis; re-run.
2. Restrict passages to business-description and segment sections to cut noise and run time.
3. Grow the set to about 60 companies with a held-out half before fixing thresholds.
