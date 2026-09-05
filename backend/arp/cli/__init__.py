from __future__ import annotations

import typer

from arp.cli.calibration import calibration_app
from arp.cli.climate import climate_app
from arp.cli.db import db_app
from arp.cli.discovery import discover_app
from arp.cli.documents import documents_app
from arp.cli.emerging_themes import emerging_themes_app
from arp.cli.engagement import engagement_app
from arp.cli.extraction import extract_app
from arp.cli.golden_set import golden_set_app
from arp.cli.identity import identity_app
from arp.cli.portfolio import portfolio_app
from arp.cli.revenue_catalogue import revenue_catalogue_app
from arp.cli.runs import runs_app
from arp.cli.taxonomy import taxonomy_app
from arp.cli.taxonomy_researcher import taxonomy_researcher_app
from arp.cli.theme import theme_app
from arp.cli.transition_plan import transition_plan_app
from arp.cli.universe import universe_app
from arp.cli.voting import voting_app

app = typer.Typer(help="Agentic Research Pipeline CLI -- the headless path for 1000s-of-companies batch runs.")
app.add_typer(theme_app, name="theme")
app.add_typer(taxonomy_app, name="taxonomy")
app.add_typer(extract_app, name="extract")
app.add_typer(transition_plan_app, name="transition-plan")
app.add_typer(discover_app, name="discover")
app.add_typer(runs_app, name="runs")
app.add_typer(universe_app, name="universe")
app.add_typer(revenue_catalogue_app, name="revenue-catalogue")
app.add_typer(engagement_app, name="engagement")
app.add_typer(voting_app, name="voting")
app.add_typer(portfolio_app, name="portfolio")
app.add_typer(climate_app, name="climate")
app.add_typer(documents_app, name="documents")
app.add_typer(identity_app, name="identity")
app.add_typer(golden_set_app, name="golden-set")
app.add_typer(emerging_themes_app, name="emerging-themes")
app.add_typer(db_app, name="db")
app.add_typer(taxonomy_researcher_app, name="taxonomy-researcher")
app.add_typer(calibration_app, name="calibration")
