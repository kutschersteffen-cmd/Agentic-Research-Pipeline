from __future__ import annotations

import hashlib
from pathlib import Path

from arp.replication._wide_csv import read_wide_csv
from arp.replication.characteristics_data import CsvCharacteristicSource
from arp.replication.price_data import CsvPriceSource
from arp.signal_lab.methods.base import MethodInput
from arp.signal_lab.registry import Recipe
from arp.signal_lab.text_store import TextRecord


def data_version_for(
    item_ids: list[str], price_bytes: bytes, panel_bytes: dict[str, bytes], history_from: str | None
) -> str:
    digest = hashlib.sha256("\n".join(sorted(item_ids)).encode())
    digest.update(price_bytes)
    for name in sorted(panel_bytes):
        digest.update(panel_bytes[name])
    if history_from is not None:  # absent for runs without history, so their ids stay what they were
        digest.update(f"\nhistory_from={history_from}".encode())
    return digest.hexdigest()[:12]


def load_inputs(
    recipe: Recipe,
    prices: Path,
    *,
    panels: dict[str, Path] | None = None,
    texts: list[TextRecord] | None = None,
    history_from: str | None = None,
) -> tuple[MethodInput, str]:
    """Loads prices and panels from `history_from` (default the window start) to the window end. History before
    the window feeds methods only; evidence is still cut to the recipe window."""
    panel_files = panels or {}
    texts = texts or []
    dates, columns = read_wide_csv(prices)
    if recipe.window_start < dates[0] or recipe.window_end > dates[-1]:
        raise ValueError(
            f"recipe window {recipe.window_start}..{recipe.window_end} is outside the price file {dates[0]}..{dates[-1]}"
        )
    if history_from is not None:
        if history_from < dates[0] or history_from > dates[-1]:
            raise ValueError(f"history_from {history_from} is outside the price file {dates[0]}..{dates[-1]}")
        if history_from not in dates:  # an off-grid date loads the same rows as the next one but hashes differently
            raise ValueError(f"history_from {history_from} is not one of the price file's dates")
        if history_from > recipe.window_start:
            raise ValueError(f"history_from {history_from} is after the window start {recipe.window_start}")
    start = history_from or recipe.window_start
    issuers = list(columns)
    price_panel = CsvPriceSource(prices).get_monthly_returns(issuers, start, recipe.window_end)
    panel_data = {
        name: CsvCharacteristicSource(path).get_values(issuers, start, recipe.window_end)
        for name, path in panel_files.items()
    }
    data_version = data_version_for(
        [t.item_id for t in texts], prices.read_bytes(), {n: p.read_bytes() for n, p in panel_files.items()}, history_from
    )
    return MethodInput(texts=texts, prices=price_panel, panels=panel_data), data_version
