"""A run's `universe_path` from a request: only a saved universe file is read."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException

from arp.config import Settings
from arp.schemas.common import CompanyRef
from arp.storage.safe_path import file_inside
from arp.universe import UniverseRejected, load_company_universe

logger = logging.getLogger(__name__)

NOT_SAVED = "Universe file must be a saved universe."
UNREADABLE = "Could not read the universe file."


def saved_universe_file(universe_path: str, settings: Settings) -> Path | None:
    return file_inside(universe_path, settings.runs_dir / "_universes")


def require_saved_universe(universe_path: str, settings: Settings) -> Path:
    """The resolved saved universe file, else 400. The answer never names the path."""
    path = saved_universe_file(universe_path, settings)
    if path is None:
        logger.info("universe_path refused: %s", universe_path)
        raise HTTPException(400, NOT_SAVED)
    return path


def load_saved_universe(universe_path: str, settings: Settings) -> list[CompanyRef]:
    """Loads a saved universe: the loader's own sentence when it rejects the
    file, else 400 `Could not read the universe file.` for any other failure."""
    path = require_saved_universe(universe_path, settings)
    try:
        return load_company_universe(path)
    except UniverseRejected:
        raise
    except Exception as exc:  # noqa: BLE001 - any unreadable file is the caller's 400
        logger.warning("universe file unreadable: %s", exc)
        raise HTTPException(400, UNREADABLE) from exc


def check_schedule_universe(universe_path: str | None, current: str | None, settings: Settings) -> None:
    """A schedule's universe_path may be empty, a saved universe file, or the
    string the schedule holds now (an operator's env setting keeps working)."""
    if universe_path and universe_path != current:
        require_saved_universe(universe_path, settings)
