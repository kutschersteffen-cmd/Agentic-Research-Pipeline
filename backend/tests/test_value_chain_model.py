import threading

import pytest

from arp.research.value_chain.build import build_full
from arp.research.value_chain.model import NotBuilt, UnknownNode, _load, load_value_chain
from tests.value_chain_fixture import write_fixture_f

NOT_BUILT = "value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR"


@pytest.fixture(scope="module")
def vc(tmp_path_factory):
    d = tmp_path_factory.mktemp("vc")
    build_full(write_fixture_f(d), d / "out")
    return load_value_chain(d / "out")


def links(vc, node, side, **kw):
    return [(item.node.node_id, round(item.direct, 4), round(item.total, 4)) for item in vc.links(node, side, **kw)]


def ids(items):
    return [i.node.node_id for i in items]


def shape(item):
    return (item.node.node_id, round(item.coef, 4), round(item.chain, 4), [shape(c) for c in item.children])


def test_suppliers_total(vc):  # AC-3
    assert links(vc, "CN.2", "suppliers") == [
        ("CN.2", 0.2, 0.2696), ("CN.3", 0.1, 0.1572), ("DE.3", 0.1, 0.1448), ("DE.2", 0.0, 0.0336)]


def test_suppliers_exclude_own(vc):  # AC-4
    assert ids(vc.links("CN.2", "suppliers", exclude_own=True)) == ["CN.3", "DE.3", "DE.2"]


def test_customers_total(vc):  # AC-5
    assert links(vc, "DE.2", "customers") == [
        ("DE.3", 0.2, 0.279), ("CN.3", 0.1, 0.1289), ("DE.2", 0.1, 0.1266), ("CN.2", 0.0, 0.0336)]


def test_customers_exclude_own(vc):  # AC-6
    assert ids(vc.links("DE.2", "customers", exclude_own=True)) == ["DE.3", "CN.3", "CN.2"]


def test_limit_cuts_after_sorting(vc):
    assert ids(vc.links("CN.2", "suppliers", limit=2)) == ["CN.2", "CN.3"]


def test_intensities(vc):  # AC-7, AC-8, AC-8b
    n = vc.node("DE.3")
    assert n.sector == "Other business activities"
    assert (n.region, n.region_label, n.output_meur, n.goods) == ("DE", "DE", 200.0, False)
    assert (n.ghg_t_per_meur, n.energy_tj_per_meur, n.jobs_per_meur, n.va_share) == (0, 0, 10, 0.5)
    n = vc.node("DE.2")
    assert (round(n.ghg_t_per_meur, 4), round(n.energy_tj_per_meur, 4), round(n.jobs_per_meur, 4), round(n.va_share, 4)) == (5, 0.1, 10, 0.3)
    assert n.goods is True
    n = vc.node("CN.3")
    assert (round(n.ghg_t_per_meur, 4), round(n.jobs_per_meur, 4)) == (0.27, 10)


def test_tree_full(vc):  # AC-9
    assert shape(vc.tree("DE.3", depth=2, width=3, cutoff=0.01)) == (
        "DE.3", 1, 1, [
            ("CN.3", 0.1, 0.1, [("CN.2", 0.1, 0.01, []), ("DE.2", 0.1, 0.01, [])]),
            ("DE.2", 0.1, 0.1, [("DE.3", 0.1, 0.01, [])]),
        ])


@pytest.mark.parametrize(("kw", "want"), [
    ({"width": 1}, ["CN.3"]),  # AC-10
    ({"cutoff": 0.1}, ["CN.3", "DE.2"]),  # AC-11
    ({"cutoff": 0.11}, []),  # AC-12
    ({"goods_only": True}, ["DE.2"]),  # AC-13
    ({"cutoff": 0}, ["CN.3", "DE.2"]),  # AC-13b
])
def test_tree_filters(vc, kw, want):
    assert ids(vc.tree("DE.3", depth=1, **kw).children) == want


def fp(f):
    return (f.unit, round(f.total, 4), f.in_home_region and round(f.in_home_region, 4),
            [(k, round(v, 4)) for k, v in f.by_region], [(k, round(v, 4)) for k, v in f.by_sector])


