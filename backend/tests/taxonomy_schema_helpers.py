from arp.research.taxonomy_schema import build_taxonomy_schema
from arp.schemas.datapoints import DataPointSchema
from arp.schemas.taxonomy import DerivationMethod, Taxonomy, TaxonomyStatus
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition


def released_schema(*activities: ActivityDefinition) -> DataPointSchema:
    """The generated schema of a ratified one-theme taxonomy, flagged released, as a theme run receives it."""
    theme = ThemeDefinition(name="T", description="", activities=list(activities))
    taxonomy = Taxonomy(taxonomy_id="tax_t", name="T", theme=theme, derivation_method=DerivationMethod.MANUAL, status=TaxonomyStatus.RATIFIED)
    return build_taxonomy_schema(taxonomy).model_copy(update={"release_flag": True})


def registered_schema(*activities: ActivityDefinition) -> DataPointSchema:
    """The same schema saved and released in the SchemaRegistry (needs the `pg` fixture), as a resumed run loads it."""
    from arp.config import Settings
    from arp.db.fields import SchemaRegistry

    registry = SchemaRegistry(Settings().postgres_dsn)
    saved = registry.save(released_schema(*activities))
    return registry.release(saved.schema_id, saved.version, released_by="own")
