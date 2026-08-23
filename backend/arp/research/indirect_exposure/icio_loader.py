from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_SAMPLE_DIR = Path(__file__).resolve().parent / "sample_data"
_SAMPLE_MATRIX = _SAMPLE_DIR / "icio_matrix.csv"
_SAMPLE_INDUSTRIES = _SAMPLE_DIR / "industries.csv"


@dataclass
class ICIOData:
    """A parsed industry x industry intermediate-flows table.

    `matrix[i, j]` is the value flowing from industry `codes[i]` (supplier)
    to industry `codes[j]` (user), matching the OECD ICIO row=supplier,
    column=user convention. This is deliberately an aggregate-over-countries
    simplification of the real (much larger) country x industry x country x
    industry OECD release -- see sample_data/README.md.
    """

    codes: list[str]
    labels: dict[str, str]
    total_output: dict[str, float]
    matrix: np.ndarray  # shape (n, n)

    def index_of(self, code: str) -> int | None:
        try:
            return self.codes.index(code)
        except ValueError:
            return None


def read_industries(path: Path) -> tuple[list[str], dict[str, str], dict[str, float]]:
    """Parses an industries.csv (isic_code,label,total_output). Public --
    shared with exiobase_loader.py's long-format loader, which reuses this
    exact companion-file format rather than duplicating a parser."""
    codes: list[str] = []
    labels: dict[str, str] = {}
    total_output: dict[str, float] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            code = row["isic_code"].strip()
            codes.append(code)
            labels[code] = row["label"].strip()
            total_output[code] = float(row["total_output"])
    return codes, labels, total_output


def _read_matrix(path: Path, expected_codes: list[str]) -> np.ndarray:
    with path.open(newline="") as f:
        rows = list(csv.reader(f))
    header = [c.strip() for c in rows[0][1:]]
    if header != expected_codes:
        raise ValueError(
            f"icio_matrix.csv column order {header} does not match industries.csv order {expected_codes}"
        )
    n = len(expected_codes)
    matrix = np.zeros((n, n), dtype=float)
    for i, row in enumerate(rows[1:]):
        row_code = row[0].strip()
        if row_code != expected_codes[i]:
            raise ValueError(f"icio_matrix.csv row {i} label {row_code!r} does not match expected {expected_codes[i]!r}")
        matrix[i, :] = [float(v) for v in row[1:]]
    return matrix


def load_icio(matrix_path: Path, industries_path: Path) -> ICIOData:
    """Loads a matched pair of (industries.csv, icio_matrix.csv). Raises
    ValueError if the two files' industry orderings don't agree -- a
    mismatch here would silently corrupt every downstream exposure number,
    so it's checked eagerly rather than assumed.
    """
    codes, labels, total_output = read_industries(industries_path)
    matrix = _read_matrix(matrix_path, codes)
    return ICIOData(codes=codes, labels=labels, total_output=total_output, matrix=matrix)


def load_sample_icio() -> ICIOData:
    """The small bundled illustrative dataset -- for demos and tests, not
    production accuracy. See sample_data/README.md."""
    return load_icio(_SAMPLE_MATRIX, _SAMPLE_INDUSTRIES)
