"""Preset DataPointSchemas, installed into the SchemaRegistry on demand."""

from __future__ import annotations

from collections.abc import Callable

from arp.presets.eu_taxonomy import SCHEMA_ID as EU_TAXONOMY_SCHEMA_ID
from arp.presets.eu_taxonomy import build_eu_taxonomy_schema
from arp.presets.green import SCHEMA_ID as GREEN_SCHEMA_ID
from arp.presets.green import build_green_schema
from arp.schemas.datapoints import DataPointSchema
from arp.storage.schema_registry import SchemaRegistry

PRESETS: dict[str, Callable[[], DataPointSchema]] = {
    GREEN_SCHEMA_ID: build_green_schema,
    EU_TAXONOMY_SCHEMA_ID: build_eu_taxonomy_schema,
}


def install_preset(preset_id: str, registry: SchemaRegistry) -> DataPointSchema:
    """Saves the preset; the registry only versions on a content change, so repeats are no-ops."""
    return registry.save(PRESETS[preset_id]())
