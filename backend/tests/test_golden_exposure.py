from __future__ import annotations

import copy
import json

import pytest
from typer.testing import CliRunner

from arp.cli import app


@pytest.fixture(autouse=True)
def _no_postgres(monkeypatch):
    # The root callback demands Postgres; validate only reads local files.
    monkeypatch.setattr("arp.db.session.require_postgres", lambda s: None)
    monkeypatch.setattr("arp.db.session.require_cutover", lambda s: None)
    monkeypatch.setattr("arp.config.get_settings", lambda: object())


def _set(kind="activity", labels=("a", "b")):
    return {
        "set_id": "s1", "kind": kind, "subject": "x", "labels": list(labels), "checked_on": "2026-10-01",
        "cases": [{
            "case_id": "c1", "company": "Hexagon Purus ASA", "label": labels[0], "role": "producer",
            "rationale": "because", "label_sources": ["https://example.com/a"],
            "documents": [{"url": "https://example.com/d.pdf"}],
        }],
    }


def _run(tmp_path, cfg):
    (tmp_path / "cases.json").write_text(json.dumps(cfg), encoding="utf-8")
    return CliRunner().invoke(app, ["golden-set", "exposure", "validate", "--set", str(tmp_path)])


@pytest.mark.parametrize("mutate,needle", [
    (lambda c: c["cases"][0].pop("label_sources"), "label_sources"),
    (lambda c: c["cases"][0].update(label_sources=[]), "label_sources"),
    (lambda c: c["cases"][0].update(label_sources=["see report"]), "label_sources"),
    (lambda c: c["cases"][0].pop("rationale"), "rationale"),
    (lambda c: c["cases"][0].update(label="maybe"), "maybe"),
    (lambda c: c["cases"].append(copy.deepcopy(c["cases"][0])), "c1"),
    (lambda c: c.update(kind="sector"), "kind"),
    (lambda c: c.pop("checked_on"), "checked_on"),
    (lambda c: c.update(checked_on="last week"), "checked_on"),
    (lambda c: c["cases"][0].update(documents=[{"kind": "annual_report"}]), "documents"),
    (lambda c: c["cases"][0].update(documents=[{"path": "missing.pdf"}]), "missing.pdf"),
    (lambda c: c["cases"][0].update(documents=[{"path": "../x.pdf"}]), "../x.pdf"),
    (lambda c: c.update(cases=[]), "cases"),
])
def test_validate_rejects(tmp_path, mutate, needle):
    cfg = _set()
    mutate(cfg)
    (tmp_path / "x.pdf").write_bytes(b"")  # exists, but outside documents/
    result = _run(tmp_path, cfg)
    assert result.exit_code == 1
    assert needle in result.output
    if needle not in ("kind", "checked_on", "cases"):  # set-level problems carry no case_id
        assert "c1" in result.output


def test_validate_ok_activity(tmp_path):
    assert _run(tmp_path, _set()).exit_code == 0


def test_validate_ok_risk(tmp_path):
    cfg = _set("risk", ("exposed_disclosed", "exposed_undisclosed", "not_exposed"))
    for i, lab in enumerate(cfg["labels"][1:], 2):
        c = copy.deepcopy(cfg["cases"][0])
        c.update(case_id=f"c{i}", label=lab, extra_key="allowed")
        cfg["cases"].append(c)
    result = _run(tmp_path, cfg)
    assert result.exit_code == 0, result.output


def test_validate_existing_document_path(tmp_path):
    (tmp_path / "documents").mkdir()
    (tmp_path / "documents" / "ok.pdf").write_bytes(b"")
    cfg = _set()
    cfg["cases"][0]["documents"] = [{"path": "ok.pdf"}]
    assert _run(tmp_path, cfg).exit_code == 0


@pytest.mark.parametrize("raw", [b"{not json", b"\xff\xfe\x00"])
def test_validate_bad_json(tmp_path, raw):
    (tmp_path / "cases.json").write_bytes(raw)
    result = CliRunner().invoke(app, ["golden-set", "exposure", "validate", "--set", str(tmp_path)])
    assert result.exit_code == 1
    assert "invalid JSON" in result.output
    assert "Traceback" not in result.output


def _cases(tmp_path, spec, labels=("core", "not")):
    cfg = _set(labels=labels)
    base = cfg["cases"][0]
    cfg["cases"] = []
    for cid, label, *sp in spec:
        c = copy.deepcopy(base)
        c.update(case_id=cid, label=label)
        if sp:
            c["split"] = sp[0]
        cfg["cases"].append(c)
    if cfg["cases"]:
        cfg["cases"][0]["company"] = "LONGi 隆基"
    (tmp_path / "cases.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _cli(tmp_path, cmd):
    return CliRunner().invoke(app, ["golden-set", "exposure", cmd, "--set", str(tmp_path)])


def _splits(tmp_path):
    return {c["case_id"]: c.get("split") for c in json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))["cases"]}


def test_split_alternates_per_label(tmp_path):  # AC-14
    _cases(tmp_path, [("a", "core"), ("b", "core"), ("c", "not"), ("d", "not")])
    assert _cli(tmp_path, "split").exit_code == 0
    assert _splits(tmp_path) == {"a": "holdout", "b": "tune", "c": "holdout", "d": "tune"}


def test_split_keeps_existing(tmp_path):  # AC-15
    _cases(tmp_path, [("a", "core", "tune"), ("b", "core"), ("c", "core")])
    _cli(tmp_path, "split")
    assert _splits(tmp_path) == {"a": "tune", "b": "tune", "c": "holdout"}


def test_split_idempotent_mixed_and_unicode(tmp_path):  # Review Focus 2 and 3
    _cases(tmp_path, [("a", "core", "tune"), ("b", "core"), ("c", "not"), ("d", "not", "holdout"), ("e", "not")])
    _cli(tmp_path, "split")
    first = (tmp_path / "cases.json").read_bytes()
    _cli(tmp_path, "split")
    assert (tmp_path / "cases.json").read_bytes() == first
    assert "LONGi 隆基".encode() in first


def test_split_invalid_does_not_write(tmp_path):
    _cases(tmp_path, [])
    before = (tmp_path / "cases.json").read_bytes()
    assert _cli(tmp_path, "split").exit_code == 1
    assert (tmp_path / "cases.json").read_bytes() == before


def test_stats_lines(tmp_path):  # AC-16
    _cases(tmp_path, [("a", "core"), ("b", "core"), ("c", "not"), ("d", "not")])
    _cli(tmp_path, "split")
    out = _cli(tmp_path, "stats").output
    assert "core tune=1 holdout=1" in out and "not tune=1 holdout=1" in out
