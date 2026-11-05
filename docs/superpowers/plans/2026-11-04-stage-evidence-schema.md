# Stage Evidence Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `build_taxonomy_schema` emits 12 stage-independent evidence fields per activity after the 4 existing
percentage fields.

**Architecture:** One module changes, `backend/arp/research/taxonomy_schema.py`: three new constant tables (types,
guidance, keywords) and a second field builder. No change to the extraction engine, storage, API or funnel.

**Tech Stack:** Python 3.12, pydantic, pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-stage-evidence-schema-design.md` (approved 2026-11-04).

## Global Constraints

- Field order per activity: the 4 `_pct` fields as today, then `revenue_amount, capex_amount, rd_amount,
  rd_programme, milestone, capacity, backlog, partnerships, news_momentum, stage_ideation, stage_innovation,
  stage_commercial`.
- New field id: `{taxonomy_id}_{activity_id}_{key}`; name `{activity.name}: {name suffix}` (suffixes from the spec's
  Fields table).
- Shared guidance prefix, exactly: "Extract only what the company explicitly states about this specific activity,
  with a verbatim quote. Never estimate, infer or compute a value."
- Field-specific guidance and keywords: exactly the spec's Guidance section and Keywords table.
- `milestone.allowed_values == ["lab", "pilot", "demonstration", "first_commercial", "series_production"]`;
  `capacity` `number` with `unit=None`.
- New fields: `required=False`, `version=taxonomy.version`, no default value.
- `field_id_for` and the 4 `_pct` fields unchanged.

## Review Focus

1. An activity with empty `seed_keywords`: new fields' keywords are just the field list (Task 2 test).
2. An activity name with punctuation ("Power-to-X"): the name is used verbatim in field names (Task 2 test).
3. A taxonomy with 0 activities: the schema has 0 fields, no error (Task 2 test).
4. Re-POST of an already-registered version gives registry version +1 (AC-10b, Task 3).
5. The R&D resolver still finds `_rd_pct` in the new schema (AC-11, Task 2).

---

### Task 1: Capture the `_pct` fields from main

**Files:**
- Create: `backend/tests/fixtures/stage_evidence/pct_fields_main.json`, `backend/tests/fixtures/stage_evidence/README.md`

- [ ] **Step 1:** Before any code change, build the fixture taxonomy (`tax_fx` v1, ratified; `act_a` "Electrolyser
  manufacturing" seed_keywords ["electrolyser"]; `act_b` "Fuel cell manufacturing" seed_keywords []) and dump
  `build_taxonomy_schema(...).fields` (all 8, `model_dump(mode="json", exclude={"created_at"})` if present) to the
  fixture. README says how it was produced and that the file is never edited.
- [ ] **Step 2:** Commit `test: capture taxonomy schema pct fields from main`.

### Task 2: Evidence fields in `build_taxonomy_schema`

**Files:**
- Modify: `backend/arp/research/taxonomy_schema.py`
- Modify: `backend/tests/test_taxonomy_schema.py` (only `test_schema_has_four_fields_per_activity_in_order`, which asserts the old count)
- Create: `backend/tests/test_stage_evidence_schema.py`

**Interfaces — Produces:**
- `EVIDENCE_KEYS: tuple[str, ...]` (the 12 keys, in order)
- `build_taxonomy_schema(taxonomy) -> DataPointSchema` (same signature)

- [ ] **Step 1: Failing tests** in `test_stage_evidence_schema.py`, each with literal expected values written out
  (not read from module constants): AC-1 `len == 32`; AC-2 exact id order; AC-3 `_pct` fields equal the Task 1
  fixture; AC-4a/b/c/d/e types; AC-5 allowed values; AC-6 prefix; AC-6b each key's full instructions; AC-7 each
  key's keywords for `act_a`; AC-7b names; AC-7c 12 distinct non-empty descriptions; AC-8 required/version;
  AC-9 draft raises; AC-11 `field_id_for(schema, "act_a", "rd") == "tax_fx_act_a_rd_pct"`; AC-14 no defaults,
  `ActivityDefinition` has no new attribute; Review Focus 1–3.
- [ ] **Step 2:** `cd backend && python3 -m pytest tests/test_stage_evidence_schema.py -q` → FAIL.
- [ ] **Step 3:** Implement: per-key tables `_EVIDENCE = {key: (name_suffix, data_type, guidance_text, keywords)}`
  and `_evidence_field(taxonomy, activity, key) -> FieldDefinition`; `build_taxonomy_schema` emits, per activity,
  the 4 `_pct` fields then the 12 evidence fields. Description per key: "{name suffix} for: {activity.name}
  ({activity.in_scope_description})".
- [ ] **Step 4:** Update `test_schema_has_four_fields_per_activity_in_order` to the new count and order (only that
  test); run `ruff check . && python3 -m pytest tests/test_stage_evidence_schema.py tests/test_taxonomy_schema.py
  tests/test_research_pipeline.py -q` → PASS (Postgres via `bash .claude/hooks/ensure-deps.sh postgres`).
- [ ] **Step 5:** Commit `feat(schema): stage evidence fields per activity`.

### Task 3: Registered schemas and golden cases

**Files:**
- Modify: `backend/tests/test_taxonomy_schema.py` (add tests only)
- Create: `backend/tests/golden/stage_evidence/cases.json`, `backend/tests/golden/stage_evidence/documents/*.txt`

- [ ] **Step 1:** Tests: AC-10 (register the fixture schema with the 4-fields-per-activity shape captured in Task 1
  via `SchemaRegistry.save`, then `GET .../schema` returns those 8 fields) and AC-10b (`POST .../schema` returns
  32 fields and `version == previous + 1`).
- [ ] **Step 2:** Golden cases for AC-12a/b in the format `arp golden-set precision` reads (look at an existing
  `--cases` file): (a) a short report text with a pilot plant and a commercial product line for electrolysers;
  (b) a report with only company-wide totals. Expected values as in the spec.
- [ ] **Step 3:** Run the unit tests → PASS. Run the golden command once with the real model (Gemini fallback:
  `ARP_LLM_MODEL=gemini-4-argon ARP_LLM_VERIFIER_MODEL=gemini-3.8-flash`) and paste the output in the PR.
- [ ] **Step 4:** Commit `test(schema): registered-schema and stage-evidence golden cases`.
