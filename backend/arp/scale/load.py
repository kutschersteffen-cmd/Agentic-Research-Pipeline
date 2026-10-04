"""Load drivers: a simulated one (no network, orchestration overhead only) and a live one."""

from __future__ import annotations

import asyncio
from pathlib import Path

from arp.config import Settings
from arp.extraction.pipeline import create_extraction_run, execute_extraction_run
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMUsage
from arp.llm.factory import build_llm_client, build_verifier_llm_client
from arp.orchestration.batch_runner import run_company_batch
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import DataPointSchema
from arp.storage.run_store import RunStore
from arp.universe import load_company_universe


class _Result:
    def __init__(self, usage: LLMUsage) -> None:
        self.usage = usage


async def simulate(
    n: int,
    concurrency: int,
    *,
    run_store: RunStore,
    latency_s: float = 0.05,
    tokens: tuple[int, int] = (6000, 800),
    cost_per_call_usd: float = 0.03,
    fail_every: int = 0,
) -> str:
    """A `load_test` run over `n` synthetic companies; each worker sleeps
    `latency_s`. `fail_every=k` makes every k-th company raise."""
    companies = [CompanyRef(company_id=f"LOAD{i:04d}", name=f"Load Issuer {i}") for i in range(n)]
    manifest = JobManager(run_store).create_run(
        "load_test",
        {"concurrency": concurrency, "mode": "simulated", "latency_s": latency_s},
        n,
        companies=companies,
    )
    index = {c.company_id: i for i, c in enumerate(companies, start=1)}

    async def worker(company: CompanyRef) -> _Result:
        await asyncio.sleep(latency_s)
        if fail_every > 0 and index[company.company_id] % fail_every == 0:
            raise RuntimeError(f"simulated failure for {company.company_id}")
        return _Result(LLMUsage(input_tokens=tokens[0], output_tokens=tokens[1]))

    await run_company_batch(
        manifest.run_id,
        companies,
        run_store=run_store,
        worker=worker,
        result_to_json=lambda r: {"usage": r.usage.model_dump(mode="json")},
        review_items=lambda c, r: [],
        cost_usd=lambda r: cost_per_call_usd,
        concurrency=concurrency,
    )
    return manifest.run_id


async def live(
    universe_path: Path,
    schema_path: Path,
    concurrency: int,
    *,
    settings: Settings,
    run_store: RunStore,
    registry: DocumentSourceRegistry,
) -> str:
    """A real extraction run at `concurrency`; costs real API money."""
    settings = settings.model_copy(update={"max_concurrent_llm_calls": concurrency})
    schema = DataPointSchema.model_validate_json(schema_path.read_text())
    companies = load_company_universe(universe_path)
    run_id = create_extraction_run(schema, companies, settings, run_store, trial=True)
    manifest = run_store.load_manifest(run_id)
    manifest.params["concurrency"] = concurrency
    run_store.save_manifest(manifest)
    return await execute_extraction_run(
        run_id,
        schema,
        companies,
        llm=build_llm_client(settings),
        verifier_llm=build_verifier_llm_client(settings),
        registry=registry,
        settings=settings,
        run_store=run_store,
    )
