from __future__ import annotations

import asyncio
import csv
import hashlib
import json
from pathlib import Path

import typer

from arp.cli._shared import _registry, _run_store, _taxonomy_store, _xbrl_source
from arp.company_graph import NOT_CONFIGURED, CompanyGraphError, import_edges, open_graph, parse_edge_csv
from arp.config import Settings, get_settings
from arp.db.fields import SchemaRegistry
from arp.db.session import require_dsn
from arp.discovery.site_finder import build_web_search_client
from arp.golden_set.exposure import ExposureSet, load_set
from arp.ingestion.base import DocumentSource
from arp.ingestion.local_files import parse_file_to_text_with_pages
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.factory import batch_settings, build_llm_client, build_verifier_llm_client
from arp.orchestration.jobs import resume_run
from arp.research.activity_generator import build_theme
from arp.research.exposure_layers import load_run_layers, parse_as_of
from arp.research.funnel import funnel_query, score_pair
from arp.research.funnel_thresholds import thresholds_for
from arp.research.indirect_exposure.core_sectors import classify_theme_core_sectors
from arp.research.indirect_exposure.criticality import apply_criticality_overlay
from arp.research.indirect_exposure.factory import NO_MODEL, resolve_indirect_exposure_model
from arp.research.lifecycle_classifier import classify_theme_lifecycle_stages
from arp.research.match_graph import _funnel_content_store
from arp.research.pipeline import _match_company, run_thematic_universe
from arp.research.rd_exposure.resolver import RDResolverContext
from arp.research.revenue_exposure.catalogue import by_company as catalogue_by_company
from arp.research.revenue_exposure.catalogue import load_catalogue
from arp.research.revenue_exposure.resolver import RevenueResolverContext
from arp.research.taxonomy_schema import THEME_NOT_ALLOWED, ThemeRunRefused, released_run_schema
from arp.schemas.common import CompanyRef, DocType, SourceDocument
from arp.schemas.revenue_exposure import ActivityCatalogueMapping
from arp.schemas.thematic import MatchVerdict, ThemeDefinition
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from arp.universe import load_company_universe

theme_app = typer.Typer(help="Thematic investment universe screening.")
edges_app = typer.Typer(help="Supply edges in the company graph (Neo4j), for the exposure layers.")
theme_app.add_typer(edges_app, name="edges")


@edges_app.command("import")
def theme_edges_import(csv_path: Path = typer.Option(..., "--csv", help="Edge CSV: supplier_key, supplier_name, customer_key, "
                       "customer_name, revenue_share, source_doc, source_passage, effective_date, published_at.")) -> None:
    """Adds the CSV's supply-edge versions to the company graph; all rows or none."""
    settings = Settings()  # read when the command starts, like the rest of its environment
    try:
        if not settings.neo4j_uri:
            raise CompanyGraphError(NOT_CONFIGURED)
        rows = parse_edge_csv(csv_path)
        with open_graph(settings) as driver:
            new = import_edges(driver, rows)
    except (ValueError, csv.Error, CompanyGraphError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"{len(rows)} rows, {new} new")


trend_app = typer.Typer(help="Quarterly theme trend snapshots: market, co-movement and capex / R&D diffusion.")
theme_app.add_typer(trend_app, name="trend")


