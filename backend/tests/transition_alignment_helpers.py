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

from arp.api.auth import current_user
from arp.api.main import app
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
from tests.transition_barrier_helpers import A_ANALYST, A_APPROVER, derive, enter_fact, pdf_with

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
AS_OF = date(2026, 3, 31)
DOCUMENTS = {  # doc_id: (company key, doc type, title, as-of)
    "P1": ("C", "transition_plan", "Fixture Steel Transition Plan 2025", AS_OF),
    "P2": ("C", "annual_report", "Fixture Steel Annual Report 2025", AS_OF),
    "P3": ("C", "transition_plan", "Fixture Steel Transition Plan 2023", date(2024, 3, 31)),
    "P4": ("P", "annual_report", "Fixture Power Annual Report 2025", AS_OF),
    "P5": ("Q", "annual_report", "Fixture Foods Report 2025", AS_OF),
    "P6": ("C", "transition_plan", "Fixture Steel Transition Plan 2025 (revised)", AS_OF),
    "P7": ("P", "transition_plan", "Fixture Power Transition Plan 2025", AS_OF),
    "P8": ("K", "transition_plan", "Fixture Cement Report 2025", AS_OF),  # a plan, so K1 counts (P2)
    "P9": ("H", "annual_report", "Fixture Trucks AB Annual Report 2025", AS_OF),
    "P10": ("X", "annual_report", "Fixture Chemicals NV Annual Report 2025", AS_OF),
}
ON_REQUEST = ("P3", "P6", "P7", "P8", "P9", "P10")  # registered only when a test asks (register_documents)
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
    ("C", "tp_h_scope1_emissions", FY25, 17_500_000, "tCO2e", "P2", 52),
    ("C", "tp_h_scope2_emissions", FY25, 500_000, "tCO2e", "P2", 52),
    ("C", "tp_h_scope1_emissions", date(2023, 12, 31), 18_000_000, "tCO2e", "P2", 53),
    ("C", "tp_h_scope2_emissions", date(2023, 12, 31), 500_000, "tCO2e", "P2", 53),
]
NET_ZERO, OFFSETS = "tp_a_ambition_3", "tp_a_offsetting_13"  # A_ambition_3, A_offsetting_13 (transition_plan_indicators)
INDICATOR_FACTS = [  # (company, field_id, period_end, value, unit, doc_id, page, quote); K's only on request
    ("C", NET_ZERO, None, True, None, "P1", 25, "We aim to reach net zero across our operations by 2050."),
    ("C", OFFSETS, None, False, None, "P1", 26, "We will use carbon credits to help meet our 2030 target."),
]


def publish_k_net_zero(pg: str, run_store, ids: dict[str, UUID]) -> None:
    """K's A_ambition_3 Yes, on its report P8."""
    register_documents(pg, "P8")
    publish(pg, run_store, [(ids["K"], NET_ZERO, None, True, None, "P8", 2)])


KPI_COMPANIES = {  # seeded only by seed_kpi_companies (ruling D4), so COMPANIES and sector listings stay as they were
    "H": ("Fixture Trucks AB", "2910"),
    "X": ("Fixture Chemicals NV", "2011"),
    "F": ("Fixture Freight GmbH", "4923"),
}
K_ALT_FUEL_QUOTE = "Alternative fuels supplied 14% of kiln heat in 2025."
KPI_FACTS = {  # name: [(company, field_id, period_end, value, unit, doc_id, page[, quote])]; each only on request
    "K": [("K", "tc_alt_fuel_share_pct", FY25, 14, "%", "P8", 12, K_ALT_FUEL_QUOTE)],
    "K24": [("K", "tc_alt_fuel_share_pct", FY24, 10, "%", "P8", 13)],  # AC-196 only
    "H": [("H", "tc_zev_sales_share_pct", FY25, 4, "%", "P9", 7)],
    "X": [("X", "tc_nh3_electrolytic_pct", FY25, 3, "%", "P10", 20),
          ("X", "tc_electrolysis_lc_power_pct", FY25, 80, "%", "P10", 21)],
}


