from arp.portfolio.mock_data import generate_demo_dataset
from arp.storage.portfolio_store import PortfolioStore


async def test_seeding_twice_does_not_duplicate_news(tmp_path):
    store = PortfolioStore(tmp_path)

    first = await generate_demo_dataset(store)
    second = await generate_demo_dataset(store)

    assert first.news_items > 0
    assert second.news_items == 0  # nothing new to ingest the second time
    assert len(store.list_news()) == first.news_items


async def test_seeding_twice_overwrites_snapshots_not_duplicates(tmp_path):
    store = PortfolioStore(tmp_path)

    await generate_demo_dataset(store)
    await generate_demo_dataset(store)

    portfolio = store.list_portfolios()[0]
    date = store.latest_snapshot_date(portfolio.portfolio_id)
    holdings = store.load_snapshot(portfolio.portfolio_id, date)
    security_ids = [h.security_id for h in holdings]
    assert len(security_ids) == len(set(security_ids))


async def test_seeding_for_today_ends_at_the_last_month_end(tmp_path):
    """Fixed dates aged: three months on, a fresh seed opened with "6 of 7 feeds are behind" and the monthly
    run answered "blocked". Seeded for a date, the newest snapshot is the month end the feeds page and the
    monthly run expect; without one, the fixed dates stay (anything built on them is reproducible)."""
    from datetime import date

    from arp.portfolio.mock_data import SNAPSHOT_DATES, snapshot_dates

    assert snapshot_dates(date(2026, 11, 11)) == ["2026-01-31", "2026-04-30", "2026-07-31", "2026-10-31"]
    assert snapshot_dates(date(2027, 1, 5)) == ["2026-03-31", "2026-06-30", "2026-09-30", "2026-12-31"]
    assert snapshot_dates(date(2026, 3, 31)) == ["2025-05-31", "2025-08-31", "2025-11-30", "2026-02-28"]

    store = PortfolioStore(tmp_path / "now")
    summary = await generate_demo_dataset(store, today=date(2026, 11, 11))
    assert summary.snapshot_dates == ["2026-01-31", "2026-04-30", "2026-07-31", "2026-10-31"]
    assert store.all_snapshot_dates() == summary.snapshot_dates

    fixed = PortfolioStore(tmp_path / "fixed")
    assert (await generate_demo_dataset(fixed)).snapshot_dates == SNAPSHOT_DATES == ["2025-11-28", "2026-02-27", "2026-05-29", "2026-08-12"]
