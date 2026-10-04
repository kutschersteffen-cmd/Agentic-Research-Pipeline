"""The frozen monthly snapshot (E77): holdings and published ESG signals as of a month end, written
once to `root/snapshots/{month}/r{revision}/` as `{dataset}.v{major}.{csv|jsonl}` plus `manifest.json`.
The manifest is written last and freezes the revision; a correction is a new revision."""

from __future__ import annotations

import calendar
import csv
import hashlib
import io
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path

from arp import holdings
from arp.publish.facts import Fact, FactEvent, fact_key, ts_now
from arp.publish.reader import as_of_bound
from arp.snapshots import schema
from arp.snapshots.schema import DatasetEntry, SnapshotManifest
from arp.storage.atomic_io import atomic_write_bytes
from arp.storage.locks import KeyedLock

_MONTH_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
_REV_RE = re.compile(r"r([1-9]\d*)")
CORRECTION_EVENTS = {"restated", "withdrawn", "restored"}
HOLDINGS = {"index_holdings": "index", "portfolio_holdings": "portfolio"}
FORMATS = ("csv", "jsonl")
_MONTH_LOCKS = KeyedLock(lock_path=lambda month_dir: Path(month_dir) / ".lock")


class SnapshotFrozen(RuntimeError):
    """The revision already has a manifest."""


def _month(month: str) -> str:
    if not isinstance(month, str) or not _MONTH_RE.fullmatch(month):
        raise ValueError(f"bad month: {month!r}")
    return month


def month_of(as_of: str) -> str:
    return _month(date.fromisoformat(as_of).isoformat()[:7])


def month_end(month: str) -> str:
    y, m = map(int, _month(month).split("-"))
    return date(y, m, calendar.monthrange(y, m)[1]).isoformat()


def snapshot_dir(root: Path, month: str, revision: int) -> Path:
    if type(revision) is not int or revision < 1:
        raise ValueError(f"bad revision: {revision!r}")
    return Path(root) / "snapshots" / _month(month) / f"r{revision}"


def dataset_path(root: Path, month: str, revision: int, dataset: str, fmt: str, major: int) -> Path:
    if dataset not in schema.DATASETS or fmt not in FORMATS or type(major) is not int:
        raise ValueError(f"bad dataset file: {dataset!r} {fmt!r} v{major!r}")
    return snapshot_dir(root, month, revision) / f"{dataset}.v{major}.{fmt}"


def _sorted(rows: list[dict], dataset: str) -> list[dict]:
    key = schema.SCHEMAS[schema.CURRENT_MAJOR]["datasets"][dataset]["key"]
    return sorted(rows, key=lambda r: tuple("" if r[c] is None else str(r[c]) for c in key))


