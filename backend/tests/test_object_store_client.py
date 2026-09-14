"""Unit tests for the object-store lazy client (no real MinIO/S3 endpoint
required) -- mirrors test_opensearch_client.py: the "extra not installed"
failure mode is pure Python and doesn't need a live service. Simulates the
extra being absent via sys.modules regardless of whether boto3 actually
happens to be installed in the test environment."""

from __future__ import annotations

import sys

import pytest

from arp.storage.object_store_client import ObjectStoreExtraNotInstalled, get_client


def test_get_client_raises_when_extra_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    get_client.cache_clear()
    try:
        with pytest.raises(ObjectStoreExtraNotInstalled):
            get_client("http://localhost:9000", "arp", "arp12345")
    finally:
        get_client.cache_clear()
