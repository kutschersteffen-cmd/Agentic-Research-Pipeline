from __future__ import annotations

import json
from pathlib import Path

from arp.schemas.common import now_iso
from arp.schemas.taxonomy import DerivationMethod, Taxonomy, TaxonomyStatus
from arp.schemas.thematic import ThemeDefinition
from arp.storage.safe_path import safe_id


class TaxonomyStore:
    """File-based persistence for the taxonomy library.

    Layout: `taxonomies/<taxonomy_id>/v<N>.json` per version, plus a small
    `latest.json` pointer -- the same append-don't-mutate philosophy as
    RunStore's review-decision log: editing a taxonomy creates a new
    version rather than overwriting history, so a ratified version stays
    exactly what was ratified even after later edits.
    """

    def __init__(self, taxonomies_dir: Path) -> None:
        self.taxonomies_dir = taxonomies_dir

    def _dir(self, taxonomy_id: str) -> Path:
        d = self.taxonomies_dir / safe_id(taxonomy_id, label="taxonomy_id")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _version_path(self, taxonomy_id: str, version: int) -> Path:
        return self._dir(taxonomy_id) / f"v{version}.json"

    def _latest_pointer_path(self, taxonomy_id: str) -> Path:
        return self._dir(taxonomy_id) / "latest.json"

    def _write(self, taxonomy: Taxonomy) -> None:
        self._version_path(taxonomy.taxonomy_id, taxonomy.version).write_text(taxonomy.model_dump_json(indent=2))
        self._latest_pointer_path(taxonomy.taxonomy_id).write_text(json.dumps({"latest_version": taxonomy.version}))

    def create(
        self,
        name: str,
        theme: ThemeDefinition,
        derivation_method: DerivationMethod,
        source_notes: str = "",
    ) -> Taxonomy:
        taxonomy = Taxonomy(name=name, version=1, theme=theme, derivation_method=derivation_method, source_notes=source_notes)
        self._write(taxonomy)
        return taxonomy

    def new_version(
        self,
        taxonomy_id: str,
        theme: ThemeDefinition,
        derivation_method: DerivationMethod,
        source_notes: str = "",
    ) -> Taxonomy:
        current = self.get(taxonomy_id)
        if current is None:
            raise ValueError(f"Unknown taxonomy_id: {taxonomy_id}")
        updated = Taxonomy(
            taxonomy_id=taxonomy_id,
            name=current.name,
            version=current.version + 1,
            theme=theme,
            derivation_method=derivation_method,
            source_notes=source_notes,
            based_on_version=current.version,
        )
        self._write(updated)
        return updated

    def get(self, taxonomy_id: str, version: int | None = None) -> Taxonomy | None:
        if version is None:
            pointer_path = self._latest_pointer_path(taxonomy_id)
            if not pointer_path.exists():
                return None
            version = json.loads(pointer_path.read_text())["latest_version"]
        path = self._version_path(taxonomy_id, version)
        if not path.exists():
            return None
        return Taxonomy.model_validate_json(path.read_text())

    def list_versions(self, taxonomy_id: str) -> list[Taxonomy]:
        d = self.taxonomies_dir / safe_id(taxonomy_id, label="taxonomy_id")
        if not d.exists():
            return []
        versions = []
        for p in d.glob("v*.json"):
            try:
                versions.append(Taxonomy.model_validate_json(p.read_text()))
            except (json.JSONDecodeError, ValueError):
                continue
        return sorted(versions, key=lambda t: t.version)

    def list_all(self) -> list[Taxonomy]:
        """The latest version of every taxonomy in the library."""
        if not self.taxonomies_dir.exists():
            return []
        latest: list[Taxonomy] = []
        for d in sorted(self.taxonomies_dir.iterdir()):
            if not d.is_dir():
                continue
            taxonomy = self.get(d.name)
            if taxonomy is not None:
                latest.append(taxonomy)
        return latest

    def ratify(self, taxonomy_id: str, version: int, ratified_by: str) -> Taxonomy:
        """Marks a specific version as ratified in place -- this is a status
        change on an already-existing, already-immutable version record,
        not a new edit, so it doesn't create a new version.
        """
        taxonomy = self.get(taxonomy_id, version)
        if taxonomy is None:
            raise ValueError(f"Unknown taxonomy_id/version: {taxonomy_id} v{version}")
        ratified = taxonomy.model_copy(
            update={"status": TaxonomyStatus.RATIFIED, "ratified_by": ratified_by, "ratified_at": now_iso()}
        )
        self._version_path(taxonomy_id, version).write_text(ratified.model_dump_json(indent=2))
        return ratified
