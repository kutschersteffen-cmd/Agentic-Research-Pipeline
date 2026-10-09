from __future__ import annotations

from collections.abc import Iterator

from arp.xbrl_pipeline.models import CatalogEntry, FactRow


def _concepts(facts: dict) -> Iterator[tuple[str, str, dict]]:
    for taxonomy, concepts in (facts.get("facts") or {}).items():
        for concept, body in concepts.items():
            yield taxonomy, concept, body


def flatten_company_facts(
    facts: dict,
    *,
    company_id: str,
    cik: str,
    source_sha: str,
    concepts: frozenset[str] | None = None,
) -> Iterator[FactRow]:
    for taxonomy, concept, body in _concepts(facts):
        if concepts is not None and f"{taxonomy}:{concept}" not in concepts:
            continue
        for unit, entries in (body.get("units") or {}).items():
            for e in entries:
                yield FactRow(
                    company_id=company_id,
                    cik=cik,
                    taxonomy=taxonomy,
                    concept=concept,
                    unit=unit,
                    value=e["val"],
                    period_start=e.get("start"),
                    period_end=e["end"],
                    fiscal_year=e.get("fy"),
                    fiscal_period=e.get("fp"),
                    form=e["form"],
                    filed=e.get("filed"),
                    accession=e.get("accn"),
                    source_sha=source_sha,
                )


def build_catalog(facts: dict) -> list[CatalogEntry]:
    out = []
    for taxonomy, concept, body in _concepts(facts):
        units = body.get("units") or {}
        years = [e["fy"] for es in units.values() for e in es if e.get("fy") is not None]
        out.append(
            CatalogEntry(
                taxonomy=taxonomy,
                concept=concept,
                label=body.get("label"),
                fact_count=sum(len(es) for es in units.values()),
                first_year=min(years, default=None),
                last_year=max(years, default=None),
                units=list(units),
            )
        )
    return out
