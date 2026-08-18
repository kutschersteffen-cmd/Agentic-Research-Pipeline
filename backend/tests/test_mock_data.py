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
