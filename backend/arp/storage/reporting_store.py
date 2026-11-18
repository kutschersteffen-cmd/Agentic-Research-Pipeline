from __future__ import annotations

import json
import shutil
from pathlib import Path

from arp.schemas.common import new_id, now_iso
from arp.schemas.reporting import (
    Deck,
    Finding,
    ReportImage,
    ReportManifest,
    ReportPlan,
    ReportRequest,
    StagedImage,
    Storyline,
    TemplateStyleProfile,
)
from arp.storage.atomic_io import atomic_write_bytes, atomic_write_text, read_text_utf8
from arp.storage.report_images import ImageError, LoadedImage, check_focus, check_name, decode_image
from arp.storage.safe_path import UnsafeIdentifierError, safe_id


class ReportingStore:
    """File-based persistence for report generation -- one directory per
    report under `reports/<report_id>/`, and one per ingested template
    style under `report_templates/<template_id>/`, and one per staged image
    upload under `report_images/<image_id>/`. Same write-then-rename
    atomicity convention as RunStore/TaxonomyStore; no database.
    """

    def __init__(self, reports_dir: Path, templates_dir: Path, images_dir: Path | None = None) -> None:
        self.reports_dir = reports_dir
        self.templates_dir = templates_dir
        self.images_dir = images_dir or templates_dir.parent / "report_images"

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

    def preview_dir(self, report_id: str) -> Path:
        return self.report_dir(report_id) / "preview"

    def save_manifest(self, manifest: ReportManifest) -> None:
        manifest.updated_at = now_iso()
        atomic_write_text(self.manifest_path(manifest.report_id), manifest.model_dump_json(indent=2))

    def load_manifest(self, report_id: str) -> ReportManifest | None:
        path = self.manifest_path(report_id)
        if not path.exists():
            return None
        return ReportManifest.model_validate_json(read_text_utf8(path))

    def save_request(self, report_id: str, request: ReportRequest) -> None:
        atomic_write_text(self.request_path(report_id), request.model_dump_json(indent=2))

    def load_request(self, report_id: str) -> ReportRequest | None:
        path = self.request_path(report_id)
        if not path.exists():
            return None
        return ReportRequest.model_validate_json(read_text_utf8(path))

    def save_plan(self, report_id: str, plan: ReportPlan) -> None:
        atomic_write_text(self.plan_path(report_id), plan.model_dump_json(indent=2))

    def load_plan(self, report_id: str) -> ReportPlan | None:
        path = self.plan_path(report_id)
        if not path.exists():
            return None
        return ReportPlan.model_validate_json(read_text_utf8(path))

    # House deck: storyline.json (approved by a human), deck.json (filled slides), findings.json.

    def save_storyline(self, report_id: str, storyline: Storyline) -> None:
        atomic_write_text(self.report_dir(report_id) / "storyline.json", storyline.model_dump_json(indent=2))

    def load_storyline(self, report_id: str) -> Storyline | None:
        path = self.report_dir(report_id) / "storyline.json"
        return Storyline.model_validate_json(read_text_utf8(path)) if path.exists() else None

    def save_deck(self, report_id: str, deck: Deck) -> None:
        atomic_write_text(self.report_dir(report_id) / "deck.json", deck.model_dump_json(indent=2))

    def load_deck(self, report_id: str) -> Deck | None:
        path = self.report_dir(report_id) / "deck.json"
        return Deck.model_validate_json(read_text_utf8(path)) if path.exists() else None

    def save_findings(self, report_id: str, findings: list[Finding]) -> None:
        atomic_write_text(self.report_dir(report_id) / "findings.json", json.dumps([f.model_dump() for f in findings], indent=2))

    def load_findings(self, report_id: str) -> list[Finding]:
        path = self.report_dir(report_id) / "findings.json"
        return [Finding.model_validate(f) for f in json.loads(read_text_utf8(path))] if path.exists() else []

    def list_reports(self) -> list[ReportManifest]:
        manifests: list[ReportManifest] = []
        if not self.reports_dir.exists():
            return manifests
        for d in self.reports_dir.iterdir():
            mp = d / "manifest.json"
            if not mp.exists():
                continue
            try:
                manifests.append(ReportManifest.model_validate_json(read_text_utf8(mp)))
            except (json.JSONDecodeError, OSError, ValueError):
                continue
        # newest first; the folder name is a random id and says nothing about age
        return sorted(manifests, key=lambda m: (m.created_at, m.report_id), reverse=True)

    # ---- images (house deck) ----

    def stage_image(self, data: bytes, filename: str) -> StagedImage:
        """Checks an upload and keeps it until a request names it by `image_id`."""
        img = decode_image(data, filename)
        staged = StagedImage(image_id=new_id("img"), media_type=img.media_type, width=img.width, height=img.height, sha256=img.sha256)
        d = self.images_dir / staged.image_id
        d.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(d / f"image.{img.ext}", img.data)
        atomic_write_text(d / "meta.json", staged.model_dump_json(indent=2))
        return staged

    def load_staged_image(self, image_id: str) -> tuple[StagedImage, bytes] | None:
        try:
            d = self.images_dir / safe_id(image_id, label="image_id")
        except UnsafeIdentifierError:
            return None
        meta = d / "meta.json"
        if not meta.exists():
            return None
        staged = StagedImage.model_validate_json(read_text_utf8(meta))
        ext = "png" if staged.media_type == "image/png" else "jpg"
        return staged, (d / f"image.{ext}").read_bytes()

    def save_report_image(self, report_id: str, name: str, data: bytes, alt: str = "", focus: list[float] | None = None) -> ReportImage:
        check_name(name)
        img = decode_image(data, name)
        entry = ReportImage(
            name=name, alt=alt, focus=check_focus(name, focus),
            media_type=img.media_type, width=img.width, height=img.height, sha256=img.sha256,
        )
        d = self.report_dir(report_id) / "images"
        d.mkdir(exist_ok=True)
        atomic_write_bytes(d / f"{name}.{img.ext}", img.data)
        return entry

    def report_image_path(self, report_id: str, name: str) -> Path:
        """The stored file of image `name`; raises ImageError for a name that can't be one."""
        check_name(name)
        d = self.report_dir(report_id) / "images"
        jpg = d / f"{name}.jpg"
        return jpg if jpg.exists() else d / f"{name}.png"

    def load_report_images(self, report_id: str, request: ReportRequest) -> dict[str, LoadedImage]:
        out: dict[str, LoadedImage] = {}
        for entry in request.images:
            if not isinstance(entry, ReportImage):
                raise ImageError(f"image '{entry.name}' was never stored with report {report_id!r}")
            out[entry.name] = LoadedImage(entry=entry, data=self.report_image_path(report_id, entry.name).read_bytes())
        return out

    def copy_report_images(self, source_id: str, target_id: str) -> None:
        """A re-run renders on its own: it gets a copy of the source's images."""
        src = self.report_dir(source_id) / "images"
        if src.is_dir():
            shutil.copytree(src, self.report_dir(target_id) / "images")

    # ---- template styles ----

    def template_dir(self, template_id: str) -> Path:
        d = self.templates_dir / safe_id(template_id, label="template_id")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def template_style_path(self, template_id: str) -> Path:
        return self.template_dir(template_id) / "style.json"

    def template_source_path(self, template_id: str, filename: str) -> Path:
        return self.template_dir(template_id) / filename

    def template_font_dir(self, template_id: str) -> Path:
        return self.template_dir(template_id) / "fonts"

    def save_template_style(self, style: TemplateStyleProfile) -> None:
        atomic_write_text(self.template_style_path(style.template_id), style.model_dump_json(indent=2))

    def load_template_style(self, template_id: str) -> TemplateStyleProfile | None:
        path = self.template_style_path(template_id)
        if not path.exists():
            return None
        return TemplateStyleProfile.model_validate_json(read_text_utf8(path))

    def list_template_styles(self) -> list[TemplateStyleProfile]:
        styles: list[TemplateStyleProfile] = []
        if not self.templates_dir.exists():
            return styles
        for d in sorted(self.templates_dir.iterdir(), reverse=True):
            sp = d / "style.json"
            if not sp.exists():
                continue
            try:
                styles.append(TemplateStyleProfile.model_validate_json(read_text_utf8(sp)))
            except (json.JSONDecodeError, OSError, ValueError):
                continue
        return styles
