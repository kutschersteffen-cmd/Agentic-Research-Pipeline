# Decision store: ratifying an old version must not move "latest", and writers must not lose each other's edits

## Intent

A deep code review found two problems in the decision framework store. Both reproduce on current `main`
(4a4f273), probed with a throwaway `DecisionStore` in a temporary directory, no real data touched.

1. **Ratifying an older version moves "latest" back.** `DecisionStore._write`
   (`backend/arp/storage/decision_store.py:47`) always writes `latest.json` to the version it just wrote, and
   `ratify` (line 136) and `save` (line 51) both go through it. Scoring and publishing read "latest" via
   `get(framework_id)`, so they silently fall back to an older rule set.
2. **Unlocked read-modify-write.** `save`, `new_version` (line 65), `ratify` and `save_published` (line 181)
   read, decide, then write with no lock; `overrides.set_override` / `remove_override`
   (`backend/arp/decision/overrides.py:29,40`) do the same on one JSON file holding both the overrides in
   force and the history, and `_read` uses `path.read_text()` with no encoding. `TaxonomyStore` already has
   the right pattern (`KeyedLock` from `arp/storage/locks.py`).

## Evidence (probe on `main`)

| Probe | Result |
|-------|--------|
| `save` v1, `new_version` v2, then `ratify("fw1", 1)`; `get("fw1").version` | **1** (expected 2). `latest_ratified("fw1")` is also 1, because only v1 is ratified |
| Two threads, `set_override` for different `entity_key`s on one fresh file, 200 trials | one override lost in **196** of 200 trials |
| Two threads, `new_version` on a framework holding v1, 100 trials | versions on disk were not `[1, 2, 3]` in **100** of 100 trials (both read v1, both write v2, one edit gone) |

## Callers (grep)

- `ratify`: API `ratify_mechanism` (`api/routers/decision.py:423`, which reads `store.get` first for the
  authoritative-role check, then calls `ratify`); CLI `decision ratify` (`cli/decision.py:312`). Both pass
  a version or `None` (= latest).
- `save`: `routers/decision.py:294` (first save of a framework), `cli/decision.py:264-312` (import).
- `new_version`: `routers/decision.py:270` and `:294`, `cli/decision.py:275`.
- `_write`: only `save`, `new_version`, `ratify` inside `decision_store.py`.
- `save_published`: `routers/decision.py:775` and `:828`.
- `set_override` / `remove_override`: `routers/decision.py:677,690` (dataset overrides, file from
  `DecisionStore.overrides_path`) and `:715,731` (run overrides, `templates.run_overrides_path`, file
  `level_overrides.json` in the run folder). Plus `overrides.load` / `history` readers.
- Tests that touch these today: `tests/test_decision_store.py`, `test_decision_overrides.py`,
  `test_decision_api.py`, `test_decision_publish.py`. None ratifies an older version or races two writers.

## Goals

- After any write (`save`, `new_version`, `ratify`), `latest.json` names the highest version number on disk,
  so no write moves "latest" down. `get` still reads only the pointer (AC-4, AC-12); `ratify` with no version
  still ratifies the version the pointer names (AC-18).
- Writes to one framework are serialized, in this process (thread lock) and across processes (`flock`,
  so the `arp decision` CLI and a running API do not race), with the same `KeyedLock` pattern as
  `TaxonomyStore`.
- Concurrent `new_version` calls each get their own version number.
- `save_published` for one `snapshot_id` publishes exactly once even when called twice at the same time.
- Two concurrent `set_override` / `remove_override` calls on one overrides file keep both changes and
  both history entries. The overrides file is read as UTF-8.

## Non-goals

- Other stores, other files, and anything in `.claude/` or `.github/`.
- A way to deliberately roll "latest" back to an older version. If wanted, that is its own feature.
- Changing what `get` does with a missing or unreadable pointer (see AC-4, AC-12).
- API or schema changes: no request or response model changes, so no OpenAPI or `frontend/src/api` regeneration.

## Anti-goals

- A ratified version must stay unwritable by `save`, exactly as today.
- Nothing may fail where it succeeds today: a single writer sees identical results and messages.

## Approaches

1. **"Latest" = highest version number on disk, recomputed under the lock after each write (chosen,
   owner decision).** Also repairs a pointer left behind by the old bug or by a crash, with no migration.
2. **"Latest" = highest ratified version.** An unratified v2 draft would stop being "latest" for the
   editor UI and for `new_version`, which would then reuse a number. Rejected by the owner.
3. **Keep today's rule.** The bug stays. Rejected by the owner.