def seed_kpi_companies(pg: str) -> dict[str, UUID]:
    """Companies H, X and F, and documents P9 and P10. Returns key -> company id."""
    with transaction(pg) as s:
        ids = {key: resolve(s, [(m.IdScheme.UNIVERSE, key.lower())], name=name, allow_create=True,
                            attrs={"isic_code": isic}).company_id for key, (name, isic) in KPI_COMPANIES.items()}
    register_documents(pg, "P9", "P10")
    return ids


def publish_kpi(pg: str, run_store, ids: dict[str, UUID], name: str, **kw) -> None:
    """Publishes the delivery-KPI facts `name` of KPI_FACTS (registering K's P8); `kw` goes to every observation."""
    rows = KPI_FACTS[name]
    if rows[0][0] == "K":
        register_documents(pg, "P8")
    publish(pg, run_store, [(ids[k], *rest) for k, *rest in rows], **kw)


EU, US, CN = "European Union", "United States", "China"
# action: (doc_id, text page, [(field_id, value, unit, page)]); facts share basis `action:<doc>:<page>:1` (P3)
ACTIONS = {
    "A1": ("P1", 12, [
        ("ta_action_text", "We will commission a 2 Mt hydrogen-based DRI plant in Sweden by 2028.", None, 12),
        ("ta_action_id", "steel.h2_dri", None, 12), ("ta_action_status", "planned", None, 12),
        ("ta_action_year", 2028, None, 12), ("ta_action_region", EU, None, 12),
        ("ta_action_capex_needed", 1500, M, 13), ("ta_action_capex_allocated", 600, M, 13),
        ("ta_action_ghg_saving", 3.5, "MtCO2e/yr", 14),
    ]),
    "A2": ("P1", 15, [
        ("ta_action_text", "Our electric arc furnace in Ohio has run on scrap since 2022.", None, 15),
        ("ta_action_id", "steel.scrap_eaf", None, 15), ("ta_action_status", "implemented", None, 15),
        ("ta_action_year", 2022, None, 15), ("ta_action_region", US, None, 15),
    ]),
    "A3": ("P1", 16, [
        ("ta_action_text", "We are studying carbon capture at our Tianjin plant.", None, 16),
        ("ta_action_id", "steel.ccus", None, 16), ("ta_action_status", "planned", None, 16),
        ("ta_action_region", CN, None, 16),
    ]),
    "K1": ("P8", 9, [
        ("ta_action_text", "We will raise alternative fuels to 30% of kiln heat by 2030.", None, 9),
        ("ta_action_id", "cement.alt_fuels", None, 9), ("ta_action_status", "planned", None, 9),
        ("ta_action_year", 2030, None, 9), ("ta_action_region", EU, None, 9),
    ]),
    "A6": ("P3", 5, [
        ("ta_action_text", "We will build a coke oven gas recovery unit by 2025.", None, 5),
        ("ta_action_id", "other", None, 5), ("ta_action_status", "planned", None, 5),
        ("ta_action_year", 2025, None, 5), ("ta_action_region", EU, None, 5),
    ]),
    "A7": ("P6", 4, [
        ("ta_action_text", "We will build a second DRI plant in Sweden by 2030.", None, 4),
        ("ta_action_id", "steel.h2_dri", None, 4), ("ta_action_status", "planned", None, 4),
        ("ta_action_year", 2030, None, 4), ("ta_action_region", EU, None, 4),
    ]),
}


def _target(page, pct, year, set_year):
    return [("ta_target_scope", "S1+2", None, page), ("ta_target_pct", pct, "%", page), ("ta_target_year", year, None, page),
            ("ta_target_base_year", 2019, None, page), ("ta_target_base_emissions", 20, "MtCO2e", page),
            ("ta_target_set_year", set_year, None, page)]


def _phaseout(page, activity, share, year):
    return [("ta_phaseout_activity", activity, None, page), ("ta_phaseout_share_pct", share, "%", page),
            ("ta_phaseout_year", year, None, page), ("ta_phaseout_method", "closure", None, page)]


