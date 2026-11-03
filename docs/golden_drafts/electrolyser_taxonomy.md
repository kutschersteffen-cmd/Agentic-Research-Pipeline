# Electrolyser manufacturing taxonomy — v1 draft review

- **Taxonomy id:** `tax_9acd23322206` (v1 = `authority_source` extraction, v2 = after `map-standards`). Status: **draft, not ratified**.
- **Source:** Scottish Government, *Assessment of electrolysers: report*, section 2 "Supply Chain Structure" — <https://www.gov.scot/publications/assessment-electrolysers-report/pages/3/> (single source, HTML, ~30k chars; the PEM/ALK/SOE component tables and supply-chain tiers sit inside the first 20,000 chars).
- **Why not IEA / EU Taxonomy:** `discover-sources` returned 0 candidates (DuckDuckGo bot challenge on every query). IEA pages return HTTP 403 to the fetcher. The EU Taxonomy Navigator is a JS app (125 chars of text). EUR-Lex Annex I puts activity 3.2 far past 20,000 chars. Note: EU activity 3.10 is *manufacture of hydrogen* (production, out of scope); the electrolyser-equipment activity is 3.2.
- **Commands:** `arp taxonomy create "Electrolyser manufacturing" --method authority_source --authority-url <url> --description "<scope>"`, then `arp taxonomy map-standards tax_9acd23322206`.

## Review

