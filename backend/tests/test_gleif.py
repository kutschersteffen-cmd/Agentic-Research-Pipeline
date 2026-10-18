from __future__ import annotations

import httpx

from arp.discovery.gleif import GLEIF_API, lei_for_isin, name_matches

LEI = "5299009TESTWERKE0063"


def _record(lei: str, name: str = "Testwerke AG", status: str = "ISSUED", country: str = "DE") -> dict:
    return {
        "id": lei,
        "attributes": {
            "lei": lei,
            "entity": {"legalName": {"name": name}, "legalAddress": {"country": country}},
            "registration": {"status": status},
        },
    }


def _client(records: list[dict] | None = None, *, status: int = 200) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={"data": records or []})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


async def test_lei_for_isin_single_issued():
    client, seen = _client([_record(LEI)])
    assert await lei_for_isin(client, "DE000TST0006") == LEI
    assert str(seen[0].url).startswith(f"{GLEIF_API}/lei-records")
    assert seen[0].url.params["filter[isin]"] == "DE000TST0006"


async def test_lei_for_isin_two_records_is_none():
    client, _ = _client([_record(LEI), _record("5299009OTHERWERKE0064")])
    assert await lei_for_isin(client, "DE000TST0006") is None


async def test_lei_for_isin_lapsed_is_none():
    client, _ = _client([_record(LEI, status="LAPSED")])
    assert await lei_for_isin(client, "DE000TST0006") is None


async def test_name_matches_issued_only_max_5():
    records = [_record(f"LEI{i:017d}", name=f"Testwerke {i}") for i in range(7)]
    records.insert(1, _record("LAPSED00000000000000", status="LAPSED"))
    client, seen = _client(records)
    out = await name_matches(client, "Testwerke & Söhne")
    assert [m.legal_name for m in out] == [f"Testwerke {i}" for i in range(5)]
    assert out[0].lei == "LEI00000000000000000" and out[0].country == "DE"
    assert seen[0].url.params["filter[fulltext]"] == "Testwerke & Söhne"


async def test_gleif_error_returns_empty():
    client, _ = _client(status=500)
    assert await name_matches(client, "Testwerke") == []
    assert await lei_for_isin(client, "DE000TST0006") is None