def test_footprints(vc):  # AC-15 to AC-19
    f = vc.footprint("DE.3", "ghg", amount_meur=2)
    assert fp(f) == (
        "t CO₂e", 1.4955, 0.9328, [("DE", 1.395), ("CN", 0.1004)],
        [("Mining of copper ores and concentrates", 1.4268), ("Other business activities", 0.0687)])
    assert f.indicator == "ghg"
    assert [(k, round(v, 4)) for k, v in vc.footprint("DE.3", "ghg", 2, top=1).by_region] == [("DE", 1.395)]
    e = vc.footprint("DE.3", "energy", amount_meur=2)
    assert (e.unit, round(e.total, 4), round(e.in_home_region, 4)) == ("TJ", 0.0279, 1)
    assert e.by_region == [("DE", e.total)]  # CN contributes 0 and is left out
    j = vc.footprint("DE.3", "jobs", amount_meur=2)
    assert (j.unit, round(j.total, 4)) == ("people", 27.9004)


@pytest.mark.parametrize("node_id", ["DE.1", "DE.999", "DE.0", "abc"])
def test_unknown_and_zero_nodes(vc, node_id):  # AC-20
    with pytest.raises(UnknownNode) as e:
        vc.node(node_id)
    assert str(e.value) == f"unknown node '{node_id}'"
    with pytest.raises(UnknownNode):
        vc.links(node_id, "suppliers")


def test_search(vc):  # AC-21, AC-22, AC-22b
    assert vc.search("paddy") == []
    assert ids_of(vc.search("copper")) == ["CN.2", "DE.2"]
    assert ids_of(vc.search("de")) == ["DE.2", "DE.3"]
    assert ids_of(vc.search("  COPPER ")) == ["CN.2", "DE.2"]
    assert ids_of(vc.search("copper", limit=1)) == ["CN.2"]


def ids_of(nodes):
    return [n.node_id for n in nodes]


def test_direct_order(vc):  # AC-22c, AC-22d, AC-22f
    sup = vc.links("DE.3", "suppliers", order="direct")
    assert ids(sup) == ["CN.3", "DE.2", "DE.3"]
    assert [round(i.direct, 4) for i in sup] == [0.1, 0.1, 0.1]
    cus = vc.links("DE.3", "customers", order="direct")
    assert ids(cus) == ["DE.3", "CN.2", "DE.2"]
    assert [round(i.direct, 4) for i in cus] == [0.1, 0.05, 0.05]
    assert ids(vc.links("DE.3", "suppliers")) == ["DE.2", "DE.3", "CN.3", "CN.2"]


def test_caveat(vc):
    assert vc.caveat == (
        "EXIOBASE 3.11.2 · 2022 · basic prices, M EUR · now-cast years are estimates · capital goods not included in flows")


def test_not_built(tmp_path):
    for d in (None, tmp_path):
        with pytest.raises(NotBuilt) as e:
            load_value_chain(d)
        assert str(e.value) == NOT_BUILT


def test_reload_after_rebuild(tmp_path):
    src = write_fixture_f(tmp_path)
    build_full(src, tmp_path / "out")
    assert load_value_chain(tmp_path / "out").manifest["edition"] == "exiobase-IOT_2022_ixi"
    build_full(src, tmp_path / "out", label="second")
    assert load_value_chain(tmp_path / "out").manifest["edition"] == "second"


def test_concurrent_cold_loads_share_one_object(tmp_path):
    build_full(write_fixture_f(tmp_path), tmp_path / "out")
    _load.cache_clear()
    found, barrier = [], threading.Barrier(2)

    def call():
        barrier.wait()
        found.append(load_value_chain(tmp_path / "out"))

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(found) == 2 and found[0] is found[1]


def test_rowl_labels(vc):
    from arp.research.value_chain.model import region_label

    assert [region_label(c) for c in ("WA", "WE", "WF", "WL", "WM", "DE")] == [
        "RoW Asia-Pacific", "RoW Europe", "RoW Africa", "RoW Americas", "RoW Middle East", "DE"]