For collisions: **wait, then succeed (chosen, owner decision)** over failing with a `...Conflict` error
(rejected: routine concurrent edits would surface as 503s).

## Decided (owner answers, 2026-11-11)

1. After ratifying an older version, "latest" stays at the highest version number.
2. Two writers wait for each other and both succeed; no new error type.
3. The overrides file is in scope for this spec.

## Design

- `DecisionStore` gets a `KeyedLock` keyed by `framework_id`, lock file `<framework dir>/.lock`
  (does not match the `v*.json` glob in `list_versions`). `save`, `new_version` and `ratify` run their whole
  read-check-write cycle inside it.
- After writing a version file, `_write` sets the pointer to the highest version in `list_versions` instead
  of `config.version`. A missing, stale or unparseable pointer is therefore overwritten by the next write.
  `get` and `list_versions` otherwise read exactly as today.
- `save_published` takes a lock for the `_published` folder around its exists-check and write
  (lock file does not match `*.json`). Behaviour and the "already published" message stay.
- `overrides.py`: one module-level `KeyedLock` keyed by the file path, lock file `<name>.lock` beside the
  overrides file; `set_override` and `remove_override` hold it across read, edit and write; `_read` uses
  `read_text_utf8`. The builder checks that no code lists the folder containing an overrides file in a way
  that `*.lock` would break (the run folder `level_overrides.json`, `_overrides/`).
