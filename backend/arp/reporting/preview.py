from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from arp.schemas.reporting import OutputFormat

_TIMEOUT_S = 120


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT_S)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed ({result.returncode}): {result.stderr.decode(errors='replace')[:2000]}")


def ensure_preview_images(source_path: Path, preview_dir: Path, output_format: OutputFormat) -> list[Path]:
    """Renders each page/slide of a rendered report to a PNG under
    `preview_dir`, via LibreOffice headless (+ poppler's pdftoppm for the
    pptx/docx case, which must go through PDF first -- LibreOffice has no
    direct multi-page image export). Cached against the source file's mtime
    so repeat preview requests for an unchanged render do no work.
    """
    existing = sorted(preview_dir.glob("page-*.png"))
    if existing and preview_dir.stat().st_mtime >= source_path.stat().st_mtime:
        return existing

    preview_dir.mkdir(parents=True, exist_ok=True)
    for f in preview_dir.glob("page-*.png"):
        f.unlink()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        if output_format == OutputFormat.PDF:
            pdf_path = source_path
        else:
            _run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(source_path)])
            pdf_path = tmp_path / f"{source_path.stem}.pdf"
        _run(["pdftoppm", "-png", "-r", "110", str(pdf_path), str(preview_dir / "page")])

    return sorted(preview_dir.glob("page-*.png"))
