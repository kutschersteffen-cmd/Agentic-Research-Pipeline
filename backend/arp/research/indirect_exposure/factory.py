from __future__ import annotations

from arp.config import Settings
from arp.research.indirect_exposure.exiobase_loader import build_icio_from_long_format, load_sample_exiobase
from arp.research.indirect_exposure.icio_loader import load_icio, load_sample_icio
from arp.research.indirect_exposure.leontief import LeontiefModel, build_or_load_model


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
    return build_or_load_model(icio, settings.icio_edition_label, cache_dir)


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
    return build_or_load_model(icio, settings.exiobase_edition_label, cache_dir)


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
    return build_leontief_model(settings) or build_exiobase_model(settings)
