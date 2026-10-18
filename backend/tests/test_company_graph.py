import socket
from datetime import date

import pytest

from arp.company_graph import NOT_CONFIGURED, CompanyGraphError, edges_at, import_edges, open_graph, parse_edge_csv
from arp.config import Settings
from arp.research.exposure_layers import Edge

HEADER = "supplier_key,supplier_name,customer_key,customer_name,revenue_share,source_doc,source_passage,effective_date,published_at"
S1_A = "s1,S1,a,A,0.40,10-K 2023,A is our largest customer.,2023-12-31,2024-03-01"
S2_S1 = "s2,S2,s1,S1,0.50,10-K 2023,S1 buys most of our output.,2023-12-31,2024-03-01"


def _csv(tmp_path, *rows, header=HEADER, prefix=""):
    path = tmp_path / "edges.csv"
    path.write_text(prefix + "\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def _err(tmp_path, *rows, **kw):
    with pytest.raises(ValueError) as exc:
        parse_edge_csv(_csv(tmp_path, *rows, **kw))
    return str(exc.value)


def test_parse_fixture_f(tmp_path):
    rows = parse_edge_csv(_csv(tmp_path, S1_A, S2_S1))
    assert [(r.supplier_key, r.customer_key, r.revenue_share) for r in rows] == [("s1", "a", 0.4), ("s2", "s1", 0.5)]
    assert rows[0].effective_date == date(2023, 12, 31) and rows[0].published_at == date(2024, 3, 1)
    assert rows[0].supplier_name == "S1" and rows[0].source_passage == "A is our largest customer."
    assert rows[0].source_doc == "10-K 2023" and rows[1].customer_name == "S1"


def test_share_of_exactly_one_is_allowed(tmp_path):
    assert parse_edge_csv(_csv(tmp_path, S1_A.replace("0.40", "1")))[0].revenue_share == 1.0


def test_quoted_passage_keeps_its_line_break(tmp_path):
    path = tmp_path / "edges.csv"
    path.write_bytes((HEADER + '\r\ns1,S1,a,A,0.4,doc,"Line one.\r\nLine two.",2023-12-31,2024-03-01\r\n').encode())
    assert parse_edge_csv(path)[0].source_passage == "Line one.\r\nLine two."


def test_parse_utf8_bom(tmp_path):
    assert len(parse_edge_csv(_csv(tmp_path, S1_A, prefix="﻿"))) == 1


def test_missing_column(tmp_path):
    assert _err(tmp_path, header=HEADER.replace(",published_at", "")) == "missing column: published_at"


def test_empty_source_passage(tmp_path):
    assert "row 1: source_passage is required" in _err(tmp_path, S1_A.replace("A is our largest customer.", ""))


def test_error_names_the_bad_row(tmp_path):
    assert "row 2: source_passage is required" in _err(tmp_path, S1_A, S2_S1.replace("S1 buys most of our output.", " "))


@pytest.mark.parametrize("share", ["1.5", "0", "-0.1"])
def test_revenue_share_range(tmp_path, share):
    msg = _err(tmp_path, S1_A.replace("0.40", share))
    assert "row 1: revenue_share must be greater than 0 and at most 1" in msg


def test_revenue_share_not_a_number(tmp_path):
    assert "row 1: revenue_share must be a number" in _err(tmp_path, S1_A.replace("0.40", "forty"))


def test_supplier_is_customer(tmp_path):
    assert "row 1: a company cannot supply itself" in _err(tmp_path, S1_A.replace("s1,S1,a,A", "a,A,a,A"))


def test_bad_date(tmp_path):
    assert "row 1: published_at must be a date in YYYY-MM-DD form" in _err(tmp_path, S1_A.replace("2024-03-01", "2024/03/01"))


def test_empty_key(tmp_path):
    assert "row 1: customer_key is required" in _err(tmp_path, S1_A.replace("s1,S1,a,A", "s1,S1,,A"))


def test_conflict_inside_one_file(tmp_path):
    msg = _err(tmp_path, S1_A, S1_A.replace("0.40", "0.45"))
    assert "row 2: an edge with this supplier, customer, effective_date and published_at is already stored with different values" in msg


def test_identical_rows_in_one_file_are_fine(tmp_path):
    assert len(parse_edge_csv(_csv(tmp_path, S1_A, S1_A))) == 2


@pytest.mark.parametrize("uri", [None, ""])
def test_not_configured(uri):
    with pytest.raises(CompanyGraphError, match="^company graph not configured: set ARP_NEO4J_URI$"):
        open_graph(Settings(neo4j_uri=uri))
    assert NOT_CONFIGURED == "company graph not configured: set ARP_NEO4J_URI"


def test_unreachable():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(CompanyGraphError, match="^company graph unavailable: "):
        open_graph(Settings(neo4j_uri=f"bolt://127.0.0.1:{port}", neo4j_password="x"))


@pytest.fixture
def driver(neo4j_graph):
    """The app's own connection (open_graph) to the test graph."""
    with open_graph(Settings()) as d:
        yield d


def test_import_counts_new(driver, neo4j_graph, tmp_path):
    rows = parse_edge_csv(_csv(tmp_path, S1_A, S2_S1))
    assert import_edges(driver, rows) == 2
    assert import_edges(driver, rows) == 0
    records, _, _ = neo4j_graph.execute_query(
        "MATCH (s:Company)-[r:SUPPLIES_TO]->(c:Company) RETURN s.issuer_key, c.issuer_key, r.revenue_share"
    )
    assert {tuple(r.values()) for r in records} == {("s1", "a", 0.4), ("s2", "s1", 0.5)}


def test_stored_conflict_refused_and_nothing_written(driver, neo4j_graph, tmp_path):
    import_edges(driver, parse_edge_csv(_csv(tmp_path, S1_A)))
    rows = parse_edge_csv(_csv(tmp_path, S2_S1, S1_A.replace("0.40", "0.45")))
    with pytest.raises(ValueError, match="row 2: an edge with this supplier, customer, effective_date and published_at is already stored with different values"):
        import_edges(driver, rows)
    records, _, _ = neo4j_graph.execute_query("MATCH ()-[r:SUPPLIES_TO]->() RETURN count(r) AS n")
    assert records[0]["n"] == 1


def test_name_only_change_is_identical_and_renames(driver, neo4j_graph, tmp_path):
    import_edges(driver, parse_edge_csv(_csv(tmp_path, S1_A)))
    assert import_edges(driver, parse_edge_csv(_csv(tmp_path, S1_A.replace("s1,S1,", "s1,Supplier One,")))) == 0
    _, names = edges_at(driver, date(2024, 6, 30))
    assert names["s1"] == "Supplier One"


def test_constraint_created(driver, neo4j_graph):
    records, _, _ = neo4j_graph.execute_query("SHOW CONSTRAINTS YIELD name RETURN name")
    assert "company_issuer_key" in {r["name"] for r in records}


def _edges(driver, as_of):
    edges, _ = edges_at(driver, as_of)
    return sorted(edges, key=lambda e: (e.supplier_key, e.customer_key))


def test_edges_at_versions(driver, neo4j_graph, tmp_path):
    older = "s1,S1,a,A,0.90,10-K 2022,A is our largest customer.,2022-12-31,2023-03-01"
    import_edges(driver, parse_edge_csv(_csv(tmp_path, S1_A, S2_S1, older)))
    assert _edges(driver, date(2024, 6, 30)) == [Edge("s1", "a", 0.4), Edge("s2", "s1", 0.5)]
    assert _edges(driver, date(2023, 6, 30)) == [Edge("s1", "a", 0.9)]
    assert _edges(driver, date(2024, 3, 1)) == [Edge("s1", "a", 0.4), Edge("s2", "s1", 0.5)]
    assert _edges(driver, date(2024, 2, 1)) == [Edge("s1", "a", 0.9)]


def test_correction_and_later_effective_date(driver, neo4j_graph, tmp_path):
    correction = S1_A.replace("0.40", "0.30").replace("2024-03-01", "2024-05-01")
    late_publication = "s1,S1,a,A,0.90,10-Q,A is our largest customer.,2023-06-30,2024-05-01"
    import_edges(driver, parse_edge_csv(_csv(tmp_path, S1_A, late_publication)))
    assert _edges(driver, date(2024, 6, 30)) == [Edge("s1", "a", 0.4)]
    assert import_edges(driver, parse_edge_csv(_csv(tmp_path, correction))) == 1
    assert _edges(driver, date(2024, 6, 30)) == [Edge("s1", "a", 0.3)]


def test_future_effective_date_ignored(driver, neo4j_graph, tmp_path):
    import_edges(driver, parse_edge_csv(_csv(tmp_path, S1_A.replace("2023-12-31", "2024-08-31"))))
    assert _edges(driver, date(2024, 6, 30)) == []
