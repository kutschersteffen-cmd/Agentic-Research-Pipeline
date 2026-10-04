import os

import pytest

from tests.postgres_helpers import reset_postgres_tables
from tests.test_publish_store_pg import _cand, _publish

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")


@pytest.fixture(autouse=True)
def _db():
    from arp.storage.postgres import ensure_schema

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    yield
    reset_postgres_tables(DSN)


def test_referenced_returns_run_and_content_key():
    from arp.publish.facts import PublishStore

    store = PublishStore(DSN)
    _publish(store, _cand(), "2026-10-01T09:00:00.000000+00:00")
    runs, keys = store.referenced()
    assert "run1" in runs and "ck" in keys
