"""showcase-stewardship-fixes AC-29..AC-37: calibration compares a document's own date with the verdict, as instants."""

from arp.agents.calibration_agent import check_company_staleness
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import CompanyRef, DocType, SourceDocument
from arp.schemas.thematic import CompanyMatch, ExposureEstimate, MatchVerdict

KO = CompanyRef(company_id="ko", name="Coca-Cola Co")


def match(generated_at):
    return CompanyMatch(company_id="ko", name="Coca-Cola Co", activity_id="act_dd5b90051fcd", activity_name="Soft drinks",
                        verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.SIGNIFICANT, confidence=0.8,
                        adjudicator_rationale="x", generated_at=generated_at)


def doc(**dates):
    return SourceDocument(company_id="ko", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="x", **dates)


class _Source:
    name = "fake"

    def __init__(self, make):
        self.make = make

    async def fetch(self, company, doc_types=None):
        return self.make()


async def check(make, generated_at):
    return await check_company_staleness(KO, [match(generated_at)], DocumentSourceRegistry([_Source(make)]), "src")


async def test_older_published_document_is_not_newer():  # AC-29
    assert await check(lambda: [doc(published_at="2026-01-10T00:00:00+00:00")], "2026-02-01T00:00:00+00:00") == []


async def test_newer_published_document_flags_with_names_and_reason():  # AC-30, AC-36, AC-37
    [flag] = await check(lambda: [doc(published_at="2026-03-01T00:00:00+00:00")], "2026-02-01T00:00:00+00:00")
    assert flag.newest_document_at == "2026-03-01T00:00:00+00:00"
    assert (flag.company_name, flag.activity_name) == ("Coca-Cola Co", "Soft drinks")
    assert flag.reason == "A disclosure dated after this verdict was generated exists -- re-running classification is recommended."


async def test_a_time_stamped_while_fetching_is_ignored_every_time():  # AC-31, AC-32
    for _ in range(2):
        assert await check(lambda: [doc()], "2026-02-01T00:00:00+00:00") == []


async def test_source_supplied_fetched_at_still_counts():  # AC-33 (must not change)
    [flag] = await check(lambda: [doc(fetched_at="2026-02-01T00:00:00+00:00")], "2026-01-01T00:00:00+00:00")
    assert flag.newest_document_at == "2026-02-01T00:00:00+00:00"


async def test_instants_are_compared_not_strings():  # AC-34
    assert await check(lambda: [doc(published_at="2026-02-10T16:31:00.000Z")], "2026-02-10T17:00:00+00:00") == []


async def test_published_at_without_offset_is_utc():  # AC-35
    assert len(await check(lambda: [doc(published_at="2026-03-01T00:00:00")], "2026-02-01T00:00:00+00:00")) == 1
