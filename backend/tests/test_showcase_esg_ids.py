"""Showcase defect 7: the ESG upload knows the companies of uploaded portfolios, whose issuer exists only as the
resolution of their security (no registry company)."""
import pytest

from arp.holdings.intake import IntakeError
from arp.portfolio.climate.esg_intake import ESG_TEMPLATE_COLUMNS, FIELD_IDS, ingest_esg_bytes, template
from arp.schemas.portfolio import SecurityRef, SecurityResolution
from arp.storage.portfolio_store import PortfolioStore

pytestmark = pytest.mark.usefixtures("pg")  # every intake also records a provider load in Postgres
ISIN = "US0378331005"


def _file(company_id: str) -> bytes:
    values = {"company_id": company_id, **{f: "1.5" for f in FIELD_IDS}}
    return template("csv") + (",".join(values[c] for c in ESG_TEMPLATE_COLUMNS) + "\n").encode()


@pytest.fixture
def store(tmp_path):
    """One uploaded security, matched by the security master to issuer `iss_a`; no registry company."""
    store = PortfolioStore(tmp_path / "pf")
    store.save_security(SecurityRef(security_id=ISIN, isin=ISIN, name="Apple", asset_class="other", currency="EUR"))
    store.save_resolution(SecurityResolution(security_id=ISIN, company_id="iss_a", confidence=1.0, needs_review=False))
    return store


def test_esg_row_for_an_uploaded_portfolios_issuer_is_written(store):
    assert store.list_companies() == []
    result = ingest_esg_bytes(store, _file("iss_a"), "e.csv", provider="default", month="2026-09", source_ref=None)
    assert (result.status, result.rows) == ("written", 1)


def test_an_id_no_security_resolves_to_is_still_unknown(store):
    with pytest.raises(IntakeError) as e:
        ingest_esg_bytes(store, _file("nope"), "e.csv", provider="default", month="2026-09", source_ref=None)
    assert [x.message for x in e.value.errors] == ["unknown company_id 'nope'"]
