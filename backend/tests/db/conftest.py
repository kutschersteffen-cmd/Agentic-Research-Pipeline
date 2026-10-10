from __future__ import annotations

import os

import pytest

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")


@pytest.fixture(scope="session")
def _schema():
    if not DSN:
        pytest.skip("ARP_TEST_POSTGRES_DSN not set -- opt-in Postgres integration test")
    from arp.storage.postgres_schema import ensure_schema

    ensure_schema(DSN)
    return DSN


@pytest.fixture
def pg(_schema):
    """Empty tables for each test; yields the DSN."""
    from tests.postgres_helpers import reset_postgres_tables

    reset_postgres_tables(_schema)
    yield _schema
