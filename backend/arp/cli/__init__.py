from __future__ import annotations

import typer

from arp.cli.bi import bi_app
from arp.cli.calibration import calibration_app
from arp.cli.climate import climate_app
from arp.cli.db import db_app
from arp.cli.decision import decision_app
from arp.cli.discovery import discover_app
from arp.cli.documents import documents_app
from arp.cli.emerging_themes import emerging_themes_app
from arp.cli.engagement import engagement_app
from arp.cli.extraction import extract_app
from arp.cli.golden_set import golden_set_app
from arp.cli.holdings import holdings_app
from arp.cli.identity import identity_app
from arp.cli.index import index_app
from arp.cli.portfolio import portfolio_app
from arp.cli.project import project_app
from arp.cli.publish import publish_app
from arp.cli.replication import replicate_app
from arp.cli.reporting import reporting_app
from arp.cli.retention import retention_app
from arp.cli.revenue_catalogue import revenue_catalogue_app
from arp.cli.runs import runs_app
from arp.cli.scale import scale_app
from arp.cli.signal_lab import signals_app
from arp.cli.snapshots import snapshots_app
from arp.cli.taxonomy import taxonomy_app
from arp.cli.taxonomy_researcher import taxonomy_researcher_app
from arp.cli.theme import theme_app
from arp.cli.transition_barrier import transition_barrier_app
from arp.cli.transition_plan import transition_plan_app
from arp.cli.universe import universe_app
from arp.cli.voting import voting_app
from arp.cli.xbrl import xbrl_app

app = typer.Typer(help="Agentic Research Pipeline CLI -- the headless path for 1000s-of-companies batch runs.")


@app.callback()
def _require_postgres(ctx: typer.Context) -> None:
    """Postgres is the system of record: every command needs ARP_POSTGRES_DSN, reachable, and every
    command but `arp db ...` (which migrates and imports) a cut-over database. `--help` needs neither."""
    import sys

    from arp.config import get_settings
    from arp.db.session import require_cutover, require_postgres

    if "--help" in sys.argv[1:]:
        return
    try:
        settings = get_settings()
        require_postgres(settings)
        if ctx.invoked_subcommand != "db":
            require_cutover(settings)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


app.add_typer(theme_app, name="theme")
app.add_typer(taxonomy_app, name="taxonomy")
app.add_typer(extract_app, name="extract")
app.add_typer(transition_plan_app, name="transition-plan")
app.add_typer(transition_barrier_app, name="transition-barrier")
app.add_typer(replicate_app, name="replicate")
app.add_typer(signals_app, name="signals")
app.add_typer(discover_app, name="discover")
app.add_typer(runs_app, name="runs")
app.add_typer(scale_app, name="scale")
app.add_typer(universe_app, name="universe")
app.add_typer(revenue_catalogue_app, name="revenue-catalogue")
app.add_typer(engagement_app, name="engagement")
app.add_typer(voting_app, name="voting")
app.add_typer(portfolio_app, name="portfolio")
app.add_typer(climate_app, name="climate")
app.add_typer(decision_app, name="decision")
app.add_typer(documents_app, name="documents")
app.add_typer(identity_app, name="identity")
app.add_typer(index_app, name="index")
app.add_typer(golden_set_app, name="golden-set")
app.add_typer(emerging_themes_app, name="emerging-themes")
app.add_typer(db_app, name="db")
app.add_typer(taxonomy_researcher_app, name="taxonomy-researcher")
app.add_typer(calibration_app, name="calibration")
app.add_typer(reporting_app, name="report")
app.add_typer(bi_app, name="bi")
app.add_typer(project_app, name="project")
app.add_typer(publish_app, name="publish")
app.add_typer(snapshots_app, name="snapshots")
app.add_typer(holdings_app, name="holdings")
app.add_typer(retention_app, name="retention")
app.add_typer(xbrl_app, name="xbrl")
