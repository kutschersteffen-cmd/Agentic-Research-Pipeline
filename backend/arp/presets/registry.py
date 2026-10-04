"""Preset DataPointSchemas, installed into the SchemaRegistry on demand."""

from __future__ import annotations

from collections.abc import Callable

from arp.schemas.datapoints import DataPointSchema
from arp.storage.schema_registry import SchemaRegistry

PRESETS: dict[str, Callable[[], DataPointSchema]] = {}


def install_preset(preset_id: str, registry: SchemaRegistry) -> DataPointSchema:
    """Saves the preset; the registry only versions on a content change, so repeats are no-ops."""
    return registry.save(PRESETS[preset_id]())