- Risk label for the implementing PR: `risk:normal` (no schema, auth or money).
- `openwiki/` does not need an update by hand; the weekly refresh covers it.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Framework `fw1` with v1 and v2 saved (v2 via `new_version`), neither ratified | `ratify("fw1", 1)` | `get("fw1").version == 2`; `get("fw1", 1).ratified is True`; `get("fw1", 2).ratified is False`; `json.loads(latest.json) == {"latest_version": 2}` | unit |
| AC-2 | Same, v2 is the newest | `ratify("fw1", 2)` | `get("fw1").version == 2` and `get("fw1").ratified is True`; `latest_ratified("fw1").version == 2` | unit |
| AC-3 | v1 (unratified) and v2 on disk | `save()` of an edited v1 (same `version=1`, new `name`) | `get("fw1").version == 2`; `get("fw1", 1).name` is the new name | unit |
| AC-4 | v1 and v2 on disk, `latest.json` deleted | `get("fw1")` | returns `None` (as today) | unit |
| AC-5 | v1 and v2 on disk, v2 unratified, `latest.json` is `{"latest_version": 1}` (left by the old bug) | `ratify("fw1", 2)` | `json.loads(latest.json) == {"latest_version": 2}`; `get("fw1").version == 2` | unit |
| AC-6 | v1 and v2 on disk, `latest.json` contains `not json`; v2 unratified | `ratify("fw1", 2)` | no exception; `json.loads(latest.json) == {"latest_version": 2}`; `get("fw1").version == 2` | unit |
| AC-7 | `fw1` with v1; both threads are released by one `threading.Barrier` immediately before the call; repeat 50 fresh stores | each of two threads calls `new_version` | `list_versions("fw1") == [1, 2, 3]` every time; the two returned versions are `{2, 3}`; `get("fw1").version == 3` | unit |
| AC-8 | Both threads are released by one `threading.Barrier` immediately before the call (repeat 50 fresh stores) | each of two threads calls `save_published` for the same `snapshot_id` with different content | exactly one call returns; the other raises `ValueError` `"<snapshot_id> is already published and cannot be overwritten."`; `get_published` returns the content of the call that returned | unit |
| AC-9 | An empty overrides file path; Both threads are released by one `threading.Barrier` immediately before the call (repeat 50 fresh paths) | each of two threads calls `set_override` with a different `entity_key` | `load(path)` has 2 overrides (both entity keys); `history(path)` has 2 entries, both `"action": "set"` | unit |
| AC-10 | A file made by `set_override(path, <override e1/c1>)`, so `history(path)` has 1 entry; Both threads are released by one `threading.Barrier` immediately before the call (repeat 50 fresh files) | thread A calls `remove_override(path, "e1", "c1", "rev", "why")`, thread B calls `set_override` for `e2`/`c1` | `load(path)` is exactly the one override `e2`/`c1`; `history(path)` has 3 entries: set e1 first, then removed e1 and set e2 in either order | unit |
| AC-11 | An overrides file written with reason `"Münchener Rück"`, with `Path.read_text` patched to decode as latin-1 when no encoding is passed (as `tests/test_file_store_encoding.py` does) | `load(path)` | `load(path)[0].reason == "Münchener Rück"` | unit |
| AC-12 | `latest.json` contains `not json` | `get("fw1")` | raises `json.JSONDecodeError` (as today; reading is not changed by this spec) | unit |
| AC-13 | Empty store | `save(v1)` | `get("fw1").version == 1`; `get("fw1").ratified is False` | unit |
| AC-14 | `fw1` v1 saved, unratified | `ratify("fw1", ratified_by="A. Novak")` (no version) | returned config has `version == 1`, `ratified is True`, `ratified_by == "A. Novak"`; `get("fw1").version == 1` | unit |
| AC-15 | `fw1` v1 ratified (AC-14 state) | `new_version(...)` | `get("fw1").version == 2`, `get("fw1").ratified is False`, `get("fw1", 1).ratified is True` | unit |
| AC-16 | `fw1` v1 ratified | `save()` with `version=1` | raises `ValueError` `"fw1 v1 is ratified and cannot be overwritten -- create a new version instead."` | unit |
| AC-17 | `fw1` v1 saved | `ratify("fw1", 9)` | raises `ValueError` `"Unknown framework: fw1 v9"` | unit |
| AC-18 | v1 (unratified) and v2 on disk, `latest.json` is `{"latest_version": 1}` | `ratify("fw1")` (no version) | v1 is ratified (returned `version == 1`, `ratified is True`); v2 is untouched (`get("fw1", 2).ratified is False`); `json.loads(latest.json) == {"latest_version": 2}` | unit |
| AC-19 | An empty overrides file path, one writer | `set_override(path, <override x/y>)` | returns a list with exactly one `LevelOverride` whose `entity_key == "x"` and `criterion_id == "y"` | unit |
| AC-20 | File from AC-19, bytes and `history(path)` recorded | `remove_override(path, "nope", "y", "r", "why")` | raises `KeyError` `"No override for nope · y."`; file bytes and `history(path)` identical to before | unit |
| AC-21 | `fw1` with v1, v2 after `save`, `new_version` and `ratify` | `list_versions("fw1")` and the names of all files in the `fw1` folder | `list_versions("fw1") == [1, 2]`; no file name in the folder ends in `.lock` other than the single file `.lock` | unit |
| AC-24 | `save_published` called once for `snapshot_id="snap1"` | `list_published()` | returns exactly one snapshot, `snapshot_id == "snap1"` | unit |
| AC-25 | `set_override` called once on `<frameworks_dir>/_overrides/ds1.json` | `sorted(p.name for p in (<frameworks_dir>/_overrides).glob("*.json"))` and `store.list_datasets()` | `["ds1.json"]`; `list_datasets()` returns `[]` | unit |
| AC-22 | `fw1` with v1; two processes (`multiprocessing`, spawn) released together (repeat 20 fresh stores) | each calls `new_version` on a store built on the same directory | `list_versions("fw1") == [1, 2, 3]` every time | unit |
| AC-23 | `fw1` v1 and v2 created with `store.save` and `store.new_version` on the app's `DecisionStore`, v2 the newest; default test user (analyst role, scoring framework, not `authoritative`) | `POST /api/decision/mechanisms/fw1/ratify?version=1`, then `GET /api/decision/mechanisms/fw1` | ratify returns 200 with body `version == 1` and `ratified == true`; the GET body has `config.version == 2` | unit |
| AC-26 | `fw1` v1 unratified; both threads released by one `threading.Barrier` immediately before the call (repeat 50 fresh stores) | thread A `ratify("fw1", 1)`, thread B `save()` of v1 with `name="new"` | v1 ends ratified every time, and either `get("fw1", 1).name == "new"` (B ran first) or B raised the AC-16 `ValueError` (A ran first); never unratified and never a lost name with no error | unit |
| AC-27 | v1 and v2 on disk, `json.loads(latest.json) == {"latest_version": 1}` | `new_version(...)` on `fw1` | returned `version == 3`; `list_versions("fw1") == [1, 2, 3]`; `json.loads(latest.json) == {"latest_version": 3}` | unit |

Must not change: a plain `save` and `ratify` of the newest version (AC-13 to AC-15), the ratified-overwrite
refusal and unknown-version errors (AC-16, AC-17), single-writer override behaviour and messages (AC-19,
AC-20), what `get` does with a missing or corrupt pointer (AC-4, AC-12), folder listings (AC-21, AC-24, AC-25).
AC-1 to AC-22 and AC-24 to AC-27 call the store and `overrides` modules directly (threads, processes, patched file reads), so they stay `unit` permanently. Only AC-23 may move to `holdout` once `HOLDOUT_TOKEN` is set.
