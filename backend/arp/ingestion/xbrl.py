from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from arp.ingestion.edgar import EdgarDocumentSource
from arp.schemas.common import Citation, DocType, now_iso

logger = logging.getLogger(__name__)

_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"

# Priority-ordered US-GAAP concepts for each metric -- the first tag present
# in a company's own filed facts wins. Filers tag inconsistently (a company
# reporting under ASC 842 vs. an older standard, or one that nets CapEx
# against disposals) rather than one canonical tag existing for every
# company, so a fixed fallback list is necessary, not optional.
_CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsForCapitalImprovements",
    "CapitalExpenditures",
    "PaymentsToAcquireProductiveAssets",
]
_RND_TAGS = ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"]

# Not currently overlaid onto CompanyFinancialsRecord (segment-level revenue
# tagging is far less standardized across filers than CapEx/R&D), but
# resolved and exposed for callers that want a hard total-revenue anchor
# (e.g. the revenue-exposure resolver's denominator) without an LLM call.
_REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
]

_ANNUAL_FORMS = {"10-K", "10-K/A"}


def _full_year(row: dict) -> bool:
    """A duration of about a year; an instant (no start, e.g. a balance) passes."""
    if not row.get("start"):
        return True
    days = (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days
    return 350 <= days <= 380


class XbrlFact(BaseModel):
    """One resolved figure from SEC EDGAR's structured XBRL companyfacts
    API -- never an LLM's read of prose, the exact "what's already
    machine-readable is never estimated by an LLM" principle the rest of
    this codebase applies to the revenue/CapEx catalogue cascade
    (arp/research/revenue_exposure/), extended to cover EDGAR filers'
    own structured financial facts as well as user-supplied catalogues.
    """

    tag: str
    value: float
    unit: str
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    form: str
    filed: str | None = None
    accession: str | None = None
    period_start: str | None = None
    period_end: str | None = None

    def as_citation(self, cik: str) -> Citation:
        # The period's own end, not companyfacts' `fy` (the filing's year, which also
        # labels the comparatives a filing repeats); fractions (EPS, ratios) as tagged.
        value = f"{self.value:,.0f}" if self.value.is_integer() else f"{self.value:,}"
        period = f"period ending {self.period_end}" if self.period_end else f"FY{self.fiscal_year} {self.fiscal_period or ''}".strip()
        quote = (
            f"{self.tag if ':' in self.tag else 'us-gaap:' + self.tag} = {value} {self.unit} "
            f"({period}, form {self.form}, filed {self.filed})"
        )
        return Citation(
            doc_id=f"xbrl:{cik}:{self.accession or self.tag}",
            doc_type=DocType.OTHER,
            quote=quote,
            location="SEC EDGAR XBRL companyfacts API",
            # Set true directly, not run through arp/grounding.py's
            # substring check: there is no source document text to check
            # a quote against here, because the "quote" *is* a structured
            # SEC fact, not an LLM's paraphrase of one. Grounding the
            # citation would be checking the fact against itself.
            grounded=True,
            company_id=None,
            source_filename=None,
        )


class CompanyXbrlFacts(BaseModel):
    company_id: str
    cik: str
    capex: XbrlFact | None = None
    rnd: XbrlFact | None = None
    revenue: XbrlFact | None = None
    fetched_at: str = Field(default_factory=now_iso)


class XbrlFactTrend(BaseModel):
    """Two consecutive annual figures for one tag and the resulting
    year-over-year change -- additive to `XbrlFact` (roadmap P3's
    structured-financials cross-check for the Emerging Themes Scanner),
    not a replacement: `fetch_capex_rnd_revenue` above still answers "what
    is this company's latest figure", this answers "did it move".
    """

    tag: str
    latest: XbrlFact
    prior: XbrlFact
    pct_change: float | None = Field(
        default=None, description="(latest.value - prior.value) / abs(prior.value); None when prior.value is 0."
    )


class CompanyXbrlTrend(BaseModel):
    company_id: str
    cik: str
    capex: XbrlFactTrend | None = None
    rnd: XbrlFactTrend | None = None
    fetched_at: str = Field(default_factory=now_iso)


class XbrlFactSource:
    """Resolves CapEx/R&D/Revenue totals for EDGAR filers directly from
    SEC's structured XBRL companyfacts API
    (data.sec.gov/api/xbrl/companyfacts/), bypassing the LLM extraction
    pipeline entirely for figures that are already machine-readable.

    Deliberately narrow in scope: only the three well-standardized total
    figures every 10-K filer tags roughly consistently. Segment-level
    breakdowns, plain-language descriptions of what CapEx/R&D is going
    toward, and non-US filers (no XBRL-via-EDGAR equivalent covered here)
    still go through the LLM extractor/verifier pipeline -- this is a
    "Path 0" ahead of that pipeline for the subset of fields it covers,
    the same cascade shape as arp/research/revenue_exposure/resolver.py's
    catalogue-first design, not a replacement for it.
    """

    def __init__(
        self,
        edgar: EdgarDocumentSource,
        cache_dir: Path,
        ttl_hours: float = 24.0 * 7,
    ) -> None:
        self._edgar = edgar
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._ttl_hours = ttl_hours

    async def resolve_cik(self, cik: str | None, ticker: str | None) -> str | None:
        return cik or await self._edgar.resolve_cik(ticker)

    async def fetch_company_facts(self, cik: str) -> dict | None:
        """Company facts change as later filings amend/restate prior
        figures, so this is TTL-bounded like EdgarDocumentSource's
        submissions cache (a week by default -- much lower churn than
        filings-list metadata, so a longer TTL is appropriate) rather than
        cached forever like an immutable filing document."""
        cik10 = cik.zfill(10)
        path = self._cache_dir / f"xbrl_companyfacts_{cik10}.json"
        if path.exists():
            try:
                payload = json.loads(path.read_text())
                if time.time() - payload["_fetched_at"] < self._ttl_hours * 3600:
                    return payload["data"]
            except (json.JSONDecodeError, KeyError, OSError):
                pass

        async with httpx.AsyncClient(headers=self._edgar.headers, timeout=30.0) as client:
            resp = await client.get(_COMPANY_FACTS_URL.format(cik10=cik10))
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        try:
            path.write_text(json.dumps({"_fetched_at": time.time(), "data": data}))
        except OSError:
            logger.warning("Could not write XBRL companyfacts cache for CIK %s", cik10)
        return data

    @staticmethod
    def _fact_from_row(tag: str, unit_name: str | None, row: dict) -> XbrlFact:
        return XbrlFact(
            tag=tag,
            value=float(row["val"]),
            unit=unit_name or "USD",
            fiscal_year=row.get("fy"),
            fiscal_period=row.get("fp"),
            form=row.get("form", ""),
            filed=row.get("filed"),
            accession=row.get("accn"),
            period_start=row.get("start"),
            period_end=row.get("end"),
        )

    @staticmethod
    def _annual_candidates(entry: dict) -> tuple[str | None, list[dict]]:
        """The unit name and every row worth considering for one tag's
        entry -- annual (10-K, full fiscal year) rows if any exist,
        otherwise every valued row -- shared by both `_best_annual_fact`
        (one row) and `_best_two_annual_facts` (roadmap P3, two rows)."""
        units = entry.get("units", {})
        unit_name, rows = next(iter(units.items()), (None, []))
        if not rows:
            return unit_name, []
        annual_rows = [r for r in rows if r.get("form") in _ANNUAL_FORMS and r.get("fp") == "FY" and r.get("val") is not None]
        return unit_name, annual_rows or [r for r in rows if r.get("val") is not None]

    def _best_annual_fact(self, facts_json: dict, tags: list[str]) -> XbrlFact | None:
        us_gaap = facts_json.get("facts", {}).get("us-gaap", {})
        for tag in tags:
            entry = us_gaap.get(tag)
            if not entry:
                continue
            unit_name, candidates = self._annual_candidates(entry)
            if not candidates:
                continue
            # Most recent annual (10-K, full fiscal year) figure by period
            # end date -- a company's own latest audited annual figure,
            # not a duplicate seen across multiple quarterly filings that
            # happen to also report the trailing annual number.
            best = max(candidates, key=lambda r: (r.get("end") or "", r.get("filed") or ""))
            return self._fact_from_row(tag, unit_name, best)
        return None

    @staticmethod
    def fact_for_tags(facts_json: dict, tags: list[str], *, fiscal_year: int) -> XbrlFact | None:
        """The annual (10-K / 10-K/A, full-year) fact for exactly `fiscal_year` -- the year
        its period ends in, not companyfacts' `fy`, which is the filing's year and also
        labels the prior-year comparatives a filing repeats -- for the first tag in list
        order that has one. Tags are "taxonomy:Name" ("us-gaap:Revenues"); a bare name
        is us-gaap. USD rows when the tag has them, else its only unit (shares, pure)."""
        facts = facts_json.get("facts", {})
        for tag in tags:
            taxonomy, _, name = tag.rpartition(":")
            units = facts.get(taxonomy or "us-gaap", {}).get(name, {}).get("units", {})
            unit_name, rows = ("USD", units["USD"]) if "USD" in units else next(iter(units.items()), (None, []))
            hits = [r for r in rows if r.get("form") in _ANNUAL_FORMS and r.get("fp") == "FY" and r.get("val") is not None
                    and (r.get("end") or "")[:4] == str(fiscal_year) and _full_year(r)]
            if hits:
                # That year's own 10-K (or its amendment) first, then the latest filed.
                best = max(hits, key=lambda r: (r.get("fy") == fiscal_year, r.get("filed") or ""))
                return XbrlFactSource._fact_from_row(name if taxonomy in ("", "us-gaap") else tag, unit_name, best)
        return None

    def _best_two_annual_facts(self, facts_json: dict, tags: list[str]) -> tuple[XbrlFact, XbrlFact] | None:
        """Roadmap P3: the two most recent *distinct-period* annual facts
        for the first tag that has at least two, for a genuine
        year-over-year comparison -- de-duped by period_end because a
        quarterly filing sometimes re-reports the same trailing annual
        figure, which would otherwise look like a second data point for
        the same fiscal year."""
        us_gaap = facts_json.get("facts", {}).get("us-gaap", {})
        for tag in tags:
            entry = us_gaap.get(tag)
            if not entry:
                continue
            unit_name, candidates = self._annual_candidates(entry)
            if not candidates:
                continue
            ranked = sorted(candidates, key=lambda r: (r.get("end") or "", r.get("filed") or ""), reverse=True)
            distinct: list[dict] = []
            seen_ends: set[str] = set()
            for row in ranked:
                end = row.get("end") or ""
                if end in seen_ends:
                    continue
                seen_ends.add(end)
                distinct.append(row)
                if len(distinct) == 2:
                    break
            if len(distinct) < 2:
                continue
            latest_row, prior_row = distinct
            return self._fact_from_row(tag, unit_name, latest_row), self._fact_from_row(tag, unit_name, prior_row)
        return None

    def _fact_trend(self, facts_json: dict, tags: list[str]) -> XbrlFactTrend | None:
        pair = self._best_two_annual_facts(facts_json, tags)
        if pair is None:
            return None
        latest, prior = pair
        pct_change = (latest.value - prior.value) / abs(prior.value) if prior.value != 0 else None
        return XbrlFactTrend(tag=latest.tag, latest=latest, prior=prior, pct_change=pct_change)

    async def fetch_capex_rnd_revenue(self, company_id: str, cik: str) -> CompanyXbrlFacts | None:
        facts_json = await self.fetch_company_facts(cik)
        if facts_json is None:
            return None
        return CompanyXbrlFacts(
            company_id=company_id,
            cik=cik,
            capex=self._best_annual_fact(facts_json, _CAPEX_TAGS),
            rnd=self._best_annual_fact(facts_json, _RND_TAGS),
            revenue=self._best_annual_fact(facts_json, _REVENUE_TAGS),
        )

    async def fetch_capex_rnd_trend(self, company_id: str, cik: str) -> CompanyXbrlTrend | None:
        """Roadmap P3's structured-financials cross-check: year-over-year
        CapEx/R&D movement, for an "action evidence" signal that doesn't
        need an LLM call. Returns `None` only when the company has no
        XBRL facts at all (a non-filer); a company with only one annual
        data point for a tag (too new a filer, or a tag it just started
        reporting) simply gets `None` for that specific metric, same
        graceful-degradation discipline as `fetch_capex_rnd_revenue`.
        """
        facts_json = await self.fetch_company_facts(cik)
        if facts_json is None:
            return None
        return CompanyXbrlTrend(
            company_id=company_id,
            cik=cik,
            capex=self._fact_trend(facts_json, _CAPEX_TAGS),
            rnd=self._fact_trend(facts_json, _RND_TAGS),
        )
