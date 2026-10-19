from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from arp.config import Settings
from arp.research.indirect_exposure.exiobase_loader import build_icio_from_long_format, load_sample_exiobase
from arp.research.indirect_exposure.icio_loader import load_icio, load_sample_icio
from arp.research.indirect_exposure.io_import import FD_GROUPS
from arp.research.indirect_exposure.leontief import (
    LeontiefModel,
    RegionalModel,
    build_or_load_model,
    compute_leontief_inverse,
)

_PATH_VARS = {
    "icio": ("ARP_ICIO_MATRIX_PATH", "ARP_ICIO_INDUSTRIES_PATH"),
    "exiobase": ("ARP_EXIOBASE_FLOWS_PATH", "ARP_EXIOBASE_INDUSTRIES_PATH"),
}


def build_leontief_model(settings: Settings, *, use_sample: bool = False) -> LeontiefModel | None:
    """Builds (or loads from cache) the Leontief model the indirect-exposure
    tier needs, sourced from the OECD-ICIO-shaped tier.

    Returns None -- the tier's "off" state -- unless either `use_sample` is
    set (the bundled illustrative dataset, for demos) or both
    `icio_matrix_path`/`icio_industries_path` are configured with a real
    extract. This keeps the tier strictly opt-in: existing runs are
    unaffected unless a caller explicitly asks for it.
    """
    cache_dir = settings.cache_dir / "leontief"
    if use_sample:
        return build_or_load_model(load_sample_icio(), "sample", cache_dir)
    if not settings.icio_matrix_path or not settings.icio_industries_path:
        return None
    icio = load_icio(settings.icio_matrix_path, settings.icio_industries_path)
    return attach_extras(build_or_load_model(icio, settings.icio_edition_label, cache_dir), settings.icio_industries_path)


def build_exiobase_model(settings: Settings, *, use_sample: bool = False) -> LeontiefModel | None:
    """EXIOBASE-sourced sibling of build_leontief_model -- same opt-in-only
    contract and cache_dir, keyed by a distinct edition_label so a cached
    EXIOBASE-sourced model can't collide with an ICIO-sourced one.
    """
    cache_dir = settings.cache_dir / "leontief"
    if use_sample:
        return build_or_load_model(load_sample_exiobase(), "exiobase-sample", cache_dir)
    if not settings.exiobase_flows_path or not settings.exiobase_industries_path:
        return None
    icio = build_icio_from_long_format(settings.exiobase_flows_path, settings.exiobase_industries_path)
    return attach_extras(
        build_or_load_model(icio, settings.exiobase_edition_label, cache_dir), settings.exiobase_industries_path
    )


def active_io_source(settings: Settings) -> str | None:
    """`icio`, `exiobase` or None (tier off), per ARP_IO_SOURCE. An explicit
    source whose two paths aren't both set raises ValueError."""
    configured = {
        "icio": bool(settings.icio_matrix_path and settings.icio_industries_path),
        "exiobase": bool(settings.exiobase_flows_path and settings.exiobase_industries_path),
    }
    if settings.io_source == "auto":
        return next((s for s in ("icio", "exiobase") if configured[s]), None)
    if not configured[settings.io_source]:
        a, b = _PATH_VARS[settings.io_source]
        raise ValueError(f"io source {settings.io_source} is not configured: set {a} and {b}")
    return settings.io_source


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _leontief_from_flows(z: np.ndarray, x: np.ndarray) -> np.ndarray:
    a = np.divide(z, x, out=np.zeros_like(z), where=x > 0)
    return compute_leontief_inverse(a)


def attach_extras(model: LeontiefModel, industries_path: Path) -> LeontiefModel:
    try:
        return _attach_extras(model, industries_path)
    except KeyError as exc:
        raise ValueError(f"{industries_path.parent}: side file does not match industries.csv: unknown {exc}") from exc


def _attach_extras(model: LeontiefModel, industries_path: Path) -> LeontiefModel:
    """Adds the optional parts of an imported table (see io_import.py) found
    next to `industries_path`: ISIC divisions/NACE classes, final demand,
    GHG and the region-resolved model. Absent columns or files leave the
    matching field empty, so hand-prepared files behave as before."""
    rows = {r["isic_code"].strip(): r for r in _read_csv(industries_path)}
    index = {c: i for i, c in enumerate(model.codes)}
    model.isic_divisions = {c: [d for d in (r.get("isic_divisions") or "").split(";") if d] for c, r in rows.items()}
    model.nace_classes = {c: [d for d in (r.get("nace_classes") or "").split(";") if d] for c, r in rows.items()}
    model.total_output = np.array([float(rows[c]["total_output"]) for c in model.codes])

    folder = industries_path.parent
    if (folder / "final_demand.csv").exists():
        model.final_demand = np.zeros((len(model.codes), len(FD_GROUPS)))
        for r in _read_csv(folder / "final_demand.csv"):
            model.final_demand[index[r["isic_code"]]] = [float(r[g]) for g in FD_GROUPS]
    if (folder / "ghg.csv").exists():
        model.ghg_kg = np.zeros(len(model.codes))
        for r in _read_csv(folder / "ghg.csv"):
            model.ghg_kg[index[r["isic_code"]]] = float(r["kg_co2e"])
    if (folder / "regional_output.csv").exists() and (folder / "regional_flows.csv").exists():
        output = _read_csv(folder / "regional_output.csv")
        reg_index = {(r["region"], r["isic_code"]): i for i, r in enumerate(output)}
        x = np.array([float(r["total_output"]) for r in output])
        z = np.zeros((len(output), len(output)))
        for r in _read_csv(folder / "regional_flows.csv"):
            i = reg_index[(r["supplier_region"], r["supplier_isic_code"])]
            j = reg_index[(r["user_region"], r["user_isic_code"])]
            z[i, j] += float(r["value"])
        groups = list(dict.fromkeys(r["region"] for r in output))
        model.regional = RegionalModel(groups=groups, index=reg_index, leontief_inverse=_leontief_from_flows(z, x))
    return model


def resolve_indirect_exposure_model(
    settings: Settings, *, use_sample_icio: bool = False, use_sample_exiobase: bool = False
) -> LeontiefModel | None:
    """The single entry point call sites should use: a run's indirect-
    exposure tier is backed by at most one source at a time.

    Raises ValueError if both sample flags are set (ambiguous -- almost
    certainly a caller mistake). If neither sample flag is set, tries the
    ICIO source first, then EXIOBASE, so a deployment with both configured
    keeps today's ICIO-only behavior unless it explicitly opts into
    EXIOBASE via one of the sample flags.
    """
    if use_sample_icio and use_sample_exiobase:
        raise ValueError("Only one of use_sample_icio / use_sample_exiobase may be set at a time.")
    if use_sample_icio:
        return build_leontief_model(settings, use_sample=True)
    if use_sample_exiobase:
        return build_exiobase_model(settings, use_sample=True)
    source = active_io_source(settings)
    if source == "icio":
        return build_leontief_model(settings)
    if source == "exiobase":
        return build_exiobase_model(settings)
    return None