# target / phase-out: (company, doc_id, basis, [(field_id, value, unit, page)]); O2 is published only on request
ITEMS = {
    "T1": ("C", "P1", "target:P1:22:1", _target(22, 30, 2030, 2021)),
    "T0": ("C", "P1", "target:P1:23:1", _target(23, 10, 2023, 2020)),
    "O1": ("C", "P1", "phaseout:P1:24:1", _phaseout(24, "blast furnace steelmaking", 50, 2035)),
    "O2": ("P", "P7", "phaseout:P7:4:1", _phaseout(4, "coal power", 100, 2038)),
}


def publish_item(pg: str, run_store, ids: dict[str, UUID], name: str, **values) -> None:
    """Publishes a target or phase-out; `values` replace field values by field_id."""
    key, doc_id, basis, rows = ITEMS[name]
    publish(pg, run_store, [(ids[key], fid, None, values.get(fid, v), unit, doc_id, page) for fid, v, unit, page in rows],
            basis=basis)


def retire_item(pg: str, cid: UUID, name: str, *field_ids: str) -> None:
    """Closes the current facts of a target or phase-out (only `field_ids`, if given)."""
    _, _, basis, rows = ITEMS[name]
    with transaction(pg) as s:
        s.execute(update(m.CompanyFact).where(
            m.CompanyFact.company_id == cid, m.CompanyFact.basis == basis, m.CompanyFact.valid_to.is_(None),
            m.CompanyFact.field_id.in_(field_ids or [r[0] for r in rows]),
        ).values(valid_to=func.clock_timestamp()))


def use_bm_s(bm: Path) -> None:
    """BM-S: BM plus the scenario prices, in place of BM in the `ta_dirs` benchmarks directory."""
    shutil.copy(FIXTURES / "bm_s" / benchmarks.BENCHMARKS_FILE, bm / benchmarks.BENCHMARKS_FILE)
    benchmarks.reset_cache()


def action_basis(name: str) -> str:
    doc_id, page, _ = ACTIONS[name]
    return f"action:{doc_id}:{page}:1"


def publish_action(pg: str, run_store, cid: UUID, name: str) -> None:
    doc_id, _, rows = ACTIONS[name]
    publish(pg, run_store, [(cid, fid, None, v, unit, doc_id, page) for fid, v, unit, page in rows], basis=action_basis(name))


def register_documents(pg: str, *doc_ids: str) -> None:
    """Registers the documents (in order, so a later one is uploaded later) with their as-of dates."""
    docs = DocumentRegistry(pg)
    for doc_id in doc_ids:
        key, doc_type, title, as_of = DOCUMENTS[doc_id]
        docs.register_document(doc_id=doc_id, company_id=key.lower(), doc_type=doc_type, content_key=f"ck_{doc_id}",
                               title=title, local_path=None, source_url=None)
        with transaction(pg) as s:
            s.execute(update(m.Document).where(m.Document.doc_id == doc_id).values(published_at=as_of))


def field_version(s, field_id: str) -> int:
    return s.scalar(select(func.max(m.FieldDefinition.version)).where(m.FieldDefinition.field_id == field_id)) or 1


def observation(s, cid: UUID, field_id: str, period_end: date | None, value, unit: str | None, doc_id: str, page: int,
                quote: str | None = None, **kw) -> ObservationIn:
    return ObservationIn(
        company_id=cid, field_id=field_id, field_version=field_version(s, field_id), source_kind=m.SourceKind.EXTRACTION,
        period_end=period_end, value=value, value_state=m.ValueState.FOUND, unit=unit,
        citations=[CitationIn(doc_id=doc_id, page=page, quote=quote)], **{"route": m.Route.REVIEW, **kw},
    )


