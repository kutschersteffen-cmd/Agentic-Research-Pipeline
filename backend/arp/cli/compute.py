from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import typer

from arp.compute import client
from arp.config import get_settings
from arp.ingestion import local_files
from arp.retrieval import embeddings, rerank

compute_app = typer.Typer(help="Cloud compute (arp/compute/): the Cloud Run GPU services for parsing, rerank, embed.")

@compute_app.callback()
def _group() -> None:
    """Keeps `check` a subcommand: a one-command Typer app would otherwise collapse into it."""


_QUERY = "revenue"
_TEXTS = ["Revenue grew 5% in 2025.", "The cat sat on the mat.", "Weather was mild."]


def _check_parse() -> str:
    url = get_settings().compute_parse_url
    if not url:
        return "parse FAIL: ARP_COMPUTE_PARSE_URL not set"
    from reportlab.pdfgen import canvas

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "check.pdf"
        pdf = canvas.Canvas(str(path))
        pdf.drawString(72, 720, "ARP compute check")
        pdf.save()
        remote = client.parse_pdf(path, local_files.parser_version())
        if remote is None:
            return f"parse FAIL: {client.last_error.get('parse', 'no result')}"
        if not (client.healthz(url) or {}).get("cuda"):
            return "parse FAIL: the service reports no GPU (/healthz cuda is not true)"
        if remote[0] != local_files._extract_pdf_text_local(path)[0]:
            return "parse FAIL: the cloud text differs from the local parse"
    return "parse OK"


def _check_rerank() -> str:
    if not get_settings().compute_models_url:
        return "rerank FAIL: ARP_COMPUTE_MODELS_URL not set"
    scores = client.rerank_scores(_QUERY, _TEXTS)
    if scores is None:
        return f"rerank FAIL: {client.last_error.get('models', 'no result')}"
    local = [float(s) for s in rerank._get_model().rerank(_QUERY, _TEXTS)]
    if int(np.argmax(scores)) != int(np.argmax(local)):
        return "rerank FAIL: the cloud and local rerankers rank a different text first"
    return "rerank OK"


def _check_embed() -> str:
    if not get_settings().compute_models_url:
        return "embed FAIL: ARP_COMPUTE_MODELS_URL not set"
    remote = client.embed(_TEXTS[:1])
    if remote is None:
        return f"embed FAIL: {client.last_error.get('models', 'no result')}"
    local = np.asarray(list(embeddings._get_model().embed(_TEXTS[:1])), dtype=np.float32)
    cosine = float(remote[0] @ local[0] / (np.linalg.norm(remote[0]) * np.linalg.norm(local[0])))
    if cosine < 0.99:
        return f"embed FAIL: cosine(cloud, local) = {cosine:.3f} < 0.99"
    return "embed OK"


@compute_app.command("check")
def compute_check() -> None:
    """Calls each cloud service once and compares it with the local result; exits 1 if any fails."""
    lines = [_check_parse(), _check_rerank(), _check_embed()]
    for line in lines:
        typer.echo(line)
    if any(" FAIL: " in line for line in lines):
        raise typer.Exit(1)
