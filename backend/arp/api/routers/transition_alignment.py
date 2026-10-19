from __future__ import annotations

from fastapi import APIRouter

from arp.schemas.transition_alignment import BenchmarkOut, BenchmarksOut, RedlineDef, RndTestDef, SectorBenchmarksOut
from arp.transition_alignment.benchmarks import citation, load_benchmarks

router = APIRouter(prefix="/api", tags=["transition-alignment"])


@router.get("/transition-alignment/benchmarks", response_model=BenchmarksOut)
def get_benchmarks() -> BenchmarksOut:
    b = load_benchmarks()
    return BenchmarksOut(
        version=b.version,
        licence_note=b.licence_note,
        sectors=[
            SectorBenchmarksOut(
                sector=name,
                isic_prefixes=s.isic_prefixes,
                capex=BenchmarkOut(
                    value=s.capex.value,
                    unit=s.capex.unit,
                    method=s.capex.method,
                    citation=citation(s.capex.source),
                    url=s.capex.source.url,
                    licence=s.capex.licence,
                ),
                rnd_tests=[
                    RndTestDef(
                        **t.model_dump(include={"id", "label", "numerator", "denominator", "value", "unit"}),
                        citation=citation(t.source),
                    )
                    for t in s.rnd_tests
                ],
                redlines=[RedlineDef(id=r.id, label=r.label, fact=r.fact, citation=citation(r.source)) for r in s.redlines],
            )
            for name, s in b.sectors.items()
        ],
    )
