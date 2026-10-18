"""The company graph in Neo4j: one `Company` node per issuer key, one `SUPPLIES_TO` relationship
per supply-edge version (supplier -> customer). Filled from CSV by `arp theme edges import`; read by
the theme exposure layers. Edge versions are never overwritten: a correction is a new row with a
later `published_at`."""

from __future__ import annotations

import csv
import functools
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import DriverError, Neo4jError

from arp.config import Settings
from arp.research.exposure_layers import Edge

NOT_CONFIGURED = "company graph not configured: set ARP_NEO4J_URI"
COLUMNS = (
    "supplier_key", "supplier_name", "customer_key", "customer_name", "revenue_share",
    "source_doc", "source_passage", "effective_date", "published_at",
)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CompanyGraphError(RuntimeError):
    """The graph is not configured or cannot be reached."""


@dataclass(frozen=True)
class EdgeRow:
    supplier_key: str
    supplier_name: str
    customer_key: str
    customer_name: str
    revenue_share: float
    source_doc: str
    source_passage: str
    effective_date: date
    published_at: date

    @property
    def version(self) -> tuple[str, str, date, date]:
        return self.supplier_key, self.customer_key, self.effective_date, self.published_at

    @property
    def values(self) -> tuple[float, str, str]:
        return self.revenue_share, self.source_doc, self.source_passage


def _conflict(n: int) -> ValueError:
    return ValueError(f"row {n}: an edge with this supplier, customer, effective_date and published_at is already stored with different values")


def _graph_errors(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (Neo4jError, DriverError) as exc:
            raise CompanyGraphError(f"company graph unavailable: {exc}") from exc

    return wrapper


@_graph_errors
def open_graph(settings: Settings) -> Driver:
    """A connected driver with the issuer-key constraint in place; the caller closes it."""
    if not settings.neo4j_uri:
        raise CompanyGraphError(NOT_CONFIGURED)
    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password or ""))
    try:
        driver.verify_connectivity()
        driver.execute_query("CREATE CONSTRAINT company_issuer_key IF NOT EXISTS FOR (c:Company) REQUIRE c.issuer_key IS UNIQUE")
    except BaseException:
        driver.close()
        raise
    return driver


def _parse_row(n: int, raw: dict[str, str]) -> EdgeRow:
    v = {c: (raw.get(c) or "").strip() for c in COLUMNS}
    for c in ("supplier_key", "customer_key", "source_passage"):
        if not v[c]:
            raise ValueError(f"row {n}: {c} is required")
    if v["supplier_key"] == v["customer_key"]:
        raise ValueError(f"row {n}: a company cannot supply itself")
    try:
        share = float(v["revenue_share"])
    except ValueError:
        raise ValueError(f"row {n}: revenue_share must be a number") from None
    if not 0 < share <= 1:
        raise ValueError(f"row {n}: revenue_share must be greater than 0 and at most 1")
    dates = {}
    for c in ("effective_date", "published_at"):
        try:
            if not _DATE.match(v[c]):
                raise ValueError
            dates[c] = date.fromisoformat(v[c])
        except ValueError:
            raise ValueError(f"row {n}: {c} must be a date in YYYY-MM-DD form") from None
    return EdgeRow(
        v["supplier_key"], v["supplier_name"], v["customer_key"], v["customer_name"], share,
        v["source_doc"], v["source_passage"], dates["effective_date"], dates["published_at"],
    )


def parse_edge_csv(path: Path) -> list[EdgeRow]:
    """Every row, or ValueError naming the first bad one ("row n" counts data rows from 1)."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in reader.fieldnames or []]
        for c in COLUMNS:
            if c not in header:
                raise ValueError(f"missing column: {c}")
        reader.fieldnames = header
        rows = [_parse_row(n, raw) for n, raw in enumerate(reader, start=1)]
    seen: dict[tuple, tuple] = {}
    for n, r in enumerate(rows, start=1):
        if seen.setdefault(r.version, r.values) != r.values:
            raise _conflict(n)
    return rows


_EXISTING = """
UNWIND $rows AS row
MATCH (:Company {issuer_key: row.s})-[r:SUPPLIES_TO {effective_date: row.e, published_at: row.p}]->(:Company {issuer_key: row.c})
RETURN row.n AS n, r.revenue_share AS share, r.source_doc AS doc, r.source_passage AS passage
"""
_WRITE = """
UNWIND $rows AS row
MERGE (s:Company {issuer_key: row.s}) SET s.name = row.sn
MERGE (c:Company {issuer_key: row.c}) SET c.name = row.cn
WITH s, c, row WHERE row.new
CREATE (s)-[:SUPPLIES_TO {revenue_share: row.share, source_doc: row.doc, source_passage: row.passage,
                          effective_date: row.e, published_at: row.p}]->(c)
"""


@_graph_errors
def import_edges(driver: Driver, rows: list[EdgeRow]) -> int:
    """Stores the rows' new edge versions in one transaction and returns how many; a row whose
    version is stored with different values raises ValueError and nothing is written."""
    params = [
        {"n": n, "s": r.supplier_key, "sn": r.supplier_name, "c": r.customer_key, "cn": r.customer_name,
         "share": r.revenue_share, "doc": r.source_doc, "passage": r.source_passage,
         "e": r.effective_date, "p": r.published_at}
        for n, r in enumerate(rows, start=1)
    ]

    def work(tx) -> int:
        stored = {rec["n"]: (rec["share"], rec["doc"], rec["passage"]) for rec in tx.run(_EXISTING, rows=params)}
        firsts = set()
        for n, r in enumerate(rows, start=1):
            if n in stored and stored[n] != r.values:
                raise _conflict(n)
            params[n - 1]["new"] = n not in stored and r.version not in firsts
            firsts.add(r.version)
        tx.run(_WRITE, rows=params).consume()
        return sum(p["new"] for p in params)

    with driver.session() as session:
        return session.execute_write(work)


@_graph_errors
def edges_at(driver: Driver, as_of: date) -> tuple[list[Edge], dict[str, str]]:
    """Per supplier-customer pair, the version known at `as_of` with the latest effective_date, then
    the latest published_at; plus the name of every company those edges touch."""
    # shortcut: reads every known edge per request, fine to ~100k edges; move the version pick into Cypher when the graph grows.
    records, _, _ = driver.execute_query(
        "MATCH (s:Company)-[r:SUPPLIES_TO]->(c:Company) WHERE r.effective_date <= $d AND r.published_at <= $d "
        "RETURN s.issuer_key AS s, s.name AS sn, c.issuer_key AS c, c.name AS cn, r.revenue_share AS share, "
        "r.effective_date AS e, r.published_at AS p",
        d=as_of,
    )
    best: dict[tuple[str, str], tuple] = {}
    names: dict[str, str] = {}
    for rec in records:
        names[rec["s"]], names[rec["c"]] = rec["sn"], rec["cn"]
        pair, rank = (rec["s"], rec["c"]), (rec["e"].to_native(), rec["p"].to_native())
        if pair not in best or rank > best[pair][0]:
            best[pair] = (rank, rec["share"])
    return [Edge(s, c, share) for (s, c), (_rank, share) in best.items()], names
