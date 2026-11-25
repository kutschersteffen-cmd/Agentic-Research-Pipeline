# Config and grounding: the documented ESG URL setting works, short non-English quotes ground

Status: Draft, for owner approval
Slug: `config-grounding`
Risk: `risk:normal` (backend only; touches `arp/config.py` and `arp/grounding.py`; no auth, schema, money or UI)
Size: `S`, one PR, no slices (bug-list bundle G = item 13)

## Decisions for the owner

None needed a question. Every choice is listed under "Defaults taken"; approving the spec approves them.

## Why

The review of 23 Nov 2026 (`/mnt/project-files/antigravity-patch-review/bug-list.md`, IDs C2.1 and C2.5;
consolidated rows M7 and M8) found two faults that still reproduce on `main` at `8eaa452`:

1. **`ARP_ESG_API_URL` is ignored.** The README (line 231), the 503 from `api/routers/security_master.py:77`,
   the error in `portfolio/climate/esg_api_source.py:34` and the frontend message map all tell an
   administrator to set `ARP_ESG_API_URL`. The setting `esg_api_base_url` in `backend/arp/config.py:113`
   reads `ARP_ESG_API_BASE_URL` (env prefix `ARP_` plus the field name). Setting the documented name leaves
   `Settings().esg_api_base_url` at `None`, so the ESG pull says "not configured" although it was.
2. **Short non-English quotes never ground.** `_find_match` in `backend/arp/grounding.py:175-178` rejects a
   quote shorter than `SHORT_QUOTE_CHARS` (20 normalised characters) unless it holds `[a-z]{3,}` (with a
   digit) or `[a-z]{2,}` (without). `[a-z]` is ASCII only, so `"Umsatz 42"` grounds but `"Größe 5"`,
   `"Été 12"`, `"Выручка 7"` and `"売上 42"` never do, even when they appear verbatim in the source. ESEF
   filings and other non-English reports lose correct short citations.

The Antigravity patch has reference fixes; this spec states the behaviour instead of pointing at it.

## What the user can do afterwards that they cannot do today

- Set `ARP_ESG_API_URL` (in the environment or in `.env`) as the docs say, and have the ESG pull use it.
  `ARP_ESG_API_BASE_URL` keeps working for anyone who found the old name.
- Get a short citation such as `"Größe 5"`, `"Выручка 7"` or `"売上 42"` marked grounded when it appears in
  the source, the same way `"Umsatz 42"` is today.

## What exists today (main `8eaa452`)

- `Settings` (`backend/arp/config.py`) uses `SettingsConfigDict(env_prefix="ARP_", env_file=".env",
  extra="ignore")`. `esg_api_base_url: str | None = None` has no alias.
- Callers read `settings.esg_api_base_url` (`security_master.py:76`, `esg_api_source.py:32,36`,
  `portfolio/monitoring/scheduler.py:43`). Tests build `Settings(esg_api_base_url=...)`
  (`backend/tests/test_esg_api_source.py:21,45,139`) and `settings.model_copy(update={"esg_api_base_url": ...})`
  (`backend/tests/test_monthly_run.py`).
- `grounding.py`: `_normalize` folds dashes, quotes and ligatures, drops soft hyphens, collapses whitespace
  and lowercases. `_find_match` applies the two short-quote guards above, then `_find_in_span` tries a raw,
  then a normalised match, and takes the fuzzy path only for quotes of `SHORT_QUOTE_CHARS` or more.
  `is_grounded(quote, source_text, fuzzy_threshold=0.92)` is `_find_match(...) is not None`.
- `backend/tests/test_grounding.py:355-386` pins today's short-quote rules (bare `"42"`, `"-"`, `"n/a"` fail;
  `"Yes"` grounds by exact match only; `"42 MWh"`, `"42 tCO2e"` ground).

## Goals

