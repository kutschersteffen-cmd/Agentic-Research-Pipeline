from __future__ import annotations

import json
from pathlib import Path

from arp.decision.dataset import Dataset
from arp.schemas.common import now_iso
from arp.schemas.decision import AuditEntry, MechanismConfig
from arp.storage.safe_path import safe_id


class DecisionStore:
    """File-based persistence for decision frameworks and the datasets they
    are applied to.

    Layout: `frameworks/<framework_id>/v<N>.json` per version plus a small
    `latest.json` pointer, and `frameworks/_datasets/<dataset_id>.json` for
    uploaded or derived tables.

    Versions are never edited in place -- the same append-don't-mutate rule
    TaxonomyStore and RunStore's decision log follow. It matters more here
    than anywhere else in this codebase: a ratified framework is the
    justification attached to a decision about a company, and a
    justification that can be rewritten after the fact is not one.
    """

    def __init__(self, frameworks_dir: Path) -> None:
        self.frameworks_dir = frameworks_dir

    # --- frameworks ---

    def _dir(self, framework_id: str) -> Path:
        d = self.frameworks_dir / safe_id(framework_id, label="framework_id")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _version_path(self, framework_id: str, version: int) -> Path:
        return self._dir(framework_id) / f"v{int(version)}.json"

    def _latest_pointer_path(self, framework_id: str) -> Path:
        return self._dir(framework_id) / "latest.json"

    def _audit_path(self, framework_id: str, version: int) -> Path:
        return self._dir(framework_id) / f"v{int(version)}.audit.json"

    def _write(self, config: MechanismConfig) -> None:
        self._version_path(config.framework_id, config.version).write_text(config.model_dump_json(indent=2))
        self._latest_pointer_path(config.framework_id).write_text(json.dumps({"latest_version": config.version}))

    def save(self, config: MechanismConfig, audit: list[AuditEntry] | None = None) -> MechanismConfig:
        """Writes a framework version. Refuses to overwrite a ratified
        version: re-deriving a framework is a new version, not a silent
        replacement of the one someone signed off."""
        existing = self.get(config.framework_id, config.version)
        if existing is not None and existing.ratified:
            raise ValueError(
                f"{config.framework_id} v{config.version} is ratified and cannot be overwritten -- create a new version instead."
            )
        self._write(config)
        if audit is not None:
            self.save_audit(config.framework_id, config.version, audit)
        return config

    def new_version(self, config: MechanismConfig, audit: list[AuditEntry] | None = None) -> MechanismConfig:
        """The only way to change a framework. The previous version stays
        exactly as it was, which is what lets a decision taken last quarter
        still point at the rules that produced it."""
        current = self.get(config.framework_id)
        updated = config.model_copy(
            update={"version": (current.version + 1) if current else 1, "ratified": False, "ratified_at": None, "created_at": now_iso()}
        )
        self._write(updated)
        if audit is not None:
            self.save_audit(updated.framework_id, updated.version, audit)
        return updated

    def save_audit(self, framework_id: str, version: int, audit: list[AuditEntry]) -> None:
        """The derivation and edit trail travels with the version it
        describes -- a framework whose reasoning lives somewhere else is a
        set of numbers nobody can defend."""
        self._audit_path(framework_id, version).write_text(
            json.dumps([json.loads(entry.model_dump_json()) for entry in audit], indent=2)
        )

    def get_audit(self, framework_id: str, version: int | None = None) -> list[AuditEntry]:
        if version is None:
            config = self.get(framework_id)
            if config is None:
                return []
            version = config.version
        path = self._audit_path(framework_id, version)
        if not path.exists():
            return []
        return [AuditEntry.model_validate(row) for row in json.loads(path.read_text())]

    def get(self, framework_id: str, version: int | None = None) -> MechanismConfig | None:
        if version is None:
            pointer = self._latest_pointer_path(framework_id)
            if not pointer.exists():
                return None
            version = json.loads(pointer.read_text()).get("latest_version")
            if version is None:
                return None
        path = self._version_path(framework_id, version)
        if not path.exists():
            return None
        return MechanismConfig.model_validate_json(path.read_text())

    def list_versions(self, framework_id: str) -> list[int]:
        d = self.frameworks_dir / safe_id(framework_id, label="framework_id")
        if not d.exists():
            return []
        return sorted(int(p.stem[1:]) for p in d.glob("v*.json") if p.stem[1:].isdigit())

    def list_frameworks(self) -> list[MechanismConfig]:
        if not self.frameworks_dir.exists():
            return []
        out: list[MechanismConfig] = []
        for d in sorted(self.frameworks_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            config = self.get(d.name)
            if config is not None:
                out.append(config)
        return sorted(out, key=lambda c: c.created_at, reverse=True)

    def ratify(self, framework_id: str, version: int | None = None) -> MechanismConfig:
        config = self.get(framework_id, version)
        if config is None:
            raise ValueError(f"Unknown framework: {framework_id} v{version}")
        if config.ratified:
            return config
        ratified = config.model_copy(update={"ratified": True, "ratified_at": now_iso()})
        self._write(ratified)
        return ratified

    # --- datasets ---

    def dataset_path(self, dataset_id: str) -> Path:
        d = self.frameworks_dir / "_datasets"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{safe_id(dataset_id, label='dataset_id')}.json"

    def save_dataset(self, dataset: Dataset) -> Dataset:
        self.dataset_path(dataset.dataset_id).write_text(dataset.model_dump_json())
        return dataset

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        path = self.dataset_path(dataset_id)
        if not path.exists():
            return None
        return Dataset.model_validate_json(path.read_text())

    def list_datasets(self) -> list[Dataset]:
        d = self.frameworks_dir / "_datasets"
        if not d.exists():
            return []
        datasets = [Dataset.model_validate_json(p.read_text()) for p in d.glob("*.json")]
        return sorted(datasets, key=lambda ds: ds.created_at, reverse=True)
