"""Fixture barrier directory F-TA and benchmarks fixture BM, wired in through their settings."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from arp.config import get_settings
from arp.db import models as m
from arp.db.companies import resolve
from arp.db.documents import DocumentRegistry
from arp.db.fields import SchemaRegistry
from arp.db.observations import CitationIn, ObservationIn, queue_item, record
from arp.db.session import transaction
from arp.orchestration.review_queue import record_review_decision
from arp.presets.registry import install_preset
from arp.schemas.common import JobStatus, RunManifest
from arp.transition_alignment import benchmarks
from arp.transition_barrier import dataset

FIXTURES = Path(__file__).parent / "fixtures" / "transition_alignment"


def _reset() -> None:
    get_settings.cache_clear()
    dataset.reset_caches()
    benchmarks.reset_cache()


@pytest.fixture
def ta_dirs(tmp_path, monkeypatch):
    """F-TA and BM copied to tmp_path; yields (f_ta, bm)."""
    f_ta, bm = tmp_path / "f_ta", tmp_path / "bm"
    shutil.copytree(FIXTURES / "f_ta", f_ta)
    shutil.copytree(FIXTURES / "bm", bm)
    monkeypatch.setenv("ARP_TRANSITION_BARRIER_DATA_DIR", str(f_ta))
    monkeypatch.setenv("ARP_TRANSITION_ALIGNMENT_DATA_DIR", str(bm))
    _reset()
    yield f_ta, bm
    _reset()


def edit_bm(bm: Path, fn: Callable[[dict], object]) -> None:
    """Apply `fn` to the raw benchmarks file and write it back, without re-signing."""
    path = bm / benchmarks.BENCHMARKS_FILE
    raw = json.loads(path.read_text(encoding="utf-8"))
    fn(raw)
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --- Seeded companies, documents and default facts (spec "Fixtures"), for the Postgres API tests ---

FY24, FY25, FY26 = date(2024, 12, 31), date(2025, 12, 31), date(2026, 12, 31)
COMPANIES = {  # key: (name, ISIC code, fiscal year end)
    "C": ("Fixture Steel AG", "2410", "12-31"),
    "P": ("Fixture Power plc", "3510", None),
    "K": ("Fixture Cement SA", "2394", None),
    "Q": ("Fixture Foods SA", "1050", None),
    "N": ("Fixture Holdings Ltd", None, None),
}
DOCUMENTS = {  # doc_id: (company key, doc type, title)
    "P1": ("C", "transition_plan", "Fixture Steel Transition Plan 2025"),
    "P2": ("C", "annual_report", "Fixture Steel Annual Report 2025"),
    "P4": ("P", "annual_report", "Fixture Power Annual Report 2025"),
    "P5": ("Q", "annual_report", "Fixture Foods Report 2025"),
}
M = "EUR million"
DEFAULT_FACTS = [  # (company, field_id, period_end, value, unit, doc_id, page)
    ("C", "tc_capex_total", FY25, 1000, M, "P2", 44),
    ("C", "tc_lowcarbon_capex", FY25, 120, M, "P2", 45),
    ("C", "tc_lowcarbon_capex_share_pct", FY25, 12, "%", "P2", 45),
    ("C", "tc_carbon_intensive_capex", FY25, 300, M, "P2", 46),
    ("C", "green_capex_share_pct", FY25, 15, "%", "P2", 47),
    ("C", "tc_new_blast_furnace", FY25, False, None, "P2", 48),
    ("C", "tc_rnd_total", FY25, 50, M, "P2", 50),
    ("C", "tc_lowcarbon_rnd", FY25, 30, M, "P2", 50),
    ("C", "tc_lowcarbon_rnd_early", FY25, 15, M, "P2", 50),
    ("C", "tc_rnd_total", FY24, 40, M, "P2", 51),
    ("C", "tc_lowcarbon_rnd", FY24, 20, M, "P2", 51),
    ("C", "tc_lowcarbon_rnd_early", FY24, 12, M, "P2", 51),
    ("C", "tc_capex_total_planned", FY26, 1100, M, "P1", 18),
    ("C", "tc_lowcarbon_capex_share_pct_planned", FY26, 20, "%", "P1", 18),
    ("Q", "capex_total", FY25, 200, M, "P5", 8),
]


def field_version(s, field_id: str) -> int:
    return s.scalar(select(func.max(m.FieldDefinition.version)).where(m.FieldDefinition.field_id == field_id)) or 1


def observation(s, cid: UUID, field_id: str, period_end: date | None, value, unit: str | None, doc_id: str, page: int,
                **kw) -> ObservationIn:
    return ObservationIn(
        company_id=cid, field_id=field_id, field_version=field_version(s, field_id), source_kind=m.SourceKind.EXTRACTION,
        period_end=period_end, value=value, value_state=m.ValueState.FOUND, unit=unit,
        citations=[CitationIn(doc_id=doc_id, page=page)], **{"route": m.Route.REVIEW, **kw},
    )


def publish(pg: str, run_store, rows: list[tuple], **kw) -> None:
    """Records each (company id, field_id, period_end, value, unit, doc_id, page) for review, then approves it.
    `kw` goes to every ObservationIn (e.g. `basis`)."""
    run_id = f"seed-{uuid4().hex[:8]}"
    run_store.save_manifest(RunManifest(run_id=run_id, run_type="extraction", status=JobStatus.COMPLETED))
    with transaction(pg) as s:
        obs = [observation(s, *r, run_id=run_id, **kw) for r in rows]
        keys = []
        for o, oid in zip(obs, record(s, obs), strict=True):
            keys.append(f"{run_id}:{oid}")
            queue_item(s, run_id, keys[-1], {"item_key": keys[-1]}, company_id=o.company_id, observation_id=oid,
                       queued_at=datetime.now(UTC))
    for key in keys:
        record_review_decision(run_store, run_id, key, "approve", "owner", None)


def retire(pg: str, cid: UUID, *keys: tuple[str, date]) -> None:
    """Closes the current facts for (field_id, period_end) keys, so the company has no counted fact there."""
    with transaction(pg) as s:
        for field_id, period_end in keys:
            s.execute(update(m.CompanyFact).where(
                m.CompanyFact.company_id == cid, m.CompanyFact.field_id == field_id, m.CompanyFact.period_end == period_end,
                m.CompanyFact.valid_to.is_(None),
            ).values(valid_to=func.clock_timestamp()))


@pytest.fixture
def seed_defaults(pg, run_store) -> dict[str, UUID]:
    """Companies C, P, K, Q, N, documents P1, P2, P4, P5 and the default facts, approved. Returns key -> company id."""
    registry = SchemaRegistry(pg)
    install_preset("sch_transition_capex", registry)
    install_preset("sch_green_lowcarbon", registry)
    ids = {}
    with transaction(pg) as s:
        for key, (name, isic, fye) in COMPANIES.items():
            attrs = {k: v for k, v in {"isic_code": isic, "fiscal_year_end": fye}.items() if v}
            ids[key] = resolve(s, [(m.IdScheme.UNIVERSE, key.lower())], name=name, allow_create=True, attrs=attrs).company_id
    docs = DocumentRegistry(pg)
    for doc_id, (key, doc_type, title) in DOCUMENTS.items():
        docs.register_document(doc_id=doc_id, company_id=key.lower(), doc_type=doc_type, content_key=f"ck_{doc_id}",
                               title=title, local_path=None, source_url=None)
    publish(pg, run_store, [(ids[k], *rest) for k, *rest in DEFAULT_FACTS])
    return ids
