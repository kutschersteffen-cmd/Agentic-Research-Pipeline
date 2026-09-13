from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from arp.schemas.common import now_iso
from arp.schemas.reporting import ReportManifest, ReportPlan, ReportRequest, TemplateStyleProfile
from arp.storage.safe_path import safe_id


class ReportingStore:
    """File-based persistence for report generation -- one directory per
    report under `reports/<report_id>/`, and one per ingested template
    style under `report_templates/<template_id>/`. Same write-then-rename
    atomicity convention as RunStore/TaxonomyStore; no database.
    """

    def __init__(self, reports_dir: Path, templates_dir: Path) -> None:
        self.reports_dir = reports_dir
        self.templates_dir = templates_dir

    # ---- reports ----

    def report_dir(self, report_id: str) -> Path:
        d = self.reports_dir / safe_id(report_id, label="report_id")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def manifest_path(self, report_id: str) -> Path:
        return self.report_dir(report_id) / "manifest.json"

    def request_path(self, report_id: str) -> Path:
        return self.report_dir(report_id) / "request.json"

    def plan_path(self, report_id: str) -> Path:
        return self.report_dir(report_id) / "plan.json"

    def output_path(self, report_id: str, filename: str) -> Path:
        return self.report_dir(report_id) / filename

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(text)
            os.replace(tmp_path, path)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    def save_manifest(self, manifest: ReportManifest) -> None:
        manifest.updated_at = now_iso()
        self._atomic_write(self.manifest_path(manifest.report_id), manifest.model_dump_json(indent=2))

    def load_manifest(self, report_id: str) -> ReportManifest | None:
        path = self.manifest_path(report_id)
        if not path.exists():
            return None
        return ReportManifest.model_validate_json(path.read_text())

    def save_request(self, report_id: str, request: ReportRequest) -> None:
        self._atomic_write(self.request_path(report_id), request.model_dump_json(indent=2))

    def load_request(self, report_id: str) -> ReportRequest | None:
        path = self.request_path(report_id)
        if not path.exists():
            return None
        return ReportRequest.model_validate_json(path.read_text())

    def save_plan(self, report_id: str, plan: ReportPlan) -> None:
        self._atomic_write(self.plan_path(report_id), plan.model_dump_json(indent=2))

    def load_plan(self, report_id: str) -> ReportPlan | None:
        path = self.plan_path(report_id)
        if not path.exists():
            return None
        return ReportPlan.model_validate_json(path.read_text())

    def list_reports(self) -> list[ReportManifest]:
        manifests: list[ReportManifest] = []
        if not self.reports_dir.exists():
            return manifests
        for d in sorted(self.reports_dir.iterdir(), reverse=True):
            mp = d / "manifest.json"
            if not mp.exists():
                continue
            try:
                manifests.append(ReportManifest.model_validate_json(mp.read_text()))
            except (json.JSONDecodeError, OSError, ValueError):
                continue
        return manifests

    # ---- template styles ----

    def template_dir(self, template_id: str) -> Path:
        d = self.templates_dir / safe_id(template_id, label="template_id")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def template_style_path(self, template_id: str) -> Path:
        return self.template_dir(template_id) / "style.json"

    def template_source_path(self, template_id: str, filename: str) -> Path:
        return self.template_dir(template_id) / filename

    def save_template_style(self, style: TemplateStyleProfile) -> None:
        self._atomic_write(self.template_style_path(style.template_id), style.model_dump_json(indent=2))

    def load_template_style(self, template_id: str) -> TemplateStyleProfile | None:
        path = self.template_style_path(template_id)
        if not path.exists():
            return None
        return TemplateStyleProfile.model_validate_json(path.read_text())

    def list_template_styles(self) -> list[TemplateStyleProfile]:
        styles: list[TemplateStyleProfile] = []
        if not self.templates_dir.exists():
            return styles
        for d in sorted(self.templates_dir.iterdir(), reverse=True):
            sp = d / "style.json"
            if not sp.exists():
                continue
            try:
                styles.append(TemplateStyleProfile.model_validate_json(sp.read_text()))
            except (json.JSONDecodeError, OSError, ValueError):
                continue
        return styles
