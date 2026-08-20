import pytest

from arp.storage.portfolio_store import PortfolioStore
from arp.storage.run_store import RunStore
from arp.storage.safe_path import UnsafeIdentifierError, safe_filename, safe_id


@pytest.mark.parametrize("value", ["AAPL", "co_1", "run_ab12cd34ef56", "2026-01-01", "climate_evic_eur_m", "a"])
def test_safe_id_accepts_normal_ids(value):
    assert safe_id(value) == value


@pytest.mark.parametrize(
    "value",
    ["..", "../../etc/cron.d/x", "a/../../b", "/etc/passwd", "..\\..\\windows", "", "."],
)
def test_safe_id_rejects_traversal(value):
    with pytest.raises(UnsafeIdentifierError):
        safe_id(value)


@pytest.mark.parametrize("value", ["report.pdf", "10-K_2026.txt"])
def test_safe_filename_accepts_plain_names(value):
    assert safe_filename(value) == value


@pytest.mark.parametrize("value", ["../../etc/cron.d/x", "/etc/cron.d/x", "a/b.pdf", "..", ".", None, ""])
def test_safe_filename_rejects_traversal(value):
    with pytest.raises(UnsafeIdentifierError):
        safe_filename(value)


def test_run_store_rejects_traversal_run_id(tmp_path):
    store = RunStore(tmp_path / "runs")
    with pytest.raises(UnsafeIdentifierError):
        store.run_dir("../outside")
    assert not (tmp_path / "outside").exists()


def test_portfolio_store_rejects_traversal_portfolio_id(tmp_path):
    store = PortfolioStore(tmp_path / "portfolios")
    with pytest.raises(UnsafeIdentifierError):
        store.list_snapshot_dates("../secret")