- G1. `ARP_ESG_API_URL` sets `esg_api_base_url`, from the process environment and from `.env`.
- G2. `ARP_ESG_API_BASE_URL` still sets it; when both are set in the same place, `ARP_ESG_API_URL` wins.
- G3. Code and tests that pass `esg_api_base_url` by field name (`Settings(...)`, `model_copy`) keep working.
- G4. The short-quote guards count letters of any script, not only `a-z`.
- G5. A 2-character CJK word (Han, Hiragana, Katakana or Hangul) is enough label for a short quote with a
  number.

## Non-goals

- Renaming the field `esg_api_base_url` or any other setting.
- Changing README, error messages or the frontend message map (they already say `ARP_ESG_API_URL`).
- Changing `SHORT_QUOTE_CHARS`, the fuzzy threshold, `_normalize`, or how long quotes ground.
- Unicode normalisation (NFC/NFD folding) of quotes or sources.
- Any other bug-list item. No UI change.

## Anti-goals (must stay true)

- A1. A bare number (`"42"`) never grounds as a short quote.
- A2. Punctuation-only short quotes (`"-"`, `"n/a"`) never ground.
- A3. `"Yes"` still grounds by exact or normalised match (never fuzzy), and short quotes (ASCII or not) never take the fuzzy path.
- A4. A 2-letter non-CJK word with a number (`"EU 42"`) still does not ground as a short quote.
- A5. A single CJK character with a number (`"円 5"`) does not ground as a short quote.

## Design

### Setting (`backend/arp/config.py`)

`esg_api_base_url` accepts, in this order, `ARP_ESG_API_URL`, `ARP_ESG_API_BASE_URL` and its field name
`esg_api_base_url` (pydantic `AliasChoices` on `validation_alias` is the expected tool). With a
`validation_alias`, pydantic-settings reads the names literally and ignores `env_prefix`, so both env names
are written in full. The field name must be in the choices (or the model must allow population by name),
or `Settings(esg_api_base_url=...)` stops working. Precedence stays pydantic-settings' own: init arguments,
then process environment, then `.env`, then the default. Within one of those sources the first matching name
in the order above wins. Environment variable names stay case-insensitive, as today.

Update the field's trailing comment to name both variables. No other field changes.

### Short-quote guards (`backend/arp/grounding.py`)

In `_find_match`, for a normalised quote shorter than `SHORT_QUOTE_CHARS`:

- **With a digit:** reject unless it holds a run of 3 or more letters of any script (`[^\W\d_]{3,}` in
  Python `re`), or a run of 2 or more letters (`[^\W\d_]`) whose code points all lie in the CJK ranges: Hiragana and Katakana `U+3040-U+30FF`, CJK Unified
  Ideographs and Extension A `U+3400-U+4DBF`, `U+4E00-U+9FFF`, compatibility ideographs `U+F900-U+FAFF`,
  Hangul syllables `U+AC00-U+D7AF`. Punctuation and marks inside those ranges (`・` U+30FB, `゠` U+30A0,
  `゛゜` U+309B/C, combining U+3099/A) are not letters and never count.
- **Without a digit:** reject unless it holds a run of 2 or more letters of any script (`[^\W\d_]{2,}`).

Everything after the guards is unchanged, including the `len(norm_quote) < SHORT_QUOTE_CHARS` early return in
`_find_in_span` that keeps short quotes off the fuzzy path. Update the comment above the guards to say
"letters of any script" and to name the CJK exception.

### Tests and golden set

The builder adds unit tests for the new passes next to the existing short-quote tests in
`backend/tests/test_grounding.py` and keeps every existing one. The PR touches `arp/grounding.py` and
`arp/config.py`, so CI runs `arp golden-set run`; it is not a merge gate (owner, 2026-11-22), and the
dispatcher reports what it shows. A red run whose log says "replaced by Gemini" means the Anthropic credit
is empty, not a code fault.

## Defaults taken

1. **`ARP_ESG_API_URL` wins** over `ARP_ESG_API_BASE_URL` when both are set in the same source, because it
   is the documented name.
2. **Process environment beats `.env`** whatever the name: `ARP_ESG_API_BASE_URL` in the environment wins
   over `ARP_ESG_API_URL` in `.env`. This is pydantic-settings' normal precedence; no custom merging.
