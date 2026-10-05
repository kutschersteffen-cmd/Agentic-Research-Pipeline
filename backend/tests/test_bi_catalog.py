from __future__ import annotations

from arp.bi.catalog import VIEW_DATASETS, VIZ_ALLOWLIST


def test_every_dataset_has_metrics_and_descriptions():
    assert set(VIEW_DATASETS) == {
        "holdings",
        "holdings_history",
        "company_facts",
        "company_facts_pending",
        "run_records",
        "documents",
        "portfolio_climate_metrics",
        "alerts",
        "triggers",
        "company_profile",
    }
    for ds in VIEW_DATASETS.values():
        assert ds.description and ds.metrics
        assert all(d.strip() for d in ds.columns.values())
        assert all(m.description.strip() and m.expression.strip() for m in ds.metrics)


def test_company_facts_pending_shares_columns_with_company_facts():
    assert list(VIEW_DATASETS["company_facts_pending"].columns) == list(VIEW_DATASETS["company_facts"].columns)


def test_viz_allowlist_has_eight_known_types():
    assert len(VIZ_ALLOWLIST) == 8 and len(set(VIZ_ALLOWLIST)) == 8
    assert "table" in VIZ_ALLOWLIST and "pie" in VIZ_ALLOWLIST


def test_metric_names_unique_per_dataset():
    for ds in VIEW_DATASETS.values():
        names = [m.name for m in ds.metrics]
        assert len(names) == len(set(names))


def test_temporal_columns_exist_in_their_dataset():
    from arp.bi.catalog import TEMPORAL_COLUMNS

    assert set(TEMPORAL_COLUMNS) == set(VIEW_DATASETS)
    for ds, cols in TEMPORAL_COLUMNS.items():
        assert cols <= set(VIEW_DATASETS[ds].columns), ds


def test_holdings_history_mirrors_holdings():
    from arp.bi.catalog import TEMPORAL_COLUMNS

    h, hh = VIEW_DATASETS["holdings"], VIEW_DATASETS["holdings_history"]
    assert list(hh.columns) == list(h.columns)
    assert [m.name for m in hh.metrics] == [m.name for m in h.metrics]
    assert "as_of_date" in TEMPORAL_COLUMNS["holdings_history"]
