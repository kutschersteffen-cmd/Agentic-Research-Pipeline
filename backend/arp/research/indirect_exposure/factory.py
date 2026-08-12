from __future__ import annotations

from arp.config import Settings
from arp.research.indirect_exposure.icio_loader import load_icio, load_sample_icio
from arp.research.indirect_exposure.leontief import LeontiefModel, build_or_load_model


def build_leontief_model(settings: Settings, *, use_sample: bool = False) -> LeontiefModel | None:
    """Builds (or loads from cache) the Leontief model the indirect-exposure
    tier needs.

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
