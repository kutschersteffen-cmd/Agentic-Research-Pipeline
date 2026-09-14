from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from arp.research.indirect_exposure.icio_loader import ICIOData, read_industries

_SAMPLE_DIR = Path(__file__).resolve().parent / "sample_data"
_SAMPLE_FLOWS = _SAMPLE_DIR / "exiobase_flows.csv"
_SAMPLE_INDUSTRIES = _SAMPLE_DIR / "industries.csv"


def build_icio_from_long_format(
    flows_path: Path,
    industries_path: Path,
    *,
    supplier_code_col: str = "supplier_isic_code",
    user_code_col: str = "user_isic_code",
    value_col: str = "value",
) -> ICIOData:
    """Builds an ICIOData from a long-format flows table -- one row per
    (supplier industry, user industry[, region, ...]) flow, as a real
    EXIOBASE extract realistically arrives, rather than the pre-squared
    matrix icio_loader.load_icio expects. Any extra columns (region codes,
    etc.) are ignored: rows are grouped by (supplier_code, user_code) and
    their values summed, collapsing region detail into the same aggregate-
    over-countries simplification icio_loader.ICIOData already documents.

    This assumes the caller has already mapped EXIOBASE's native product/
    sector classification to ISIC Rev.4 division codes -- that crosswalk is
    not attempted here (see docs/METHODOLOGY.md and sample_data/README.md).

    industries_path uses the exact same isic_code,label,total_output format
    load_icio's companion file uses (total_output must already be
    aggregated across regions by the caller).

    Raises ValueError if a flows-file code isn't present in industries.csv
    -- an unmapped code would otherwise silently disappear from the
    aggregate, corrupting every downstream exposure number, the same
    fail-fast philosophy as icio_loader.load_icio's ordering check.
    """
    codes, labels, total_output = read_industries(industries_path)
    code_set = set(codes)
    index_of = {code: i for i, code in enumerate(codes)}

    n = len(codes)
    matrix = np.zeros((n, n), dtype=float)

    with flows_path.open(newline="") as f:
        reader = csv.DictReader(f)
        missing_cols = {supplier_code_col, user_code_col, value_col} - set(reader.fieldnames or [])
        if missing_cols:
            raise ValueError(f"{flows_path} is missing required column(s): {sorted(missing_cols)}")
        for row in reader:
            supplier_code = row[supplier_code_col].strip()
            user_code = row[user_code_col].strip()
            if supplier_code not in code_set:
                raise ValueError(f"{flows_path} references unmapped supplier code {supplier_code!r} (not in {industries_path})")
            if user_code not in code_set:
                raise ValueError(f"{flows_path} references unmapped user code {user_code!r} (not in {industries_path})")
            matrix[index_of[supplier_code], index_of[user_code]] += float(row[value_col])

    return ICIOData(codes=codes, labels=labels, total_output=total_output, matrix=matrix)


def load_sample_exiobase() -> ICIOData:
    """The bundled illustrative EXIOBASE-shaped sample: the same
    illustrative economy as icio_loader.load_sample_icio(), re-expressed
    as region-resolved long-format flows (each nonzero cell of the OECD
    sample split across two illustrative regions, EU/ROW, summing back to
    the original value exactly) -- proves the aggregation arithmetic here
    is correct, not a claim about real EXIOBASE data. See
    sample_data/README.md.
    """
    return build_icio_from_long_format(_SAMPLE_FLOWS, _SAMPLE_INDUSTRIES)