def publish(pg: str, run_store, rows: list[tuple], **kw) -> None:
    """Records each (company id, field_id, period_end, value, unit, doc_id, page[, quote]) for review, then approves it.
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
    """Companies C, P, K, Q, N, documents P1, P2, P4, P5 and the default facts, approved: capex, emissions, A1-A3,
    operating regions, both assumptions, T1, T0, O1 and C's two indicator facts. Returns key -> company id."""
    registry = SchemaRegistry(pg)
    install_preset("sch_transition_capex", registry)
    install_preset("sch_transition_delivery_kpis", registry)
    install_preset("sch_green_lowcarbon", registry)
    install_preset("sch_transition_plan_actions", registry)
    install_preset("transition_plan_indicators", registry)
    ids = {}
    with transaction(pg) as s:
        for key, (name, isic, fye) in COMPANIES.items():
            attrs = {k: v for k, v in {"isic_code": isic, "fiscal_year_end": fye}.items() if v}
            ids[key] = resolve(s, [(m.IdScheme.UNIVERSE, key.lower())], name=name, allow_create=True, attrs=attrs).company_id
    register_documents(pg, *(d for d in DOCUMENTS if d not in ON_REQUEST))
    publish(pg, run_store, [(ids[k], *rest) for k, *rest in DEFAULT_FACTS])
    c = ids["C"]
    publish(pg, run_store, [(c, f"ta_operates_{r}", None, True, None, "P2", 3) for r in ("eu", "us", "cn")])
    publish(pg, run_store, [(c, "ta_assumed_carbon_price", date(2030, 12, 31), 90, "EUR/tCO2", "P1", 20)],
            basis=f"region:{EU}")
    publish(pg, run_store, [(c, "ta_assumed_h2_cost", None, 3, "USD/kg H2", "P1", 21)], basis="region:any")
    for name in ("A1", "A2", "A3"):
        publish_action(pg, run_store, c, name)
    for name in ("T1", "T0", "O1"):
        publish_item(pg, run_store, ids, name)
    publish(pg, run_store, [(ids[k], *rest) for k, *rest in INDICATOR_FACTS])
    return ids


# --- F-TA ratification through the barrier API (spec "Fixtures": STL-R1 EU H, STL-T1 EU M) ---

H2_QUOTE = "Renewable hydrogen cost was USD 6/kg H2."


def _decide(client, who, run_id: str, key: str) -> None:
    app.dependency_overrides[current_user] = lambda: who
    etag = client.get(f"/api/review/runs/{run_id}/items/{key}/context").json()["etag"]
    r = client.post(f"/api/review/runs/{run_id}/items/{key}/decision",
                    json={"decision": "approve", "reason_code": "confirmed", "context_etag": etag})
    assert r.status_code == 200, r.text


def ratify_fta(client) -> None:
    """Enters D1 price 72 (p. 12), applies and levy Yes for STL-R1 EU and D5 h2_cost 6 (p. 7) for STL-T1 EU, derives
    both cells, then an analyst and an approver approve each (as test_tb_ratings.ratify_change)."""
    r1, t1 = (f"/api/transition-barrier/cells/{code}/{EU}" for code in ("STL-R1", "STL-T1"))
    entries = [
        enter_fact(client, "price", 72, "D1", 12, cell=r1),
        enter_fact(client, "applies", True, "D1", 4, cell=r1),
        enter_fact(client, "levy", True, "D2", 3, cell=r1),
        enter_fact(client, "h2_cost", 6, "D1", 7, cell=t1, title="Hydrogen Cost Review 2026", quote=H2_QUOTE,
                   pdf=pdf_with([None] * 6 + [H2_QUOTE]), as_of="2026-06-30", filename="D5.pdf"),
    ]
    assert [e.status_code for e in entries] == [201] * 4, [e.text for e in entries]
    app.dependency_overrides[current_user] = lambda: A_ANALYST
    run_id = derive(client, [("STL-R1", EU), ("STL-T1", EU)])
    for who in (A_ANALYST, A_APPROVER):
        for code in ("STL-R1", "STL-T1"):
            _decide(client, who, run_id, f"{code}:{EU}")