def dataset_rows(as_of: str, *, portfolio_store, facts: list[Fact]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for dataset, kind in HOLDINGS.items():
        rows = []
        for holder in portfolio_store.list_holders():
            if holder.kind != kind:
                continue
            for h in holdings.load(portfolio_store, kind, holder.holder_id, as_of):
                rows.append({
                    f"{kind}_id": holder.holder_id, "issuer_key": h.issuer_key, "isin": h.isin, "as_of": h.as_of_date,
                    "issuer_scheme": h.issuer_scheme, "weight": h.weight_pct, "shares": h.shares,
                    "free_float": h.free_float, "price": h.price, "currency": h.currency, "calibration_version": None,
                    "market_value": h.market_value, "fx_rate_to_eur": h.fx_rate_to_eur,
                    "source_file": h.source_ref if h.source == "file" else None,
                })
        out[dataset] = _sorted(rows, dataset)
    out["esg_signals"] = _sorted([{
        "issuer_key": f.issuer_key, "field_id": f.field_id, "period_end": f.period_end, "basis": f.basis,
        "issuer_scheme": f.issuer_scheme, "value": f.value, "canonical_unit": f.canonical_unit, "state": f.state,
        "fact_id": f.fact_id, "fact_version": f.version, "release_id": f.release_id, "published_at": f.valid_from,
        "restated": f.restated,
    } for f in facts], "esg_signals")
    return out


def render(dataset: str, rows: list[dict], major: int) -> tuple[bytes, bytes]:
    cols = schema.header(dataset, major)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    w.writerows(["" if row.get(c) is None else row.get(c) for c in cols] for row in rows)
    jsonl = "".join(json.dumps({c: row.get(c) for c in cols}, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    return buf.getvalue().encode(), jsonl.encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_snapshot(
    as_of: str,
    *,
    root: Path,
    portfolio_store,
    facts_as_of: Callable[[str], list[Fact]],
    revision: int = 1,
    supersedes: str | None = None,
    changes: Iterable[dict] = (),
    majors: list[int] | None = None,
    holdings_from: int | None = None,
    cutoff: str | None = None,
    event_id_cutoff: int | None = None,
) -> SnapshotManifest:
    """`majors`: defaults to the month's live majors. `holdings_from`: a revision of the same month whose
    holdings files are copied byte for byte. `cutoff`: the time facts and events were read up to (now when
    None); it must be after the month end. One build per month at a time (a file lock on the month dir)."""
    month = month_of(as_of)
    if as_of != month_end(month):
        raise ValueError(f"as_of must be the month end {month_end(month)}, got {as_of!r}")
    out = snapshot_dir(root, month, revision)
    with _MONTH_LOCKS.acquire(str(out.parent)):
        return _build(as_of, month, revision, out, root, portfolio_store, facts_as_of, supersedes, changes,
                      schema.live_majors(month) if majors is None else majors, holdings_from, cutoff, event_id_cutoff)


def _build(as_of, month, revision, out, root, portfolio_store, facts_as_of, supersedes, changes, majors, holdings_from,
           cutoff, event_id_cutoff):
    snapshot_id = f"{month}.r{revision}"
    if (out / "manifest.json").exists():
        raise SnapshotFrozen(f"{snapshot_id} is frozen")
    cutoff = cutoff or ts_now()
    if cutoff <= as_of_bound(as_of):
        raise ValueError(f"{month} has not ended")
    rows = dataset_rows(as_of, portfolio_store=portfolio_store, facts=facts_as_of(as_of))
    entries = []
    for major in majors:
        for dataset in schema.DATASETS:
            if holdings_from is not None and dataset in HOLDINGS:
                data = tuple(dataset_path(root, month, holdings_from, dataset, f, major).read_bytes() for f in FORMATS)
            else:
                data = render(dataset, rows[dataset], major)
            files = {}
            for fmt, blob in zip(FORMATS, data, strict=True):
                path = dataset_path(root, month, revision, dataset, fmt, major)
                atomic_write_bytes(path, blob)
                if _sha(path.read_bytes()) != _sha(blob):
                    raise RuntimeError(f"{path} does not match what was written")
                files[fmt] = _sha(blob)
            entries.append(DatasetEntry(name=dataset, major=major, schema_version=schema.SCHEMAS[major]["version"],
                                        rows=data[1].count(b"\n"), files=files))
    manifest = SnapshotManifest(
        snapshot_id=snapshot_id, month=month, revision=revision, as_of=as_of, frozen_at=ts_now(), cutoff=cutoff,
        event_id_cutoff=event_id_cutoff,
        schema_version=schema.SCHEMAS[schema.CURRENT_MAJOR]["version"], datasets=entries,
        supersedes=supersedes, changes=list(changes),
    )
    _freeze(out / "manifest.json", manifest)
    return manifest


def _freeze(path: Path, manifest: SnapshotManifest) -> None:
    """Writes the manifest whole and never over an existing one (`os.link` fails if the target exists)."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(manifest.model_dump_json(indent=2).encode())
        os.link(tmp, path)
    except FileExistsError:
        raise SnapshotFrozen(f"{manifest.snapshot_id} is frozen") from None
    finally:
        os.unlink(tmp)


def _revisions(root: Path, month: str) -> list[int]:
    d = Path(root) / "snapshots" / _month(month)
    if not d.is_dir():
        return []
    return sorted(int(m.group(1)) for p in d.iterdir() if p.is_dir() and (m := _REV_RE.fullmatch(p.name)))


def read_manifest(root: Path, month: str, revision: int | None = None) -> SnapshotManifest | None:
    """One revision's manifest, or with `revision=None` the latest frozen revision's."""
    revs = [revision] if revision is not None else reversed(_revisions(root, month))
    for rev in revs:
        path = snapshot_dir(root, month, rev) / "manifest.json"
        if path.exists():
            return SnapshotManifest.model_validate_json(path.read_bytes())
    return None


def list_months(root: Path) -> list[dict]:
    d = Path(root) / "snapshots"
    months = sorted(p.name for p in d.iterdir() if p.is_dir() and _MONTH_RE.fullmatch(p.name)) if d.is_dir() else []
    out = []
    for month in months:
        revs = _revisions(root, month)
        if not revs:
            continue
        frozen = (snapshot_dir(root, month, revs[-1]) / "manifest.json").exists()
        out.append({"month": month, "latest_revision": revs[-1], "snapshot_id": f"{month}.r{revs[-1]}",
                    "status": "frozen" if frozen else "incomplete"})
    return out


def build_correction(
    month: str,
    *,
    root: Path,
    portfolio_store,
    facts_as_of: Callable[[str], list[Fact]],
    events_since: Callable[[str], list[FactEvent]],
    now: str | None = None,
) -> SnapshotManifest | None:
    """A new revision when a fact visible at month end was restated, withdrawn or restored after the latest
    revision's cut-off (for r1, after month end, since r1 reflects month end). ESG rows carry every such
    correction since month end; facts first published after month end never enter. The latest revision is
    superseded by events with an id above its `event_id_cutoff` (event ids follow commit order; a timestamp is
    taken before commit, so a slow commit can land behind a time watermark). Events are read once by time
    (`at` after month end, the same stamps that decide what was visible at month end), then current facts after
    that read, so every event read is reflected; the highest id read is stored for the next correction.
    The majors and holdings files are those of the latest revision."""
    latest = read_manifest(root, month)
    if latest is None:
        return None
    end = month_end(month)
    bound = as_of_bound(end)
    base_facts = facts_as_of(bound)
    base = {fact_key(f) for f in base_facts}
    events = events_since(bound)
    cutoff = now or ts_now()  # after the event read: every event read is stamped before it
    max_id = max([e.event_id or 0 for e in events] + [latest.event_id_cutoff or 0])
    since_end = [e for e in events if e.event_type in CORRECTION_EVENTS
                 and (e.issuer_key, e.field_id, e.period_end, e.basis) in base]
    if latest.revision == 1:
        new = since_end
    elif latest.event_id_cutoff is not None:
        new = [e for e in since_end if e.event_id > latest.event_id_cutoff]
    else:  # a manifest from before event ids were stored
        new = [e for e in since_end if e.at > (latest.cutoff or latest.frozen_at)]
    if not new:
        return None
    keys = {(e.issuer_key, e.field_id, e.period_end, e.basis) for e in since_end}
    current = {fact_key(f): f for f in facts_as_of(cutoff)}
    corrected = [f for f in base_facts if fact_key(f) not in keys] + [current[k] for k in keys if k in current]
    return build_snapshot(
        end, root=root, portfolio_store=portfolio_store, facts_as_of=lambda _: corrected, cutoff=cutoff,
        event_id_cutoff=max_id,
        revision=latest.revision + 1, supersedes=latest.snapshot_id, holdings_from=latest.revision,
        majors=sorted({d.major for d in latest.datasets}),
        changes=[e.model_dump(include={"event_type", "fact_id", "issuer_key", "field_id", "period_end", "basis", "at"})
                 for e in new],
    )
