"""The extraction schema generated from a ratified taxonomy version (one per version), and the
theme-run gate that requires it to be released."""

from __future__ import annotations

from typing import Literal

from arp.db.fields import SchemaRegistry
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition
from arp.schemas.taxonomy import Taxonomy, TaxonomyStatus
from arp.schemas.thematic import ActivityDefinition
from arp.storage.taxonomy_store import TaxonomyStore

Metric = Literal["revenue", "capex", "opex", "rd"]
METRICS: tuple[Metric, ...] = ("revenue", "capex", "opex", "rd")
_LABELS = {"revenue": "revenue", "capex": "capital expenditure (CapEx)", "opex": "operating expenditure (OpEx)"}
_NAMES = {"revenue": "revenue share", "capex": "CapEx share", "opex": "OpEx share", "rd": "R&D intensity"}


def schema_id_for(taxonomy_id: str, version: int) -> str:
    return f"sch_{taxonomy_id}_v{version}"


def field_id_for(schema: DataPointSchema, activity_id: str, metric: Metric) -> str:
    taxonomy_id = schema.schema_id.removeprefix("sch_").rsplit("_v", 1)[0]
    return f"{taxonomy_id}_{activity_id}_{metric}_pct"


def _field(taxonomy: Taxonomy, activity: ActivityDefinition, metric: Metric) -> FieldDefinition:
    if metric == "rd":
        description = (
            f"R&D spend intensity related to the company's investment in: {activity.name} ({activity.in_scope_description})"
        )
        instructions = (
            "Extract an EXPLICITLY stated R&D-spend-as-percentage-of-revenue figure, but only when the "
            "disclosure also names or clearly describes R&D effort specifically tied to this activity (a named "
            "program, product line, or research focus area) -- not just a bare company-wide R&D % with no "
            "connection to this activity. If the company discloses a company-wide R&D % alongside explicit "
            "commentary on this activity's R&D effort, extract the company-wide % and note in raw_value_text "
            "that it is company-wide, not activity-specific. NEVER estimate, infer, or compute a figure that "
            "isn't explicitly stated."
        )
        keywords = [*activity.seed_keywords, "research and development", "R&D"]
    else:
        label = _LABELS[metric]
        description = (
            f"The percentage of the company's total {label} attributable to: {activity.name} ({activity.in_scope_description})"
        )
        instructions = (
            f"Extract an EXPLICITLY stated percentage of total {label} attributable to this specific "
            f"activity, as disclosed by the company (e.g. a stated segment revenue share, a 'X% of revenue came "
            f"from...' statement). Express `value` as a number between 0 and 100 (e.g. 18.5 for 18.5%). If only a "
            f"dollar figure is stated with no percentage and no computable total, leave `value` null and put the "
            f"raw figure in raw_value_text -- NEVER estimate, infer, or compute a percentage from unrelated totals."
        )
        keywords = [*activity.seed_keywords, metric]
    return FieldDefinition(
        field_id=f"{taxonomy.taxonomy_id}_{activity.activity_id}_{metric}_pct",
        name=f"{activity.name}: {_NAMES[metric]}",
        description=description,
        data_type=FieldDataType.PERCENTAGE,
        unit="%",
        extraction_instructions=instructions,
        required=False,
        seed_keywords=keywords,
        version=taxonomy.version,
    )


def build_taxonomy_schema(taxonomy: Taxonomy) -> DataPointSchema:
    """Four percentage fields per activity, in activity order. Pure: same version, same schema."""
    if taxonomy.status != TaxonomyStatus.RATIFIED:
        raise ValueError(f"Taxonomy {taxonomy.taxonomy_id} v{taxonomy.version} is a draft; ratify it first.")
    return DataPointSchema(
        schema_id=schema_id_for(taxonomy.taxonomy_id, taxonomy.version),
        name=f"{taxonomy.name} v{taxonomy.version}",
        description=f"Generated from taxonomy {taxonomy.taxonomy_id} v{taxonomy.version}.",
        fields=[_field(taxonomy, a, m) for a in taxonomy.theme.activities for m in METRICS],
    )


class ThemeRunRefused(ValueError):
    """A theme run may not start: `status` is the HTTP status the API answers with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


THEME_NOT_ALLOWED = "Theme runs start from a taxonomy version: send taxonomy_id, not theme."


def released_run_schema(
    store: TaxonomyStore, registry: SchemaRegistry, taxonomy_id: str, version: int | None
) -> tuple[Taxonomy, DataPointSchema]:
    """The one gate every theme run passes: a ratified taxonomy version whose generated schema's
    latest registry version is released. Returns that version and that schema."""
    taxonomy = store.get(taxonomy_id, version)
    if taxonomy is None:
        raise ThemeRunRefused(404, f"Taxonomy not found: {taxonomy_id}")
    if taxonomy.status != TaxonomyStatus.RATIFIED:
        raise ThemeRunRefused(
            409, f"Taxonomy {taxonomy_id} v{taxonomy.version} is a draft; ratify it and release its schema first."
        )
    schema_id = schema_id_for(taxonomy_id, taxonomy.version)
    try:
        schema = registry.get(schema_id)
    except KeyError:
        schema = None
    if schema is None or not schema.release_flag:
        raise ThemeRunRefused(409, f"Schema {schema_id} is not released; release it first.")
    return taxonomy, schema
