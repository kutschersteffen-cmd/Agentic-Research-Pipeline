from __future__ import annotations

import json
from pathlib import Path

from arp.schemas.index import ConstructionSpec, IndexCalibration, IndexState, ReviewResult
from arp.storage.atomic_io import atomic_write_text
from arp.storage.safe_path import safe_id


class IndexStore:
    """File-based persistence for index construction calibrations and the
    reviews run from them.

    Calibrations are versioned append-only, exactly like the taxonomy
    library: editing one writes a new version rather than overwriting
    history, so a calibration a committee approved stays byte-for-byte what
    they approved. Each version carries `effective_from`, and
    `resolve_for_date` returns the version *in force on the review date*
    rather than the latest one -- without that, re-running a 2024 review
    today would silently run it under 2026 parameters.

    Layout:
        indices/calibrations/<calibration_id>/v<N>.json   one per version
        indices/calibrations/<calibration_id>/latest.json pointer + name
        indices/<index_id>/reviews/<review_date>.json     ReviewResult
        indices/<index_id>/state/<review_date>.json       IndexState carried forward
    """

    def __init__(self, indices_dir: Path) -> None:
        self.indices_dir = indices_dir

    # ---------------------------------------------------------------- paths

    def _calibration_dir(self, calibration_id: str) -> Path:
        d = self.indices_dir / "calibrations" / safe_id(calibration_id, label="calibration_id")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _index_dir(self, index_id: str, sub: str) -> Path:
        d = self.indices_dir / safe_id(index_id, label="index_id") / sub
        d.mkdir(parents=True, exist_ok=True)
        return d

    # --------------------------------------------------------- calibrations

    def create_calibration(
        self,
        name: str,
        spec: ConstructionSpec,
        *,
        effective_from: str,
        notes: str = "",
        approved_by: list[str] | None = None,
    ) -> IndexCalibration:
        calibration = IndexCalibration(
            name=name,
            version=1,
            effective_from=effective_from,
            notes=notes,
            approved_by=approved_by or [],
            spec=spec,
        )
        self._write_calibration(calibration)
        return calibration

    def new_calibration_version(
        self,
        calibration_id: str,
        spec: ConstructionSpec,
        *,
        effective_from: str,
        notes: str = "",
        approved_by: list[str] | None = None,
    ) -> IndexCalibration:
        current = self.get_calibration(calibration_id)
        if current is None:
            raise ValueError(f"Unknown calibration_id: {calibration_id}")
        if effective_from < current.effective_from:
            raise ValueError(
                f"effective_from {effective_from} precedes version {current.version}'s {current.effective_from}; "
                "calibration versions are forward-only so a later edit cannot rewrite an earlier review"
            )
        updated = IndexCalibration(
            calibration_id=calibration_id,
            name=current.name,
            version=current.version + 1,
            based_on_version=current.version,
            effective_from=effective_from,
            notes=notes,
            approved_by=approved_by or [],
            spec=spec,
        )
        # Close the previous version's window so the effective ranges tile
        # the timeline without gaps or overlaps.
        superseded = current.model_copy(update={"effective_to": effective_from})
        self._write_calibration(superseded)
        self._write_calibration(updated)
        return updated

    def _write_calibration(self, calibration: IndexCalibration) -> None:
        directory = self._calibration_dir(calibration.calibration_id)
        atomic_write_text(directory / f"v{calibration.version}.json", calibration.model_dump_json(indent=2))
        latest = self._latest(calibration.calibration_id)
        if latest is None or calibration.version >= latest:
            atomic_write_text(directory / "latest.json",
                json.dumps({"latest_version": calibration.version, "name": calibration.name}, indent=2)
            )

    def _latest(self, calibration_id: str) -> int | None:
        pointer = self._calibration_dir(calibration_id) / "latest.json"
        if not pointer.exists():
            return None
        return int(json.loads(pointer.read_text())["latest_version"])

    def get_calibration(self, calibration_id: str, version: int | None = None) -> IndexCalibration | None:
        if version is None:
            version = self._latest(calibration_id)
            if version is None:
                return None
        path = self._calibration_dir(calibration_id) / f"v{int(version)}.json"
        if not path.exists():
            return None
        return IndexCalibration.model_validate_json(path.read_text())

    def list_calibration_versions(self, calibration_id: str) -> list[IndexCalibration]:
        directory = self._calibration_dir(calibration_id)
        versions = []
        for path in sorted(directory.glob("v*.json"), key=lambda p: int(p.stem[1:])):
            versions.append(IndexCalibration.model_validate_json(path.read_text()))
        return versions

    def resolve_for_date(self, calibration_id: str, review_date: str) -> IndexCalibration | None:
        """The version in force on `review_date`: the latest one whose
        `effective_from` is on or before it. Returns None when the
        calibration did not yet exist on that date, which is a real answer
        and not an error -- a review cannot run under a methodology that had
        not been approved yet."""
        in_force = [v for v in self.list_calibration_versions(calibration_id) if v.effective_from <= review_date]
        if not in_force:
            return None
        return max(in_force, key=lambda v: (v.effective_from, v.version))

    def list_calibrations(self) -> list[IndexCalibration]:
        root = self.indices_dir / "calibrations"
        if not root.exists():
            return []
        out = []
        for directory in sorted(root.iterdir()):
            if not directory.is_dir():
                continue
            calibration = self.get_calibration(directory.name)
            if calibration is not None:
                out.append(calibration)
        return out

    def delete_calibration(self, calibration_id: str) -> bool:
        """Removes a calibration and all its versions. Only for calibrations
        that never produced a review -- the caller checks that, because a
        calibration a published number was built from must remain
        reconstructable."""
        directory = self.indices_dir / "calibrations" / safe_id(calibration_id, label="calibration_id")
        if not directory.exists():
            return False
        for path in sorted(directory.iterdir()):
            path.unlink()
        directory.rmdir()
        return True

    # -------------------------------------------------------------- reviews

    def save_review(self, result: ReviewResult) -> None:
        review_date = safe_id(result.review_date, label="review_date")
        atomic_write_text(self._index_dir(result.index_id, "reviews") / f"{review_date}.json", result.model_dump_json(indent=2))
        atomic_write_text(self._index_dir(result.index_id, "state") / f"{review_date}.json", result.state.model_dump_json(indent=2))

    def get_review(self, index_id: str, review_date: str) -> ReviewResult | None:
        path = self._index_dir(index_id, "reviews") / f"{safe_id(review_date, label='review_date')}.json"
        if not path.exists():
            return None
        return ReviewResult.model_validate_json(path.read_text())

    def list_review_dates(self, index_id: str) -> list[str]:
        return sorted(p.stem for p in self._index_dir(index_id, "reviews").glob("*.json"))

    def latest_state_before(self, index_id: str, review_date: str) -> IndexState | None:
        """The most recent state strictly before `review_date` -- the
        `state[t-1]` a path-dependent methodology needs. Strictly before, so
        re-running a review is idempotent rather than compounding its own
        prior output."""
        earlier = [d for d in sorted(p.stem for p in self._index_dir(index_id, "state").glob("*.json")) if d < review_date]
        if not earlier:
            return None
        path = self._index_dir(index_id, "state") / f"{earlier[-1]}.json"
        return IndexState.model_validate_json(path.read_text())

    def list_indices(self) -> list[str]:
        if not self.indices_dir.exists():
            return []
        return sorted(
            d.name for d in self.indices_dir.iterdir() if d.is_dir() and d.name != "calibrations" and (d / "reviews").exists()
        )
