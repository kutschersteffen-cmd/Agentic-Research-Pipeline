"""Unit tests for the OpenSearch lazy client (no real cluster required) --
mirrors how the Postgres equivalent (get_engine) would be tested: the
"extra not installed" failure mode is pure Python and doesn't need a live
service. Simulates the extra being absent via sys.modules regardless of
whether opensearch-py actually happens to be installed in the test
environment, so this test is meaningful either way."""

from __future__ import annotations

import sys

import pytest

from arp.storage.opensearch_client import OpenSearchExtraNotInstalled, get_client


def test_get_client_raises_when_extra_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "opensearchpy", None)
    get_client.cache_clear()
    try:
        with pytest.raises(OpenSearchExtraNotInstalled):
            get_client("http://localhost:9200")
    finally:
        get_client.cache_clear()
