# Taxonomy from stocks, layer 1 (stated index rules) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `arp taxonomy infer start --methodology <doc>` extracts the document's stated index rules, maps the ones with a recognised form onto a draft `ConstructionSpec`, and stores them under the run JSON key `index_rules`.

**Architecture:** `extract_source` gets a `checklist` parameter; a new `INDEX_RULES_CHECKLIST` (5 items) returns quoted rules. A new pure module `stock_inference/index_rules.py` maps rules to spec fields with regexes over the **document span** the quote grounded to (never the model's numbers). `run.start` calls it once per methodology doc and passes the default checklist's stated theme to the theme step.

**Tech Stack:** Python, pydantic, pytest, `FakeLLMClient`.

**Spec:** `docs/superpowers/specs/2026-11-04-taxonomy-from-stocks-design.md`, section "Layer 1: stated index rules", rows AC-42 to AC-46.

## Global Constraints

- Numbers in mapped rules are parsed from the grounded quote in code, never taken from the model.
- `extract_source` default behaviour (authority agent) unchanged: default `checklist=AUTHORITY_CHECKLIST`.
- Run JSON `index_rules` = `{currency, construction_spec, rules[{text, quote, source, mapped_to}]}`; `rules` in document order; `null` when no methodology is given.
- `construction_spec` validates as `ConstructionSpec`; fields no rule sets keep the model's default.
- One failing model call (bad reply) never ends the run.

## Review Focus

1. Fuzzy-grounded quote whose number differs from the document (model says USD 600 million, doc says 500): the mapped value must be 500 (parse from `span_text`).
2. Run JSON 4-decimal rounding would turn `base_weighting.floor = 1e-9` into `0` and break validation: `construction_spec` is exempt from rounding.
3. "reviewed semi-annually" must map to `semi_annual`, not `annual`.
4. Two rules for the same single field (e.g. two caps): the first maps, the later one gets `mapped_to: null`.
5. A model call that raises for one checklist item: the other items' rules are still kept and `start` still reaches `themes_ready`.

---

### Task 1: `extract_source(checklist=...)` and `INDEX_RULES_CHECKLIST`

**Files:**
- Modify: `backend/arp/research/authority_taxonomy/checklist.py` (add list)
- Modify: `backend/arp/research/authority_taxonomy/extract.py` (param, draft model, rule handling)
- Test: `backend/tests/test_authority_extract_index_rules.py` (new)

**Interfaces — Produces:**
- `INDEX_RULES_CHECKLIST: list[ChecklistItem]`, keys `eligibility, selection, weighting, caps, rebalance`, each with a question and keyword list (e.g. caps: `cap, capped, exceed, maximum, weight, limit`; rebalance: `review, reviewed, rebalance, rebalanced, quarterly, annual, annually, semi-annual, semi-annually`; eligibility includes `exclude, discretion, committee, minimum, capitalisation, liquidity`).
- `IndexRulesDraft(rules: list[IndexRuleItem(text, quote)])` — one output model for all 5 items.
- `StatedRule(kind: str, text: str, quote: str, source: str)`; `SourceExtraction.rules: list[StatedRule]` (default empty). `quote` is the document span the model's quote grounded to.
- `extract_source(url, text, *, theme_name, scope, value_chain, llm, checklist=AUTHORITY_CHECKLIST)`.

- [ ] Test `test_index_rule_quote_is_document_span`: doc "...a minimum free-float market capitalisation of USD 500 million...", fake `IndexRulesDraft` returns that sentence; `checklist=[eligibility item]` → `out.rules == [StatedRule(kind="eligibility", text=..., quote=<doc span>, source=url)]`.
- [ ] Test `test_ungrounded_rule_dropped` (AC-46 at this level): quote absent from doc → `out.rules == []`, report `not_in_source`.
- [ ] Existing `tests/test_authority_taxonomy*` stay green unchanged.
- [ ] Implement, run `pytest tests/test_authority_extract_index_rules.py tests/ -k authority`, commit.

### Task 2: map rules to `ConstructionSpec`

**Files:**
- Create: `backend/arp/research/stock_inference/index_rules.py`
- Modify: `backend/arp/research/stock_inference/schemas.py` (type `index_rules`)
- Test: `backend/tests/test_stock_inference_index_rules.py`

**Interfaces — Produces:**
- `IndexRule(text, quote, source, mapped_to: str | None)`, `IndexRules(currency: str | None, construction_spec: ConstructionSpec, rules: list[IndexRule])`; `InferRun.index_rules: IndexRules | None`.
- `map_rules(rules: list[StatedRule]) -> IndexRules` (pure; rules already in document order).

Recognised forms (first match wins per rule; regex over the quote, case-insensitive):
| Form | Target | `mapped_to` |
|---|---|---|
| `5/10/40` | `constraints.ucits_5_10_40 = True` | `constraints.ucits_5_10_40` |
| market capitali[sz]ation + money | `MetricThresholdScreen(field="float_mcap", min_value)` | `screens[i].min_value` |
| (average) daily trad(ed/ing) value + money | `MetricThresholdScreen(field="adv_3m", min_value)` | `screens[i].min_value` |
| revenue/sales/exposure + `%` | `MetricThresholdScreen(field="relevance", min_value=pct/100)` | `screens[i].min_value` |
| cap/exceed/maximum + `%` | `constraints.single_name_cap = pct/100` | `constraints.single_name_cap` |
| exclu* + GICS sector names present in the quote | `CategoryScreen(field="sector", deny=[names])` | `screens[i].deny` |
| `<n>` constituents/companies/stocks/securities (fixed count) | `TopN(n, score_field="float_mcap" if "largest" else "relevance")` | `selection.n` |
| equal(ly) weight / market-cap weight | `base_weighting.scheme` `equal` / `free_float_mcap` | `base_weighting.scheme` |
| monthly / quarterly / semi-annual(ly), half-year(ly), twice a year / annual(ly), once a year | `calendar.review_frequency` | `calendar.review_frequency` |

Money: `USD|EUR|GBP|CHF|JPY|$|€|£` then number with `,` thousands and optional `thousand|million|mn|m|billion|bn`. First money's currency → `index_currency` and `currency`. A single-valued target already set → later rule `mapped_to: null`.

- [ ] Tests (one per row of AC-42..45 plus Review Focus 3, 4): AC-42 asserts `screens[0]` type/field/`min_value == 500_000_000`, `index_currency == "USD"`, `mapped_to == "screens[0].min_value"`, and `spec.model_dump(exclude={"screens","index_currency"}) == ConstructionSpec().model_dump(exclude=...)`; AC-43 `0.08`; AC-44 `semi_annual`; AC-45 `mapped_to is None`, rule kept.
- [ ] Implement, run, commit.

### Task 3: wire into `infer start`

**Files:**
- Modify: `backend/arp/research/stock_inference/run.py`
- Test: `backend/tests/test_cli_taxonomy_infer.py` (add tests only)

**Interfaces — Consumes:** Tasks 1-2. **Produces:** `async stated_index_rules(docs, name, llm) -> tuple[IndexRules, str | None]` (rules, stated theme) in `index_rules.py`.

- Per methodology doc: default checklist run (`value_chain=False`) for the stated theme (first non-empty `theme_description`), then one `extract_source` per `INDEX_RULES_CHECKLIST` item; each call in its own `try`, a raising call is logged and skipped. `source` = the path/URL as given. Rules sorted by doc order, then quote position.
- `start` stores `index_rules` (None without `--methodology`) and passes the stated theme to `propose_themes`.
- `dump` exempts `construction_spec` from rounding.

- [ ] CLI tests: AC-42 end to end (`--methodology fixture.txt`, `show --json`, `ConstructionSpec.model_validate(...)`), AC-46 end to end, no `--methodology` → `index_rules is None`, Review Focus 5 (one item raises, run still `themes_ready`).
- [ ] Run `ruff check . && pytest tests/test_cli_taxonomy_infer.py tests/test_stock_inference_index_rules.py tests/test_authority_extract_index_rules.py`, commit.
- [ ] OpenAPI: `InferRun` is not an API model, so no export needed (verify with `scripts/export_openapi.py` diff).