3. **An init argument beats the environment**, as for every other setting.
4. **No deprecation warning** for `ARP_ESG_API_BASE_URL`; it is simply a second accepted name.
5. **CJK set** = Hiragana, Katakana, Han (BMP blocks above) and Hangul syllables. Han extension B and later
   (outside the BMP) are not in the 2-character exception; they still count as letters for the 3-letter run.
6. **2 CJK characters, not 1**, are needed next to a number; a single CJK character is too weak a label
   (A5), as a single Latin letter is today.
7. **Without a digit, 2 letters of any script** ground, so `"Да"` and `"売上"` behave like `"Yes"`.
8. **No Unicode normalisation is added.** A quote in decomposed form (`"Éte"`) against a source in
   composed form does not match today and still does not.

## Acceptance

These are `holdout` rows that call `Settings()` and `is_grounded` directly, the same way the approved
`workspace-gpu` spec's rows call `get_settings()`; the app exposes neither through the API.

Config rows build `Settings()` in a test with both `ARP_ESG_API_URL` and `ARP_ESG_API_BASE_URL` removed from
the process environment and the working directory set to an empty temporary directory (no `.env`), unless
"Given" says otherwise. Grounding rows call `arp.grounding.is_grounded(quote, source)` with the default
`fuzzy_threshold` (0.92).

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | env `ARP_ESG_API_URL=https://esg-a.example/v1` | `Settings()` | `.esg_api_base_url == "https://esg-a.example/v1"` | holdout |
| AC-2  | env `ARP_ESG_API_BASE_URL=https://esg-b.example/v1` | `Settings()` | `.esg_api_base_url == "https://esg-b.example/v1"` | holdout |
| AC-3  | env `ARP_ESG_API_URL=https://esg-a.example/v1` and env `ARP_ESG_API_BASE_URL=https://esg-b.example/v1` | `Settings()` | `.esg_api_base_url == "https://esg-a.example/v1"` | holdout |
| AC-4  | `.env` in the working directory holding the line `ARP_ESG_API_URL=https://esg-e.example/v1`; neither name in the process env | `Settings()` | `.esg_api_base_url == "https://esg-e.example/v1"` | holdout |
| AC-5  | `.env` in the working directory holding the line `ARP_ESG_API_BASE_URL=https://esg-f.example/v1`; neither name in the process env | `Settings()` | `.esg_api_base_url == "https://esg-f.example/v1"` | holdout |
| AC-6  | env `ARP_ESG_API_BASE_URL=https://esg-b.example/v1`; `.env` holding `ARP_ESG_API_URL=https://esg-e.example/v1` | `Settings()` | `.esg_api_base_url == "https://esg-b.example/v1"` | holdout |
| AC-7  | neither name in env or `.env` | `Settings()` | `.esg_api_base_url is None` | holdout |
| AC-8  | env `ARP_ESG_API_URL=https://esg-a.example/v1` | `Settings(esg_api_base_url="https://esg-c.example/v1")` | `.esg_api_base_url == "https://esg-c.example/v1"` | holdout |
| AC-9  | `s = Settings()` with neither name set | `s.model_copy(update={"esg_api_base_url": "https://esg-d.example/v1"})` | the copy's `.esg_api_base_url == "https://esg-d.example/v1"` | holdout |
| AC-10 | env `ARP_ESG_API_TOKEN=tok-1` | `Settings()` | `.esg_api_token == "tok-1"` (unchanged) | holdout |
| AC-11 | — | `is_grounded("Größe 5", "Tabelle 3: Größe 5 Mitarbeiter")` | `True` | holdout |
| AC-12 | — | `is_grounded("Été 12", "Saison Été 12 semaines")` | `True` | holdout |
| AC-13 | — | `is_grounded("Выручка 7", "Итого: Выручка 7 млрд руб.")` | `True` | holdout |
| AC-14 | — | `is_grounded("売上 42", "当期 売上 42 億円")` | `True` | holdout |
| AC-15 | — | `is_grounded("매출 42", "올해 매출 42 억원")` | `True` | holdout |
| AC-16 | — | `is_grounded("Да", "Ответ: Да.")` | `True` | holdout |
| AC-17 | — | `is_grounded("売上", "今期の売上は増加")` | `True` | holdout |
| AC-18 | — | `is_grounded("42", "Total was 42 units across sites.")` | `False` (unchanged) | holdout |
| AC-19 | — | `is_grounded("-", "Scope 3 emissions: - (not reported)")` | `False` (unchanged) | holdout |
| AC-20 | — | `is_grounded("n/a", "Scope 3 emissions: n/a")` | `False` (unchanged) | holdout |
| AC-21 | — | `is_grounded("Yes", "Board oversight of climate: Yes. Next row.")` | `True` (unchanged) | holdout |
| AC-22 | — | `is_grounded("Yes", "Board oversight of climate: Yse.")` | `False` (unchanged) | holdout |
| AC-23 | — | `is_grounded("Umsatzerlöse 42 Mix", "Umsatzerlöse 42 Mio.")` (19 normalised chars, one letter off) | `False` (unchanged: a short non-ASCII quote never fuzzy-matches, although its fuzzy coverage 18/19 = 0.947 is above 0.92) | holdout |
| AC-24 | — | `is_grounded("EU 42", "EU 42 bn")` | `False` (unchanged) | holdout |
| AC-25 | — | `is_grounded("円 5", "合計 円 5")` | `False` (unchanged) | holdout |
| AC-26 | — | `is_grounded("Umsatz 42", "Umsatz 42 Mio")` | `True` (unchanged) | holdout |
| AC-27 | — | `is_grounded("Größe 5", "Die Größe 6 gilt")` | `False` (unchanged: a different number never grounds) | holdout |
| AC-28 | — | `is_grounded("・・ 5", "x ・・ 5")` | `False` (unchanged: CJK punctuation is not a letter) | holdout |
| AC-29 | — | `is_grounded("ドル 5", "為替 ドル 5 円")` | `True` (Katakana word) | holdout |
| AC-30 | — | `is_grounded("𠀋𠀋 5", "x 𠀋𠀋 5")` | `False` (unchanged: Han extension B is outside the 2-character exception) | holdout |
| AC-31 | — | `is_grounded("𠀋𠀋𠀋 5", "x 𠀋𠀋𠀋 5")` | `True` (3 letters of any script) | holdout |
| AC-32 | — | `is_grounded("Not applicable", "Scope 3 reporting:  not\napplicable for this entity.")` (`\n` is a newline) | `True` (unchanged: short quotes still ground by normalised match) | holdout |
| AC-33 | `.env` in the working directory holding the two lines `ARP_ESG_API_BASE_URL=https://esg-f.example/v1` and `ARP_ESG_API_URL=https://esg-e.example/v1`; neither name in the process env | `Settings()` | `.esg_api_base_url == "https://esg-e.example/v1"` | holdout |
| AC-34 | env `arp_esg_api_url=https://esg-l.example/v1` (lower case) | `Settings()` | `.esg_api_base_url == "https://esg-l.example/v1"` (names are case-insensitive, as for every other setting) | holdout |
| AC-35 | env `arp_esg_api_base_url=https://esg-m.example/v1` (lower case) | `Settings()` | `.esg_api_base_url == "https://esg-m.example/v1"` (unchanged) | holdout |

Must not change: bare numbers, punctuation-only quotes and 2-letter non-CJK labels with a number stay
ungrounded (AC-18, AC-19, AC-20, AC-24), and so do a single CJK character, CJK punctuation, two Han extension B characters or a different number
(AC-25, AC-28, AC-30, AC-27); `"Yes"` grounds by exact or normalised match, never fuzzy (AC-21, AC-22, AC-32); short quotes never
fuzzy-match (AC-23); ASCII labels ground as before (AC-26); names stay case-insensitive (AC-35); `ARP_ESG_API_TOKEN` reads as before
(AC-10); init by field name and `model_copy` keep working (AC-8, AC-9). The existing tests in
`backend/tests/test_grounding.py`, `backend/tests/test_esg_api_source.py` and `backend/tests/test_monthly_run.py`
stay unchanged and green.
