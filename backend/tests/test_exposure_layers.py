import pytest

from arp.config import Settings
from arp.research.exposure_layers import (
    Edge,
    LayerParams,
    LayerSettingsError,
    compute_layers,
    layer_params,
    run_company_l1,
)
from arp.schemas.common import CompanyRef

DEFAULT = LayerParams(w1=0.45, w2=0.35, w3=0.2, decay=0.85, max_hops=2, pure_play_threshold=0.5)
F_RUN = [("A", "A", 0.60), ("B", "B", 0.25), ("C", "C", None)]
F_EDGES = [Edge("S1", "A", 0.40), Edge("S2", "S1", 0.50)]
F_NAMES = {"S1": "S1", "S2": "S2", "A": "A"}


def _by_key(rows):
    return {r.issuer_key: r for r in rows}


def test_fixture_f_order_and_values():
    rows = compute_layers(F_RUN, F_EDGES, F_NAMES, DEFAULT)
    assert [r.issuer_key for r in rows] == ["A", "B", "S1", "S2", "C"]
    r = _by_key(rows)
    a = r["A"]
    assert (a.name, a.in_run, a.l1, a.l2, a.l3) == ("A", True, 0.6, None, None)
    assert round(a.score, 4) == 0.27 and a.pure_play and a.status == "scored" and a.rank == 1 and a.l2_via is None
    assert round(r["B"].score, 4) == 0.1125 and not r["B"].pure_play and r["B"].rank == 2
    s1 = r["S1"]
    assert (s1.name, s1.in_run, s1.l1) == ("S1", False, None)
    assert round(s1.l2, 4) == 0.204 and round(s1.score, 4) == 0.0714 and s1.rank == 3 and s1.l2_via == ["S1", "A"]
    s2 = r["S2"]
    assert round(s2.l2, 4) == 0.0867 and round(s2.score, 4) == 0.0303 and s2.rank == 4 and s2.l2_via == ["S2", "S1", "A"]
    c = r["C"]
    assert (c.l1, c.l2, c.l3, c.score, c.status, c.rank, c.pure_play) == (None, None, None, None, "insufficient data", None, False)


def test_no_edges_lists_run_only():
    assert [r.issuer_key for r in compute_layers(F_RUN, [], {}, DEFAULT)] == ["A", "B", "C"]


def test_three_hop_path_ignored():
    rows = compute_layers(F_RUN, F_EDGES + [Edge("S3", "S2", 0.9)], F_NAMES, DEFAULT)
    assert "S3" not in _by_key(rows)


def test_max_hops_one():
    params = LayerParams(0.45, 0.35, 0.2, 0.85, 1, 0.5)
    assert [r.issuer_key for r in compute_layers(F_RUN, F_EDGES, F_NAMES, params)] == ["A", "B", "S1", "C"]


def test_two_anchors_sum():
    s1 = _by_key(compute_layers(F_RUN, F_EDGES + [Edge("S1", "B", 0.20)], F_NAMES, DEFAULT))["S1"]
    assert round(s1.l2, 4) == 0.2465 and round(s1.score, 4) == 0.0863 and s1.l2_via == ["S1", "A"]


def test_decay_per_hop():
    r = _by_key(compute_layers([("D", "D", 1.0)], [Edge("T1", "D", 1.0), Edge("T2", "T1", 1.0)], {}, DEFAULT))
    assert round(r["T1"].l2, 4) == 0.85 and round(r["T2"].l2, 4) == 0.7225


def test_l2_capped_at_one():
    edges = [Edge("T1", "D", 1.0), Edge("T2", "T1", 1.0), Edge("T1", "E", 1.0)]
    r = _by_key(compute_layers([("D", "D", 1.0), ("E", "E", 1.0)], edges, {}, DEFAULT))
    assert r["T1"].l2 == 1.0


def test_no_loop_back_to_self():
    r = _by_key(compute_layers([("A", "A", 0.6), ("B", "B", 0.25)], [Edge("A", "B", 0.4), Edge("B", "A", 0.4)], {}, DEFAULT))
    assert round(r["A"].l2, 4) == 0.085 and round(r["B"].l2, 4) == 0.204


def test_customer_without_l1_gives_no_l2():
    r = _by_key(compute_layers(F_RUN, F_EDGES + [Edge("C", "X", 0.5)], F_NAMES, DEFAULT))
    assert r["C"].l2 is None and r["C"].status == "insufficient data" and "X" not in r


