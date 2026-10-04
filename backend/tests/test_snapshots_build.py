from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date

import pytest

from arp.holdings.intake import ingest
from arp.holdings.validate import validate
from arp.publish.facts import FactCandidate, FactEvent, plan_version, ts_now
from arp.publish.reader import visible
from arp.schemas.common import Citation
from arp.snapshots import schema
from arp.snapshots.build import (
    SnapshotFrozen,
    build_correction,
    build_snapshot,
    dataset_path,
    read_manifest,
    snapshot_dir,
)
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.run_store import RunStore

AS_OF, MONTH = "2026-10-31", "2026-10"
LEI = "5493001KJTIIGC8Y1R12"


def _rows(kind, weights=(60, 40)):
    raw = [{"_row": 2, "isin": "US0378331005", "weight": weights[0], "market_value": 600, "currency": "EUR"},
           {"_row": 3, "isin": "DE0007164600", "weight": weights[1], "market_value": 400, "currency": "EUR"}]
    v = validate(raw, kind=kind, as_of=AS_OF, today=date(2027, 1, 31))
    assert not v.errors, v.errors
    return v


def _ingest(env, kind, holder, weights=(60, 40)):
    store, rs, idmap = env
    ingest(store, _rows(kind, weights), kind=kind, holder_id=holder, as_of=AS_OF, source="file", source_ref="f.csv",
           principal=None, override_reason=None, run_store=rs, idmap=idmap)


def _fact(field, value=1.0, prev=None, at="2026-10-01T09:00:00.000000+00:00"):
    cand = FactCandidate(
        issuer_key=LEI, issuer_scheme="LEI", field_id=field, period_end="2025-12-31", value=value, unit="t",
        canonical_value=value, canonical_unit="t", state="approved",
        citation=Citation.model_construct(doc_id="d1", content_key="ck"),
        source_run_id="run1", observed_at=at, item_key=field,
    )
    return plan_version(prev, cand, release_id="rel_1", now=at).fact


class World:
    """Facts and events in memory, read through the real as-of rule."""

    def __init__(self):
        self.facts = [_fact("f1"), _fact("f2"), _fact("f3")]
        self.events: list[FactEvent] = []

    def facts_as_of(self, as_of):
        return visible(self.facts, as_of)

    def events_since(self, after):
        return [e for e in self.events if e.at > after]

    def _event(self, kind, f, at):
        self.events.append(FactEvent(event_type=kind, fact_id=f.fact_id, issuer_key=f.issuer_key, field_id=f.field_id,
                                     period_end=f.period_end, basis=f.basis, release_id=f.release_id, at=at))

    def withdraw(self, field):
        at = ts_now()
        i, f = next((i, f) for i, f in enumerate(self.facts) if f.field_id == field and f.valid_to is None)
        self.facts[i] = f.model_copy(update={"valid_to": at})
        self._event("withdrawn", f, at)

    def restate(self, field, value):
        at = ts_now()
        i, f = next((i, f) for i, f in enumerate(self.facts) if f.field_id == field and f.valid_to is None)
        new = _fact(field, value, prev=f, at=at)
        self.facts[i] = f.model_copy(update={"valid_to": at, "superseded_by": new.fact_id})
        self.facts.append(new)
        self._event("restated", new, at)


@pytest.fixture
def env(tmp_path):
    e = PortfolioStore(tmp_path / "pf"), RunStore(tmp_path / "runs"), IdentifierMapStore(tmp_path / "idmap.jsonl")
    _ingest(e, "index", "IX1")
    _ingest(e, "portfolio", "PF1")
    return e


@pytest.fixture
def world():
    return World()


def _build(env, world, root, **kw):
    return build_snapshot(AS_OF, root=root, portfolio_store=env[0], facts_as_of=world.facts_as_of, **kw)


def _correct(env, world, root):
    return build_correction(MONTH, root=root, portfolio_store=env[0], facts_as_of=world.facts_as_of,
                            events_since=world.events_since)


def _hashes(m):
    return {(d.name, d.major): d.files for d in m.datasets}


def _jsonl(root, m, dataset, major=1):
    path = dataset_path(root, m.month, m.revision, dataset, "jsonl", major)
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_same_inputs_same_hashes(env, world, tmp_path):
    a, b = _build(env, world, tmp_path / "a"), _build(env, world, tmp_path / "b")
    assert _hashes(a) == _hashes(b)
    assert {d.name for d in a.datasets} == set(schema.DATASETS)
    assert a.snapshot_id == "2026-10.r1" and a.as_of == AS_OF


def test_frozen_snapshot_refuses_rewrite(env, world, tmp_path):
    _build(env, world, tmp_path)
    with pytest.raises(SnapshotFrozen, match="2026-10.r1 is frozen"):
        _build(env, world, tmp_path)


def test_manifest_hashes_match_stored_files(env, world, tmp_path):
    m = _build(env, world, tmp_path)
    for d in m.datasets:
        for fmt, digest in d.files.items():
            data = dataset_path(tmp_path, MONTH, 1, d.name, fmt, d.major).read_bytes()
            assert hashlib.sha256(data).hexdigest() == digest


