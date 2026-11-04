"""Migrated ICIO data gives the numbers recorded before the change (Baseline B, AC-18, AC-19, AC-20, AC-44)."""

import json
from pathlib import Path

import pytest

from arp.config import Settings
from arp.research.indirect_exposure.exposure import compute_indirect_exposure
from arp.research.indirect_exposure.factory import SAMPLE_DIR, resolve_indirect_exposure_model
from arp.research.indirect_exposure.migrate import convert_parts, icio_sectors
from arp.research.value_chain import links
from arp.research.value_chain.model import ValueChain
from arp.schemas.common import CompanyRef
from arp.schemas.value_chain import LinkRule

BASELINE = json.loads((Path(__file__).parent / "fixtures" / "icio_baseline.json").read_text())


def test_c1_weights_match_baseline():  # AC-18
    parts = convert_parts("split", [{"icio_code": "B07", "share": 0.4}, {"icio_code": "D_GEN_REN", "share": 0.6}])
    vc = ValueChain(SAMPLE_DIR, json.loads((SAMPLE_DIR / "manifest.json").read_text()))
    res = links.resolve_company(vc, CompanyRef(company_id="c1", name="c1"), LinkRule(kind="split", parts=parts, set_by="t", set_at="t"))
    weights = {vc._nodes[k].node_id: w for k, w in res.weights.items()}
    assert res.unresolved == []
    assert weights.keys() == BASELINE["c1_weights"].keys()
    for node_id, w in BASELINE["c1_weights"].items():
        assert weights[node_id] == pytest.approx(w, abs=1e-12), node_id


def test_c9_exposure_match_baseline():  # AC-19, AC-20, AC-44
    model = resolve_indirect_exposure_model(Settings(), use_sample=True)
    r = compute_indirect_exposure(
        "c9", "", model, set(icio_sectors("B07")), model.edition_label, country="DE", nace=("nace2", "24.44", "2")
    )
    assert r.upstream_exposure == pytest.approx(BASELINE["c9"]["upstream_exposure"], abs=1e-12)
    assert r.downstream_exposure == pytest.approx(BASELINE["c9"]["downstream_exposure"], abs=1e-12)
    assert (r.code_scheme, r.isic_code) == ("nace2", "24.44")
    assert r.critical_input is True is BASELINE["c9"]["critical_input"]