def test_via_tie_takes_sorted_path():
    run = [("P", "P", 0.4), ("Q", "Q", 0.4)]
    s1 = _by_key(compute_layers(run, [Edge("S1", "Q", 0.5), Edge("S1", "P", 0.5)], {}, DEFAULT))["S1"]
    assert round(s1.l2, 4) == 0.34 and s1.l2_via == ["S1", "P"]


def test_equal_scores_rank_by_key():
    r = _by_key(compute_layers([("Q", "Q", 0.4), ("P", "P", 0.4)], [], {}, DEFAULT))
    assert (r["P"].rank, r["Q"].rank) == (1, 2) and round(r["P"].score, 4) == round(r["Q"].score, 4) == 0.18


def test_weights_from_params():
    params = LayerParams(0.5, 0.35, 0.15, 0.85, 2, 0.5)
    assert round(_by_key(compute_layers(F_RUN, F_EDGES, F_NAMES, params))["A"].score, 4) == 0.3


def test_pure_play_threshold():
    params = LayerParams(0.45, 0.35, 0.2, 0.85, 2, 0.2)
    assert _by_key(compute_layers(F_RUN, F_EDGES, F_NAMES, params))["B"].pure_play


def test_supplier_name_from_graph_and_run_name_wins():
    r = _by_key(compute_layers([("A", "Run name", 0.6)], [Edge("S1", "A", 0.4)], {"A": "Graph name", "S1": "Supplier"}, DEFAULT))
    assert r["A"].name == "Run name" and r["S1"].name == "Supplier"


def _match(company_id, verdict, value, source):
    return {
        "company_id": company_id,
        "verdict": verdict,
        "revenue_exposure": {"activity_id": "a", "revenue": {"value_pct": value, "source": source}},
    }


def test_l1_max_of_include_matches():
    refs = [CompanyRef(company_id="m", entity_id="11111111-1111-1111-1111-111111111111", name="M")]
    rows = [{"_key": "m", "company_matches": [_match("m", "include", 0.2, "catalogue"), _match("m", "include", 0.5, "extracted")]}]
    assert run_company_l1(refs, rows) == [("11111111-1111-1111-1111-111111111111", "M", 0.5)]
    r = compute_layers(run_company_l1(refs, rows), [], {}, DEFAULT)[0]
    assert round(r.score, 4) == 0.225


def test_l1_ignores_exclude_qualitative_and_missing():
    refs = [CompanyRef(company_id=c, name=c.upper()) for c in ("a", "c", "n")]
    rows = [
        {"_key": "a", "company_matches": [_match("a", "exclude", 0.6, "catalogue")]},
        {"_key": "c", "company_matches": [_match("c", "include", None, "qualitative"), _match("c", "include", 0.9, "qualitative")]},
        {"_key": "n", "company_matches": [{"company_id": "n", "verdict": "include", "revenue_exposure": None}]},
    ]
    assert [l1 for _key, _name, l1 in run_company_l1(refs, rows)] == [None, None, None]


def test_run_company_keys_deduplicated():
    ref = CompanyRef(company_id="a", entity_id="11111111-1111-1111-1111-111111111111", name="A")
    dup = CompanyRef(company_id="a2", entity_id="11111111-1111-1111-1111-111111111111", name="A again")
    assert [n for _k, n, _l in run_company_l1([ref, dup], [])] == ["A"]


def test_layer_params_defaults():
    assert layer_params(Settings()) == DEFAULT


@pytest.mark.parametrize(
    ("env", "value"),
    [
        ("ARP_THEME_LAYER_DECAY", "0"),
        ("ARP_THEME_LAYER_DECAY", "1.5"),
        ("ARP_THEME_LAYER_MAX_HOPS", "3"),
        ("ARP_THEME_LAYER_MAX_HOPS", "0"),
        ("ARP_THEME_LAYER_W1", "-0.1"),
        ("ARP_THEME_LAYER_W2", "-1"),
        ("ARP_THEME_LAYER_W3", "-0.01"),
    ],
)
def test_layer_params_rejects_bad_setting(monkeypatch, env, value):
    monkeypatch.setenv(env, value)
    with pytest.raises(LayerSettingsError, match=env):
        layer_params(Settings())
