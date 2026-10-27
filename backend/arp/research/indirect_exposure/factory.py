from __future__ import annotations

import csv
import functools
import json
import threading
from pathlib import Path

import numpy as np

from arp.config import Settings
from arp.research.indirect_exposure.io_import import EXIOBASE_FD, FD_GROUPS, SPLIT_INDUSTRIES, _read_reference
from arp.research.indirect_exposure.leontief import LeontiefModel

# The tier reads the same `arp io build-full` output as the Value Chain Explorer.
# See docs/superpowers/specs/2026-10-26-io-full-resolution-tier-design.md.

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_data"
NOT_BUILT = "value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR"
NO_MODEL = "No input-output data available: run arp io build-full and set ARP_VALUE_CHAIN_DIR"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


_load_lock = threading.Lock()  # lru_cache lets concurrent misses each load L


@functools.lru_cache(maxsize=1)
def _load(directory: str, manifest_text: str) -> LeontiefModel:
    folder = Path(directory)
    nodes = _read_csv(folder / "nodes.csv")
    live = np.flatnonzero(np.array([float(r["output_meur"]) for r in nodes]) > 0)
    nodes = [nodes[i] for i in live]
    leontief_inverse = np.load(folder / "L.npy", mmap_mode="r")[np.ix_(live, live)]

    icio = _read_reference("icio2025_industries.csv")
    codes = [r["code"] for r in icio] + [c for c, *_ in SPLIT_INDUSTRIES]
    covers: dict[str, set[str]] = {c: set() for c in codes}
    for r in _read_reference("exiobase_ixi_to_icio2025.csv"):
        covers[r["icio_code"]].add(r["exiobase_sector"])
        if r["split_code"] != r["icio_code"]:
            covers[r["split_code"]].add(r["exiobase_sector"])
    sectors = [r["sector"] for r in nodes]

    final_demand = None
    if (folder / "Y.npy").is_file():
        groups = [EXIOBASE_FD[r["category"]] for r in _read_csv(folder / "y_columns.csv")]
        grouping = np.zeros((len(groups), len(FD_GROUPS)))
        for k, g in enumerate(groups):
            if g is not None:
                grouping[k, g] = 1.0
        final_demand = np.load(folder / "Y.npy", mmap_mode="r")[live] @ grouping

    return LeontiefModel(
        codes=codes,
        labels={r["code"]: r["label"] for r in icio} | {c: label for c, label, *_ in SPLIT_INDUSTRIES},
        edition_label=json.loads(manifest_text)["edition"],
        leontief_inverse=leontief_inverse,
        output=np.array([float(r["output_meur"]) for r in nodes]),
        regions=np.array([r["region"] for r in nodes]),
        code_nodes={c: np.array([i for i, s in enumerate(sectors) if s in covers[c]], dtype=np.intp) for c in codes},
        ghg_t_per_meur=np.array([float(r["ghg_t_per_meur"] or 0) for r in nodes]),
        final_demand=final_demand,
        isic_divisions={r["code"]: [d for d in r["isic_divisions"].split(";") if d] for r in icio},
        nace_classes={c: nace.split(";") for c, _, _, nace in SPLIT_INDUSTRIES},
        prompt_codes=[r["code"] for r in icio],
    )


def load_model(directory: Path) -> LeontiefModel:
    """Cached on the manifest text, so a rebuild (new built_at, archive or label) reloads."""
    manifest = Path(directory) / "manifest.json"
    if not manifest.is_file():
        raise ValueError(NOT_BUILT)
    with _load_lock:
        return _load(str(directory), manifest.read_text())


def resolve_indirect_exposure_model(settings: Settings, *, use_sample: bool = False) -> LeontiefModel | None:
    """The single entry point call sites should use: the bundled sample
    build when `use_sample` is set, else the build in ARP_VALUE_CHAIN_DIR,
    else None -- the tier's "off" state. Raises ValueError when the setting
    names a directory without a build.
    """
    if use_sample:
        return load_model(SAMPLE_DIR)
    if settings.value_chain_dir is None:
        return None
    return load_model(settings.value_chain_dir)