@trend_app.command("snapshot")
def theme_trend_snapshot(
    taxonomy_id: str,
    symbols: Path = typer.Option(..., "--symbols", help="CSV with company_id, symbol, home_index and optional cik."),
    quarter: str = typer.Option(None, "--quarter", help="One quarter, YYYYQn."),
    start: str = typer.Option(None, "--from", help="First quarter of a range, YYYYQn."),
    stop: str = typer.Option(None, "--to", help="Last quarter of a range, YYYYQn."),
    prices: Path = typer.Option(None, "--prices", help="Wide CSV of weekly prices; default Yahoo."),
    facts_dir: Path = typer.Option(None, "--facts-dir", help="Directory of SEC companyfacts CIK<10 digits>.json files; default SEC."),
) -> None:
    """Computes and stores the theme's snapshot for a quarter or a range of quarters; all or none."""
    from datetime import date

    import httpx

    from arp.replication.price_data import CsvPriceSource, YFinancePriceSource
    from arp.research import theme_trend

    try:
        if facts_dir:
            facts_for = theme_trend.facts_from_dir(facts_dir)
        else:
            facts_for = lambda cik: asyncio.run(_xbrl_source().fetch_company_facts(cik))  # noqa: E731
        done = theme_trend.snapshot(
            taxonomy_id, symbols, quarter, start, stop, taxonomy_store=_taxonomy_store(), run_store=_run_store(),
            portfolios_dir=get_settings().portfolios_dir, prices=CsvPriceSource(prices) if prices else YFinancePriceSource(),
            facts_for=facts_for, today=date.today())
    except theme_trend.TrendRefused as e:
        typer.echo(e.args[0], err=True)
        raise typer.Exit(1) from None
    except (ImportError, OSError, ValueError, OverflowError, httpx.HTTPError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from None
    for q in done:
        typer.echo(f"Saved {taxonomy_id} {q}")


@trend_app.command("show")
def theme_trend_show(taxonomy_id: str, as_json: bool = typer.Option(False, "--json")) -> None:
    """The stored quarters side by side, with the change from the previous stored quarter."""
    from arp.research import theme_trend

    try:
        data = theme_trend.load_trend(theme_trend.trend_path(get_settings().portfolios_dir, taxonomy_id))
    except theme_trend.TrendRefused as e:
        typer.echo(e.args[0], err=True)
        raise typer.Exit(1) from None
    except ValueError:  # an id that cannot name a file
        data = None
    if data is None:
        typer.echo(f"No trend stored for {taxonomy_id}.", err=True)
        raise typer.Exit(1)
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    for line in theme_trend.show_lines(data):
        typer.echo(line)


def _num(x: float | None) -> str:
    return "-" if x is None else f"{x:.4f}"


@theme_app.command("layers")
def theme_layers(
    run_id: str = typer.Option(..., "--run"),
    as_of: str = typer.Option(None, "--as-of", help="YYYY-MM-DD; defaults to today (UTC)."),
) -> None:
    """Layer 1 (direct), Layer 2 (value chain), Layer 3 and score S per company of a theme run, tab-separated."""
    settings = Settings()
    try:
        _params, rows = load_run_layers(settings, RunStore(require_dsn(settings), settings.runs_dir), run_id, parse_as_of(as_of))
    except (LookupError, ValueError, CompanyGraphError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo("rank\tissuer_key\tname\tl1\tl2\tl3\tscore\tstatus")
    for r in rows:
        cells = ["-" if r.rank is None else str(r.rank), r.issuer_key, r.name, _num(r.l1), _num(r.l2), _num(r.l3), _num(r.score), r.status]
        typer.echo("\t".join(cells))


@theme_app.command("decompose")
def theme_decompose(name: str, description: str = "", out: Path = typer.Option(..., help="Where to write the ThemeDefinition JSON.")) -> None:
    settings = get_settings()
    llm = build_llm_client(settings)
    theme, _usage = asyncio.run(build_theme(name, description, llm))
    out.write_text(theme.model_dump_json(indent=2))
    typer.echo(f"Wrote theme with {len(theme.activities)} activities to {out}")



@theme_app.command("classify-sectors")
def theme_classify_sectors(
    theme_file: Path = typer.Option(..., "--theme"),
    out: Path = typer.Option(..., help="Where to write the ThemeDefinition JSON with core_isic_codes populated."),
    use_sample_io: bool = typer.Option(
        False, "--use-sample-io", help="Use the bundled illustrative sample input-output model instead of ARP_VALUE_CHAIN_DIR."
    ),
) -> None:
    """Populates each activity's core_isic_codes -- one classification call
    per activity against the input-output model's fixed industry list, run
    once per theme (not per company) before enabling the indirect-exposure
    tier in `theme run --use-sample-io` or with ARP_VALUE_CHAIN_DIR set.
    Also applies the bundled
    criticality overlay (arp.research.indirect_exposure.criticality),
    flagging any activity whose freshly-classified core_isic_codes touch a
    USGS/IEA-listed critical mineral's industry.
    """
    settings = get_settings()
    theme = ThemeDefinition.model_validate_json(theme_file.read_text())
    try:
        model = resolve_indirect_exposure_model(settings, use_sample=use_sample_io)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if model is None:
        typer.echo(f"{NO_MODEL}, or pass --use-sample-io.", err=True)
        raise typer.Exit(1)
    llm = build_llm_client(settings)
    updated_theme, _usage = asyncio.run(classify_theme_core_sectors(theme, model, llm))
    updated_theme = apply_criticality_overlay(updated_theme)
    out.write_text(updated_theme.model_dump_json(indent=2))
    classified = sum(1 for a in updated_theme.activities if a.core_isic_codes)
    critical = sum(1 for a in updated_theme.activities if a.criticality_flag)
    typer.echo(
        f"Classified core sectors for {classified}/{len(updated_theme.activities)} activities "
        f"({critical} flagged critical-input). Wrote {out}"
    )



@theme_app.command("classify-lifecycle")
def theme_classify_lifecycle(
    theme_file: Path = typer.Option(..., "--theme"),
    out: Path = typer.Option(..., help="Where to write the ThemeDefinition JSON with lifecycle_stage populated."),
) -> None:
    """Populates each activity's lifecycle_stage (ideation/innovation/
    commercialization/mature) -- one classification call per activity, run
    once per theme, before a run that enables Method C
    (`theme run --enable-rd-exposure`), which only does anything for
    ideation/innovation-stage activities. Independent of --classify-sectors
    (a different concern -- ISIC industry vs. technology maturity); run
    both if you want both tiers populated.
    """
    settings = get_settings()
    llm = build_llm_client(settings)
    theme = ThemeDefinition.model_validate_json(theme_file.read_text())
    updated_theme, _usage = asyncio.run(classify_theme_lifecycle_stages(theme, llm))
    out.write_text(updated_theme.model_dump_json(indent=2))
    classified = sum(1 for a in updated_theme.activities if a.lifecycle_stage is not None)
    typer.echo(f"Classified lifecycle stage for {classified}/{len(updated_theme.activities)} activities. Wrote {out}")



@theme_app.command("run")
def theme_run(
    theme_file: Path = typer.Option(
        None, "--theme", help="Refused: theme runs start from a taxonomy version (--taxonomy)."
    ),
    taxonomy_id: str = typer.Option(None, "--taxonomy", help="The saved taxonomy to run; its version's schema must be released."),
    taxonomy_version: int = typer.Option(None, "--taxonomy-version", help="Defaults to the latest version."),
    universe: Path = typer.Option(..., help="Company universe CSV or JSON."),
    use_sample_io: bool = typer.Option(
        False,
        "--use-sample-io",
        help="Enable the indirect-exposure tier using the bundled illustrative sample input-output model (demo only).",
    ),
    revenue_catalogue: Path = typer.Option(
        None, "--revenue-catalogue", help="A structured revenue/capex catalogue CSV (see `revenue-catalogue suggest-mapping`)."
    ),
    catalogue_mapping: Path = typer.Option(
        None, "--catalogue-mapping", help="The reviewed activity->catalogue-label mapping JSON (required alongside --revenue-catalogue)."
    ),
    enable_rd_exposure: bool = typer.Option(
        False,
        "--enable-rd-exposure",
        help="Enable Method C (R&D-spend-intensity + news-mention scoring) for ideation/innovation-stage activities.",
    ),
    batch: bool = typer.Option(False, "--batch", help="Use the Message Batches API: 50% cheaper, slower."),
) -> None:
    settings = batch_settings(get_settings(), batch)
    if theme_file is not None:
        typer.echo(THEME_NOT_ALLOWED, err=True)
        raise typer.Exit(1)
    if taxonomy_id is None:
        typer.echo("Provide --taxonomy.", err=True)
        raise typer.Exit(1)
    try:
        taxonomy, schema = released_run_schema(
            _taxonomy_store(), SchemaRegistry(settings.postgres_dsn), taxonomy_id, taxonomy_version
        )
    except ThemeRunRefused as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    theme = taxonomy.theme
    typer.echo(f"Using taxonomy {taxonomy.taxonomy_id} v{taxonomy.version}, schema {schema.schema_id} v{schema.version}.")
    llm = build_llm_client(settings)
    verifier_llm = build_verifier_llm_client(settings)
    companies = load_company_universe(universe)
    try:
        indirect_model = resolve_indirect_exposure_model(settings, use_sample=use_sample_io)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if indirect_model is not None:
        typer.echo(f"Indirect exposure tier enabled ({indirect_model.edition_label}).")

    if bool(revenue_catalogue) != bool(catalogue_mapping):
        typer.echo("Provide both --revenue-catalogue and --catalogue-mapping together, or neither.", err=True)
        raise typer.Exit(1)
    revenue_resolver = None
    mappings: list[ActivityCatalogueMapping] | None = None
    if revenue_catalogue is not None:
        catalogue = load_catalogue(revenue_catalogue)
        mappings = [ActivityCatalogueMapping.model_validate(m) for m in json.loads(catalogue_mapping.read_text())]
        revenue_resolver = RevenueResolverContext(
            catalogue_by_company=catalogue_by_company(catalogue), mappings=mappings, registry=_registry(), settings=settings, schema=schema,
            isic_model=indirect_model,
        )
        typer.echo(f"Revenue-exposure resolution enabled ({len(mappings)} confirmed activity mapping(s)).")

    rd_resolver = None
    if enable_rd_exposure:
        rd_resolver = RDResolverContext(
            registry=_registry(), settings=settings, schema=schema, isic_model=indirect_model,
            search_client=build_web_search_client(settings.discovery_user_agent),
        )
        typer.echo("R&D/news exposure resolution enabled (ideation/innovation-stage activities only).")

    typer.echo(f"Running theme '{theme.name}' against {len(companies)} companies...")
    run_id = asyncio.run(
        run_thematic_universe(
            theme,
            companies,
            llm=llm,
            verifier_llm=verifier_llm,
            registry=_registry(),
            settings=settings,
            run_store=_run_store(),
            indirect_model=indirect_model,
            revenue_resolver=revenue_resolver,
            rd_resolver=rd_resolver,
            universe_path=str(universe),
            use_sample_io=use_sample_io,
            revenue_catalogue_path=str(revenue_catalogue) if revenue_catalogue else None,
            catalogue_mapping=mappings,
            enable_rd_exposure=enable_rd_exposure,
            taxonomy_id=taxonomy.taxonomy_id,
            taxonomy_version=taxonomy.version,
            extraction_schema=schema,
        )
    )
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/)")



@theme_app.command("resume")
def theme_resume(run_id: str) -> None:
    """Re-invokes a theme run that was interrupted, failed, partially
    completed, or cancelled -- reconstructed from what `theme run`
    persisted at creation time. Already-completed companies are skipped
    automatically."""
    settings = get_settings()
    llm = build_llm_client(settings)
    verifier_llm = build_verifier_llm_client(settings)
    try:
        run_id = asyncio.run(
            resume_run(
                run_id, llm=llm, verifier_llm=verifier_llm, registry=_registry(), settings=settings, run_store=_run_store()
            )
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Resumed run complete: {run_id} (see runs/{run_id}/)")


# --- theme funnel over an exposure golden set (spec 2026-11-01-theme-funnel-design) -------------------------


def _funnel_taxonomy(taxonomy_id: str | None, version: int | None, taxonomies_dir: Path | None, theme_file: Path | None):
    """The taxonomy version the funnel commands read activities (and contrast statements) from."""
    if theme_file is not None:
        typer.echo(THEME_NOT_ALLOWED, err=True)
        raise typer.Exit(1)
    if taxonomy_id is None:
        typer.echo("Provide --taxonomy.", err=True)
        raise typer.Exit(1)
    taxonomy = TaxonomyStore(taxonomies_dir or get_settings().taxonomies_dir).get(taxonomy_id, version)
    if taxonomy is None:
        typer.echo(f"Taxonomy not found: {taxonomy_id}", err=True)
        raise typer.Exit(1)
    return taxonomy


def _case_documents(documents_dir: Path, case_id: str) -> list[SourceDocument]:
    """Files under `<documents_dir>/<case_id>/<doc_type>/`, the LocalFileDocumentSource layout."""
    docs = []
    for path in sorted(p for p in (documents_dir / case_id).glob("*/*") if p.is_file()):
        text, page_breaks, tables = parse_file_to_text_with_pages(path)
        doc_type = DocType(path.parent.name) if path.parent.name in DocType._value2member_map_ else DocType.OTHER
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]  # content-addressed: chunk ids key stored vectors
        docs.append(SourceDocument(doc_id=f"{case_id}_{digest}", company_id=case_id, doc_type=doc_type,
                                   title=path.name, local_path=str(path), full_text=text, page_breaks=page_breaks,
                                   table_spans=tables))
    return docs


def funnel_report(theme: ThemeDefinition, cases: ExposureSet, documents_dir: Path, split: str) -> list[dict]:
    """One row per golden case: kept when the funnel passes any of the theme's activities for its documents."""
    thresholds = thresholds_for(theme.theme_id)
    store = _funnel_content_store(get_settings())
    rows = []
    for case in cases.cases:
        if split != "all" and case.split != split:
            continue
        try:
            docs = _case_documents(documents_dir, case.case_id)
        except Exception as exc:  # noqa: BLE001 - one unparseable file must not end the golden run
            typer.echo(f"{case.case_id}: could not parse its document: {exc}", err=True)
            docs = []
        if not docs:
            rows.append({"case_id": case.case_id, "label": case.label, "kept": False, "rerank_max": None,
                         "entail_positive": None, "document": False})
            continue
        records = [score_pair(docs, a, thresholds, store, funnel_query(theme, a)) for a in theme.activities]
        best = max(records, key=lambda r: (r.passed, r.entail_positive))  # max keeps the first of equals
        rows.append({"case_id": case.case_id, "label": case.label, "kept": best.passed, "rerank_max": best.rerank_max,
                     "entail_positive": best.entail_positive, "document": True, "funnel": best.model_dump()})
    return rows


@theme_app.command("funnel")
def theme_funnel(
    theme_file: Path = typer.Option(None, "--theme", help="Refused: the funnel reads a taxonomy version (--taxonomy)."),
    taxonomy_id: str = typer.Option(None, "--taxonomy", help="The saved taxonomy whose activities are scored."),
    taxonomy_version: int = typer.Option(None, "--taxonomy-version", help="Defaults to the latest version."),
    taxonomies_dir: Path = typer.Option(None, "--taxonomies-dir", help="Taxonomy store directory (default: configured)."),
    cases: Path = typer.Option(..., "--cases", help="Exposure golden set cases.json."),
    documents_dir: Path = typer.Option(..., "--documents-dir", help="Holds <case_id>/<doc_type>/<file> per case."),
    split: str = typer.Option("all", "--split", help="tune, holdout or all."),
    min_kept_positive: float = typer.Option(None, "--min-kept-positive", help="Exit 1 if positives kept / total < x."),
    max_kept_negative: float = typer.Option(None, "--max-kept-negative", help="Exit 1 if `not` kept / total > x."),
    out: Path = typer.Option(None, "--out", help="Write the per-case rows as JSON."),
) -> None:
    """Runs only the theme funnel (no LLM) over a golden set and prints how many cases each label keeps."""
    taxonomy = _funnel_taxonomy(taxonomy_id, taxonomy_version, taxonomies_dir, theme_file)
    golden = load_set(cases.parent)
    rows = funnel_report(taxonomy.theme, golden, documents_dir, split)
    for r in rows:
        if not r["document"]:
            typer.echo(f"{r['case_id']}: no document ({r['label']}, not kept)")
            continue
        rerank = "n/a" if r["rerank_max"] is None else f"{r['rerank_max']:.2f}"
        typer.echo(f"{r['case_id']} {r['label']}: rerank {rerank}, positive {r['entail_positive']:.2f}, "
                   f"{'pass' if r['kept'] else 'screened'}")
    if out is not None:
        out.write_text(json.dumps(rows, indent=2))
    for label in golden.labels:
        of_label = [r for r in rows if r["label"] == label]
        typer.echo(f"{label}: {sum(r['kept'] for r in of_label)}/{len(of_label)}")
    positives = [r for r in rows if r["label"] != "not"]
    negatives = [r for r in rows if r["label"] == "not"]
    failed = False
    if min_kept_positive is not None and positives and sum(r["kept"] for r in positives) / len(positives) < min_kept_positive:
        typer.echo(f"Positives kept below {min_kept_positive}.", err=True)
        failed = True
    if max_kept_negative is not None and negatives and sum(r["kept"] for r in negatives) / len(negatives) > max_kept_negative:
        typer.echo(f"`not` kept above {max_kept_negative}.", err=True)
        failed = True
    if failed:
        raise typer.Exit(1)


class _CaseFiles(DocumentSource):
    """The golden set's local files as a document source (no content store, no identity checks)."""

    name = "golden_case_files"

    def __init__(self, documents_dir: Path) -> None:
        self.documents_dir = documents_dir

    async def fetch(self, company, doc_types=None):
        return _case_documents(self.documents_dir, company.company_id)


class _CountingLLM:
    def __init__(self, llm) -> None:
        self._llm = llm
        self.calls = 0

    async def complete_structured(self, **kwargs):
        self.calls += 1
        return await self._llm.complete_structured(**kwargs)


async def _compare_arm(theme: ThemeDefinition, cases: list, documents_dir: Path, settings: Settings) -> list[dict]:
    """Each golden company through the theme run's per-company step; LLM calls counted per company."""
    llm = _CountingLLM(build_llm_client(settings))
    verifier = _CountingLLM(build_verifier_llm_client(settings))
    registry = DocumentSourceRegistry([_CaseFiles(documents_dir)])
    rows = []
    for case in cases:
        before = llm.calls + verifier.calls
        result = await _match_company(CompanyRef(company_id=case.case_id, name=case.company), theme, registry=registry,
                                      llm=llm, verifier_llm=verifier, settings=settings)
        included = any(m.verdict == MatchVerdict.INCLUDE for m in result.matches)
        rows.append({"label": case.label, "calls": llm.calls + verifier.calls - before, "include": included})
    return rows


def _precision(rows: list[dict]) -> float:
    included = [r for r in rows if r["include"]]
    return sum(r["label"] != "not" for r in included) / len(included) if included else 0.0


@theme_app.command("funnel-compare")
def theme_funnel_compare(
    theme_file: Path = typer.Option(None, "--theme", help="Refused: the funnel reads a taxonomy version (--taxonomy)."),
    taxonomy_id: str = typer.Option(None, "--taxonomy", help="The saved taxonomy to run."),
    taxonomy_version: int = typer.Option(None, "--taxonomy-version", help="Defaults to the latest version."),
    taxonomies_dir: Path = typer.Option(None, "--taxonomies-dir", help="Taxonomy store directory (default: configured)."),
    cases: Path = typer.Option(..., "--cases", help="Exposure golden set cases.json."),
    documents_dir: Path = typer.Option(..., "--documents-dir", help="Holds <case_id>/<doc_type>/<file> per case."),
    split: str = typer.Option("all", "--split", help="tune, holdout or all."),
    negatives_only: bool = typer.Option(False, "--negatives-only", help="Count LLM calls on `not` cases only."),
    max_call_ratio: float = typer.Option(None, "--max-call-ratio", help="Exit 1 if calls on > x * calls off."),
    max_precision_drop: float = typer.Option(None, "--max-precision-drop", help="Exit 1 if include precision drops by > x."),
) -> None:
    """Runs the theme matching on the golden companies with the funnel off, then on, and compares LLM calls and the
    precision of `include` verdicts (core and peripheral count as positive). Writes no run."""
    taxonomy = _funnel_taxonomy(taxonomy_id, taxonomy_version, taxonomies_dir, theme_file)
    golden = load_set(cases.parent)
    chosen = [c for c in golden.cases if split == "all" or c.split == split]
    base = get_settings()
    arms = {
        on: asyncio.run(_compare_arm(taxonomy.theme, chosen, documents_dir,
                                     base.model_copy(update={"models_universe_funnel_enabled": on})))
        for on in (False, True)
    }
    counted = {on: sum(r["calls"] for r in rows if not negatives_only or r["label"] == "not") for on, rows in arms.items()}
    precision = {on: _precision(rows) for on, rows in arms.items()}
    typer.echo(f"llm_calls_off: {counted[False]}")
    typer.echo(f"llm_calls_on: {counted[True]}")
    typer.echo(f"precision_off: {precision[False]:.3f}")
    typer.echo(f"precision_on: {precision[True]:.3f}")
    failed = False
    if max_call_ratio is not None and counted[True] > max_call_ratio * counted[False]:
        typer.echo(f"LLM calls with the funnel exceed {max_call_ratio} x calls without.", err=True)
        failed = True
    if max_precision_drop is not None and precision[False] - precision[True] > max_precision_drop:
        typer.echo(f"Include precision dropped by more than {max_precision_drop}.", err=True)
        failed = True
    if failed:
        raise typer.Exit(1)
