from arp.emerging_themes.action_evidence import check_company_action_evidence
from arp.ingestion.xbrl import CompanyXbrlTrend, XbrlFact, XbrlFactTrend
from arp.schemas.common import CompanyRef


class _FakeXbrlSource:
    """Duck-types the two XbrlFactSource methods check_company_action_evidence
    calls -- no network, no cache, so these tests exercise only the
    graceful-degradation logic, not XbrlFactSource itself (see
    test_xbrl.py for that)."""

    def __init__(self, cik: str | None, trend: CompanyXbrlTrend | None) -> None:
        self._cik = cik
        self._trend = trend

    async def resolve_cik(self, cik: str | None, ticker: str | None) -> str | None:
        return cik or self._cik

    async def fetch_capex_rnd_trend(self, company_id: str, cik: str) -> CompanyXbrlTrend | None:
        return self._trend


def _fact(value: float, fiscal_year: int) -> XbrlFact:
    return XbrlFact(tag="PaymentsToAcquirePropertyPlantAndEquipment", value=value, unit="USD", fiscal_year=fiscal_year, fiscal_period="FY", form="10-K", filed="2026-02-01", accession="acc1")


async def test_returns_none_when_cik_unresolvable():
    company = CompanyRef(company_id="c1", name="Acme", ticker=None, cik=None)
    source = _FakeXbrlSource(cik=None, trend=None)

    result = await check_company_action_evidence(company, source)

    assert result is None


async def test_returns_none_when_no_xbrl_facts_at_all():
    company = CompanyRef(company_id="c1", name="Acme", ticker="ACME", cik=None)
    source = _FakeXbrlSource(cik="320193", trend=None)

    result = await check_company_action_evidence(company, source)

    assert result is None


async def test_returns_none_when_trend_has_no_capex_or_rnd():
    company = CompanyRef(company_id="c1", name="Acme", ticker="ACME", cik=None)
    trend = CompanyXbrlTrend(company_id="c1", cik="320193", capex=None, rnd=None)
    source = _FakeXbrlSource(cik="320193", trend=trend)

    result = await check_company_action_evidence(company, source)

    assert result is None


async def test_builds_evidence_from_capex_and_rnd_trend():
    company = CompanyRef(company_id="c1", name="Acme", ticker="ACME", cik=None)
    capex_trend = XbrlFactTrend(tag="PaymentsToAcquirePropertyPlantAndEquipment", latest=_fact(340_000_000, 2025), prior=_fact(300_000_000, 2024), pct_change=0.1333)
    trend = CompanyXbrlTrend(company_id="c1", cik="320193", capex=capex_trend, rnd=None)
    source = _FakeXbrlSource(cik="320193", trend=trend)

    result = await check_company_action_evidence(company, source)

    assert result is not None
    assert result.company_id == "c1"
    assert result.cik == "320193"
    assert result.capex_pct_change == 0.1333
    assert result.rnd_pct_change is None