| # | Activity | In scope (short) | Out of scope (short) | Source quote | Fits theme? |
|---|---|---|---|---|---|
| 1 | Raw and processed materials supply | Mining, materials processing, coating, chemicals, semiconductors supplying electrolyser inputs | Mining unrelated to electrolysers; finished components | Yes (exact) | **No** — upstream commodity suppliers, not electrolyser makers |
| 2 | Electrolyser stack component manufacture | Electrodes, membranes, separators, PTLs, bipolar plates, frames/seals (PEM, ALK); ceramic cells, interconnectors (SOE) | Balance-of-plant; installation | Yes (exact) | **Yes** — core |
| 3 | Balance-of-plant and auxiliary equipment | Rectifiers, compressors, chillers, pumps, vessels, dryers, water systems | Stack; integration/installation | Yes (exact) | **Borderline** — generic "off-the-shelf" equipment (per the source's own quote); pulls in generic compressor/pump makers |
| 4 | Electrolyser/fuel cell OEM manufacture and testing | OEMs supplying the full electrolyser package (PEM, ALK, SOE), incl. testing | Generic components; hydrogen end-use | Yes (exact) | **Yes, but name and quote include fuel cells** |
| 5 | System integration and installation | Integrators, control systems, pipework, cabling, EPC/commissioning | Component manufacture; O&M | Yes (exact) | **Borderline** — OEM-linked integrators fit; EPC/construction contractors do not |
| 6 | Operation and maintenance services | Operating and maintaining electrolyser facilities over ~25 years | Manufacture, installation, decommissioning | Yes (exact) | **No** — operating electrolysers is explicitly out of scope |
| 7 | End-of-life decommissioning and material recovery | Decommissioning, disposal, PGM recycling | Primary mining; general waste | Yes (exact) | **No** — not making or selling electrolysers |

**Citations:** all 7 activities carry a `source_citation` with `grounded: true`, `match_method: exact`, score 1.0 (single source, so `merge_activity_sets` did not rewrite them).

**Required exclusions in out-of-scope text:**

| Exclusion | Covered? |
|---|---|
| Operating electrolysers / producing hydrogen | No. Only #4 mentions "hydrogen end-use"; #6 makes operation an in-scope activity |
| Buying electrolysers | No activity excludes it |
| Generic industrial gases | No activity excludes it |
| Fuel cells | No. #4 includes "fuel cell" in its name and quote |

## Gaps to fix before ratifying

1. **Scope drift:** the source maps the whole supply chain, so 3 of 7 activities (#1, #6, #7) are outside "making and selling electrolysers" and 2 (#3, #5) are borderline. Drop #1, #6, #7; narrow #3 to electrolyser-specific BoP (or drop it); narrow #5 to OEM-linked system integration.
2. **AEM missing:** the source covers PEM, ALK and SOE only. No activity names AEM electrolysers.
3. **Exclusions missing:** add operators/hydrogen producers, electrolyser buyers, industrial gas companies and fuel cell makers to the out-of-scope text (at least on #2 and #4); rename #4 to "Electrolyser OEM manufacture and testing".
4. **No standards codes:** `core_isic_codes` is empty on every activity — the `authority_source` extraction does not populate them — so `map-standards` reported "Mapped 7/7" but saved empty NACE/NAICS/SIC/GICS lists. Codes must be added by hand (e.g. ISIC 2790 *other electrical equipment*, 2819 *other general-purpose machinery*) in a new version before the funnel uses them.
5. **v2 `derivation_method` reads `manual`:** `map-standards` relabelled the version; the authority_source provenance is only on v1 and in the citations.

## Full `arp taxonomy show tax_9acd23322206` output (v2)

```json
{
  "taxonomy_id": "tax_9acd23322206",
  "name": "Electrolyser manufacturing",
  "version": 2,
  "theme": {
    "theme_id": "theme_97c4c594bcf3",
    "name": "Electrolyser manufacturing",
    "description": "Companies that design, manufacture and sell water electrolysers (alkaline, PEM, solid-oxide and AEM), including electrolyser stacks and their core components (electrodes, membranes/diaphragms, porous transport layers, bipolar plates, frames and seals) and integrated electrolyser systems. Out of scope: operating electrolysers or producing/selling hydrogen, buying or deploying electrolysers as an end user, generic industrial gases, and fuel cells.",
    "activities": [
      {
        "activity_id": "act_92c7022955fb",
        "name": "Raw and processed materials supply (mining, materials processing, coating)",
        "in_scope_description": "Metal mining and processing, materials processing, metal coating, plastics manufacture and processing, chemical processing and semiconductors that supply materials (e.g. iridium, platinum, nickel, titanium, PFSA membranes, KOH) to electrolyser component manufacturers and OEMs.",
        "out_of_scope_description": "Mining or materials processing with no link to electrolyser inputs; manufacture of finished components or systems.",
        "seed_keywords": [
          "metal mining",
          "materials processing",
          "metal coating",
          "platinum",
          "iridium",
          "nickel",
          "chemical processing",
          "PFSA membrane"
        ],
        "core_isic_codes": [],
        "source_citation": {
          "doc_id": "doc_5660d4da4c3c",
          "doc_type": "other",
          "quote": "Metal mining and processing Materials processing Metal coating Plastics manufacture and processing Chemical processing Semiconductors",
          "location": "https://www.gov.scot/publications/assessment-electrolysers-report/pages/3/",
          "grounded": true,
          "page": null,
          "sheet": null,
          "company_id": "https://www.gov.scot/publications/assessment-electrolysers-report/pages/3/",
          "source_filename": null,
          "content_key": null,
          "span_text": "Metal mining and processing Materials processing Metal coating Plastics manufacture and processing Chemical processing Semiconductors",
          "char_start": 11269,
          "char_end": 11402,
          "match_method": "exact",
          "match_score": 1.0,
          "passage_id": null,
          "table_ref": null,
          "parser_version": null
        },
        "standards_mapping": {
          "nace_codes": [],
          "naics_codes": [],
          "sic_codes": [],
          "gics": [],
          "unmapped_isic_codes": []
        },
        "tier": "core",
        "lifecycle_stage": null,
        "criticality_flag": false,
        "human_approved": false
      },
      {
        "activity_id": "act_10ac31ce3bc4",
        "name": "Electrolyser stack component manufacture",
        "in_scope_description": "Manufacture of the stack's sub-components: anodes, cathodes, electrolyte/membranes, separators, porous transport layers, bipolar plates, frames and sealing (PEM, ALK) and ceramic cells, current collectors, interconnectors and gaskets (SOE). The specialist electrolyser OEM manufactures the stack itself.",
        "out_of_scope_description": "Balance-of-plant equipment such as pumps, compressors and piping; project installation.",
        "seed_keywords": [
          "electrolyser stack",
          "bipolar plate",
          "porous transport layer",
          "membrane",
          "anode",
          "cathode",
          "interconnector",
          "ceramic cell"
        ],
        "core_isic_codes": [],
        "source_citation": {
          "doc_id": "doc_5660d4da4c3c",
          "doc_type": "other",
          "quote": "Manufacture of the electrolyser stack itself would be carried out by the specialist electrolyser OEM",
          "location": "https://www.gov.scot/publications/assessment-electrolysers-report/pages/3/",
          "grounded": true,
          "page": null,
          "sheet": null,
          "company_id": "https://www.gov.scot/publications/assessment-electrolysers-report/pages/3/",
          "source_filename": null,
          "content_key": null,
          "span_text": "Manufacture of the electrolyser stack itself would be carried out by the specialist electrolyser OEM",
          "char_start": 16849,
          "char_end": 16949,
          "match_method": "exact",
          "match_score": 1.0,
          "passage_id": null,
          "table_ref": null,
          "parser_version": null
        },
        "standards_mapping": {
          "nace_codes": [],
          "naics_codes": [],
          "sic_codes": [],
          "gics": [],
          "unmapped_isic_codes": []
        },
        "tier": "core",
        "lifecycle_stage": null,
        "criticality_flag": false,
        "human_approved": false
      },
      {
        "activity_id": "act_1034c6c29df4",
        "name": "Balance-of-plant and auxiliary equipment manufacture",
        "in_scope_description": "Manufacture of the off-the-shelf and process equipment in an electrolyser package: water systems (de-ionised water units, feed water), rectifiers/transformers and electrical equipment, cooling equipment and chillers, compressors, heat exchangers, pumps, separation vessels, de-oxo dryer units and hotboxes.",
        "out_of_scope_description": "Stack manufacture; system integration and on-site installation services.",
        "seed_keywords": [
          "compressor",
          "rectifier",
          "transformer",
          "chiller",
          "heat exchanger",
          "de-ionised water unit",
          "separation vessel",
          "dryer"
        ],
        "core_isic_codes": [],
        "source_citation": {
          "doc_id": "doc_5660d4da4c3c",
          "doc_type": "other",
          "quote": "Several components, such as heat exchangers, pumps, compressors, feed tanks, rectifiers and transformers, are 'off-the-shelf'",
          "location": "https://www.gov.scot/publications/assessment-electrolysers-report/pages/3/",
          "grounded": true,
          "page": null,
          "sheet": null,
          "company_id": "https://www.gov.scot/publications/assessment-electrolysers-report/pages/3/",
          "source_filename": null,
          "content_key": null,
          "span_text": "Several components, such as heat exchangers, pumps, compressors, feed tanks, rectifiers and transformers, are 'off-the-shelf'",
          "char_start": 16258,
          "char_end": 16383,
          "match_method": "exact",
          "match_score": 1.0,
          "passage_id": null,
          "table_ref": null,
          "parser_version": null
        },
        "standards_mapping": {
          "nace_codes": [],
          "naics_codes": [],
          "sic_codes": [],
          "gics": [],
          "unmapped_isic_codes": []
        },
        "tier": "core",
        "lifecycle_stage": null,
        "criticality_flag": false,
        "human_approved": false
      },
      {
        "activity_id": "act_8accf95338d8",
        "name": "Electrolyser/fuel cell OEM manufacture and testing",
        "in_scope_description": "Original equipment manufacturers producing and supplying the standard electrolyser package (PEM, ALK, SOE), including testing facilities.",
        "out_of_scope_description": "Suppliers of generic components that are not part of an electrolyser package; hydrogen end-use.",
        "seed_keywords": [
          "electrolyser OEM",
          "PEM electrolyser",
          "alkaline electrolyser",
          "solid oxide electrolyser",
          "testing facilities"
        ],
        "core_isic_codes": [],
        "source_citation": {
          "doc_id": "doc_5660d4da4c3c",
          "doc_type": "other",
          "quote": "Electrolyser/fuel cell manufacturer Testing facilities",
          "location": "https://www.gov.scot/publications/assessment-electrolysers-report/pages/3/",
          "grounded": true,
          "page": null,
          "sheet": null,
          "company_id": "https://www.gov.scot/publications/assessment-electrolysers-report/pages/3/",
          "source_filename": null,
          "content_key": null,
          "span_text": "Electrolyser/fuel cell manufacturer Testing facilities",
          "char_start": 12109,
          "char_end": 12163,
          "match_method": "exact",
          "match_score": 1.0,
          "passage_id": null,
          "table_ref": null,
          "parser_version": null
        },
        "standards_mapping": {
          "nace_codes": [],
          "naics_codes": [],
          "sic_codes": [],
          "gics": [],
          "unmapped_isic_codes": []
        },
        "tier": "core",
        "lifecycle_stage": null,
        "criticality_flag": false,
        "human_approved": false
      },
      {
        "activity_id": "act_ca4d2ad5a960",
        "name": "System integration and installation",
        "in_scope_description": "Electrolyser-specialist system integrators (normally associated with the OEM); control systems (electrical hardware and software); metalwork, pipework and cabling; and project management, construction and commissioning contractors.",
        "out_of_scope_description": "Manufacture of the underlying components; ongoing operation and maintenance.",
        "seed_keywords": [
          "system integrator",
          "control system",
          "pipework",
          "cabling",
          "commissioning",
          "project management",
          "construction"
        ],
        "core_isic_codes": [],
        "source_citation": {
          "doc_id": "doc_5660d4da4c3c",
          "doc_type": "other",
          "quote": "System integration and installation focuses on the post-manufacture, pre-operation tier of the supply chain.",
          "location": "https://www.gov.scot/publications/assessment-electrolysers-report/pages/3/",
          "grounded": true,
          "page": null,
          "sheet": null,
          "company_id": "https://www.gov.scot/publications/assessment-electrolysers-report/pages/3/",
          "source_filename": null,
          "content_key": null,
          "span_text": "System integration and installation focuses on the post-manufacture, pre-operation tier of the supply chain.",
          "char_start": 17241,
          "char_end": 17349,
          "match_method": "exact",
          "match_score": 1.0,
          "passage_id": null,
          "table_ref": null,
          "parser_version": null
        },
        "standards_mapping": {
          "nace_codes": [],
          "naics_codes": [],
          "sic_codes": [],
          "gics": [],
          "unmapped_isic_codes": []
        },
        "tier": "core",
        "lifecycle_stage": null,
        "criticality_flag": false,
        "human_approved": false
      },
      {
        "activity_id": "act_37857b91efdb",
        "name": "Operation and maintenance services",
        "in_scope_description": "Services to operate and maintain electrolyser facilities over their operational lifetime (c. 25 years), requiring electrical, mechanical, software, control and chemical engineering, located close to where the electrolyser is deployed.",
        "out_of_scope_description": "Manufacture, installation and decommissioning of equipment; electricity generation itself.",
        "seed_keywords": [
          "operation and maintenance",
          "O&M",
          "servicing",
          "control and software",
          "electrolyser lifetime"
        ],
        "core_isic_codes": [],
        "source_citation": {
          "doc_id": "doc_5660d4da4c3c",
          "doc_type": "other",
          "quote": "Operation and maintenance, along with decommissioning, are key services throughout the operational lifetime of the electrolyser (c. 25 years).",
          "location": "https://www.gov.scot/publications/assessment-electrolysers-report/pages/3/",
          "grounded": true,
          "page": null,
          "sheet": null,
          "company_id": "https://www.gov.scot/publications/assessment-electrolysers-report/pages/3/",
          "source_filename": null,
          "content_key": null,
          "span_text": "Operation and maintenance, along with decommissioning, are key services throughout the operational lifetime of the electrolyser (c. 25 years).",
          "char_start": 17970,
          "char_end": 18112,
          "match_method": "exact",
          "match_score": 1.0,
          "passage_id": null,
          "table_ref": null,
          "parser_version": null
        },
        "standards_mapping": {
          "nace_codes": [],
          "naics_codes": [],
          "sic_codes": [],
          "gics": [],
          "unmapped_isic_codes": []
        },
        "tier": "core",
        "lifecycle_stage": null,
        "criticality_flag": false,
        "human_approved": false
      },
      {
        "activity_id": "act_179e56c8882d",
        "name": "End-of-life decommissioning and material recovery",
        "in_scope_description": "Decommissioning services, specialist electrical and chemical disposal, and recycling facilities for material recovery, including precious metals recycling from electrolyser stacks.",
        "out_of_scope_description": "Primary mining of virgin materials; general waste handling not related to electrolysers.",
        "seed_keywords": [
          "decommissioning",
          "recycling",
          "material recovery",
          "precious metals recycling",
          "disposal"
        ],
        "core_isic_codes": [],
        "source_citation": {
          "doc_id": "doc_5660d4da4c3c",
          "doc_type": "other",
          "quote": "Decommissioning services Material recovery and recycling",
          "location": "https://www.gov.scot/publications/assessment-electrolysers-report/pages/3/",
          "grounded": true,
          "page": null,
          "sheet": null,
          "company_id": "https://www.gov.scot/publications/assessment-electrolysers-report/pages/3/",
          "source_filename": null,
          "content_key": null,
          "span_text": "Decommissioning services Material recovery and recycling",
          "char_start": 12610,
          "char_end": 12666,
          "match_method": "exact",
          "match_score": 1.0,
          "passage_id": null,
          "table_ref": null,
          "parser_version": null
        },
        "standards_mapping": {
          "nace_codes": [],
          "naics_codes": [],
          "sic_codes": [],
          "gics": [],
          "unmapped_isic_codes": []
        },
        "tier": "core",
        "lifecycle_stage": null,
        "criticality_flag": false,
        "human_approved": false
      }
    ],
    "created_at": "2026-11-03T05:23:35.075242+00:00"
  },
  "derivation_method": "manual",
  "source_notes": "Standards mapping added: NACE, NAICS, SIC (ISIC crosswalk), GICS (LLM-classified).",
  "status": "draft",
  "ratified_by": null,
  "ratified_at": null,
  "based_on_version": 1,
  "created_at": "2026-11-03T05:23:46.533077+00:00"
}
```
