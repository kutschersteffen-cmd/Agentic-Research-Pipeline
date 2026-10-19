from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from arp.research.indirect_exposure.icio_loader import ICIOData


def compute_technical_coefficients(icio: ICIOData) -> np.ndarray:
    """A[i, j] = intermediate input from industry i required per unit of
    industry j's total output. Column-normalizes the raw flow matrix by
    each industry's total_output; a column for an industry with zero
    reported output is left as all zeros rather than dividing by zero.
    """
    n = len(icio.codes)
    a = np.zeros((n, n), dtype=float)
    for j, code in enumerate(icio.codes):
        denom = icio.total_output.get(code, 0.0)
        if denom > 0:
            a[:, j] = icio.matrix[:, j] / denom
    return a


def compute_leontief_inverse(a: np.ndarray) -> np.ndarray:
    """L = (I - A)^-1. Entry L[i, j] is the total (direct + indirect)
    output required from industry i to satisfy one unit of final demand
    for industry j -- the multi-hop supply-chain propagation this whole
    tier exists to capture.
    """
    n = a.shape[0]
    return np.linalg.inv(np.eye(n) - a)


@dataclass
class RegionalModel:
    """The region-resolved model from regional_output.csv/regional_flows.csv:
    one industry per (region group, code), in file order."""

    groups: list[str]
    index: dict[tuple[str, str], int]
    leontief_inverse: np.ndarray


@dataclass
class LeontiefModel:
    codes: list[str]
    labels: dict[str, str]
    leontief_inverse: np.ndarray  # shape (n, n)
    edition_label: str
    # Optional extras from an imported table's directory (factory.attach_extras);
    # empty/None for hand-prepared files and the bundled samples.
    isic_divisions: dict[str, list[str]] = field(default_factory=dict)
    nace_classes: dict[str, list[str]] = field(default_factory=dict)
    total_output: np.ndarray | None = None
    final_demand: np.ndarray | None = None  # shape (n, 4), arp.research.indirect_exposure.io_import.FD_GROUPS
    ghg_kg: np.ndarray | None = None
    regional: RegionalModel | None = None

    def index_of(self, code: str) -> int | None:
        try:
            return self.codes.index(code)
        except ValueError:
            return None

    def industry_reference_list(self) -> list[tuple[str, str]]:
        """(code, label) pairs in this model's order -- the reference list
        for industry-anchored taxonomy drafting (see
        arp/research/activity_generator.py) and for the core-sector /
        company-industry classification prompts.
        """
        return [(code, self.labels.get(code, "")) for code in self.codes]

    def industry_prompt_list(self) -> str:
        """The same reference list rendered as the "code: label" block the
        classification prompts tell the model to pick from. Lives here, with
        codes and labels, because core_sectors.py and company_mapper.py each
        had their own character-identical copy -- two agents classifying
        against the same closed list must see it rendered the same way.
        """
        return "\n".join(f"{code}: {label}" for code, label in self.industry_reference_list())


def build_model(icio: ICIOData, edition_label: str) -> LeontiefModel:
    a = compute_technical_coefficients(icio)
    leontief_inverse = compute_leontief_inverse(a)
    return LeontiefModel(codes=icio.codes, labels=icio.labels, leontief_inverse=leontief_inverse, edition_label=edition_label)


def _cache_path(cache_dir: Path, edition_label: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in edition_label)
    return cache_dir / f"leontief_{safe}.npz"


def _source_hash(icio: ICIOData) -> str:
    h = hashlib.sha256("\n".join(icio.codes).encode())
    h.update(np.ascontiguousarray(icio.matrix, dtype=float).tobytes())
    h.update(np.array([icio.total_output.get(c, 0.0) for c in icio.codes], dtype=float).tobytes())
    return h.hexdigest()


def save_model_cache(model: LeontiefModel, cache_dir: Path, source_hash: str = "") -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    codes_arr = np.array(model.codes, dtype="<U64")
    labels_arr = np.array([model.labels.get(c, "") for c in model.codes], dtype="<U256")
    np.savez(
        _cache_path(cache_dir, model.edition_label),
        codes=codes_arr,
        labels=labels_arr,
        leontief_inverse=model.leontief_inverse,
        source_hash=np.array(source_hash),
    )


def load_model_cache(cache_dir: Path, edition_label: str, source_hash: str | None = None) -> LeontiefModel | None:
    """`source_hash` given: a cache built from different inputs (a re-import
    under the same edition label) counts as missing."""
    path = _cache_path(cache_dir, edition_label)
    if not path.exists():
        return None
    data = np.load(path, allow_pickle=False)
    if source_hash is not None and ("source_hash" not in data or str(data["source_hash"]) != source_hash):
        return None
    codes = [str(c) for c in data["codes"]]
    labels = {c: str(label) for c, label in zip(codes, data["labels"], strict=True)}
    return LeontiefModel(codes=codes, labels=labels, leontief_inverse=data["leontief_inverse"], edition_label=edition_label)


def build_or_load_model(icio: ICIOData, edition_label: str, cache_dir: Path, force_rebuild: bool = False) -> LeontiefModel:
    """Computing the Leontief inverse is the one non-trivial cost in this
    tier; it depends only on the ICIO edition, never on the company universe
    or theme, so it's computed once per edition and cached to disk.
    """
    source_hash = _source_hash(icio)
    if not force_rebuild:
        cached = load_model_cache(cache_dir, edition_label, source_hash)
        if cached is not None and cached.codes == icio.codes:
            return cached
    model = build_model(icio, edition_label)
    save_model_cache(model, cache_dir, source_hash)
    return model