def test_r1_stays_readable_after_r2(env, world, tmp_path):
    r1 = _build(env, world, tmp_path)
    world.withdraw("f1")
    r2 = _correct(env, world, tmp_path)
    assert r2.revision == 2 and r2.supersedes == "2026-10.r1" and len(r2.changes) == 1
    assert r2.changes[0]["event_type"] == "withdrawn" and r2.changes[0]["field_id"] == "f1"
    assert read_manifest(tmp_path, MONTH, 1) == r1
    assert read_manifest(tmp_path, MONTH) == r2
    for d in r1.datasets:
        for fmt, digest in d.files.items():
            assert hashlib.sha256(dataset_path(tmp_path, MONTH, 1, d.name, fmt, d.major).read_bytes()).hexdigest() == digest
    assert [r["field_id"] for r in _jsonl(tmp_path, r2, "esg_signals")] == ["f2", "f3"]


def test_r3_keeps_r2_corrections(env, world, tmp_path):
    _build(env, world, tmp_path)
    world.withdraw("f1")
    _correct(env, world, tmp_path)
    world.restate("f2", 9.0)
    r3 = _correct(env, world, tmp_path)
    assert r3.revision == 3 and r3.supersedes == "2026-10.r2"
    assert [(c["event_type"], c["field_id"]) for c in r3.changes] == [("restated", "f2")]
    esg = {r["field_id"]: r for r in _jsonl(tmp_path, r3, "esg_signals")}
    assert set(esg) == {"f2", "f3"}
    assert esg["f2"]["value"] == 9.0 and esg["f2"]["fact_version"] == 2


def test_correction_copies_holdings_files(env, world, tmp_path):
    r1 = _build(env, world, tmp_path)
    _ingest(env, "index", "IX1", weights=(55, 45))  # an intake revision after r1
    world.withdraw("f1")
    r2 = _correct(env, world, tmp_path)
    for ds in ("index_holdings", "portfolio_holdings"):
        assert _hashes(r2)[(ds, 1)] == _hashes(r1)[(ds, 1)]
    assert _hashes(r2)[("esg_signals", 1)] != _hashes(r1)[("esg_signals", 1)]


def test_no_events_no_revision(env, world, tmp_path):
    assert _correct(env, world, tmp_path) is None  # nothing built yet
    _build(env, world, tmp_path)
    assert _correct(env, world, tmp_path) is None
    world.withdraw("f1")
    assert _correct(env, world, tmp_path).revision == 2
    assert _correct(env, world, tmp_path) is None  # no event newer than r2


def test_esg_signals_rows_keep_fact_id(env, world, tmp_path):
    m = _build(env, world, tmp_path)
    rows = _jsonl(tmp_path, m, "esg_signals")
    assert [(r["fact_id"], r["fact_version"], r["published_at"]) for r in rows] == [
        (f.fact_id, f.version, f.valid_from) for f in world.facts
    ]


def test_csv_and_jsonl_hold_the_same_rows(env, world, tmp_path):
    m = _build(env, world, tmp_path)
    for d in m.datasets:
        jl = _jsonl(tmp_path, m, d.name)
        text = dataset_path(tmp_path, MONTH, 1, d.name, "csv", 1).read_text()
        rows = list(csv.DictReader(io.StringIO(text)))
        assert len(rows) == len(jl) == d.rows > 0
        assert list(rows[0]) == schema.header(d.name)
        assert rows == [{k: "" if v is None else str(v) for k, v in r.items()} for r in jl]
    pf = _jsonl(tmp_path, m, "portfolio_holdings")
    assert pf[0]["portfolio_id"] == "PF1" and pf[0]["fx_rate_to_eur"] == 1.0 and pf[0]["source_file"] == "f.csv"


def test_old_major_built_alongside(env, world, tmp_path, monkeypatch):
    v1 = schema.SCHEMAS[1]
    v2 = {"version": "2.0", "retire_after": None, "datasets": {
        name: {**ds, "columns": [*ds["columns"], "extra"]} for name, ds in v1["datasets"].items()}}
    monkeypatch.setitem(schema.SCHEMAS, 2, v2)
    monkeypatch.setitem(v1, "retire_after", "2026-11")
    assert schema.live_majors("2026-10") == [1, 2] and schema.live_majors("2026-12") == [2]
    m = _build(env, world, tmp_path)
    assert {d.major for d in m.datasets} == {1, 2}
    for ds in schema.DATASETS:
        for major in (1, 2):
            for fmt in ("csv", "jsonl"):
                assert dataset_path(tmp_path, MONTH, 1, ds, fmt, major).exists()
    assert "extra" in _jsonl(tmp_path, m, "esg_signals", 2)[0]


def test_bad_month_or_revision_rejected(tmp_path):
    for month, rev in (("../x", 1), ("2026-13", 1), ("2026-10/..", 1), ("2026-10", 0)):
        with pytest.raises(ValueError):
            snapshot_dir(tmp_path, month, rev)
