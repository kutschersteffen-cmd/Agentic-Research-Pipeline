import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from arp.config import Settings
from arp.retention import RetentionViolation, cleanup, delete_expired

DAY = 86400
KEY = "abcd" + "0" * 60


def _age(path, days):
    t = datetime.now(UTC).timestamp() - days * DAY
    os.utime(path, (t, t), follow_symlinks=False)


def _write(path, text="x", days=3651):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    _age(path, days)
    return path


@pytest.fixture
def settings(tmp_path):
    return Settings(runs_dir=tmp_path / "runs", blob_store_dir=tmp_path / "blobs")


def _run(settings, rid="r1", status="completed", days=3651):
    d = settings.runs_dir / rid
    _write(d / "manifest.json", json.dumps({"status": status}), days)
    _write(d / "results.jsonl", days=days)
    return d


def test_delete_expired_refuses_younger_file(tmp_path):
    f = _write(tmp_path / "f", days=10)
    with pytest.raises(RetentionViolation):
        delete_expired(f, timedelta(days=3650), now=datetime.now(UTC))
    assert f.exists()


def test_delete_expired_deletes_older_file(tmp_path):
    f = _write(tmp_path / "f", days=3651)
    delete_expired(f, timedelta(days=3650), now=datetime.now(UTC))
    assert not f.exists()


def test_cleanup_dry_run_deletes_nothing(settings):
    d = _run(settings)
    report = cleanup(settings, apply=False)
    assert str(d / "results.jsonl") in report.deleted
    assert (d / "results.jsonl").exists()


def test_cleanup_deletes_expired_run_but_keeps_young_decision_log(settings):
    d = _run(settings)
    _write(d / "review_decisions.jsonl", days=10)
    cleanup(settings, apply=True)
    assert not (d / "results.jsonl").exists() and not (d / "manifest.json").exists()
    assert (d / "review_decisions.jsonl").exists()


def test_cleanup_keeps_run_with_one_young_file(settings):
    d = _run(settings)
    _write(d / "errors.jsonl", days=10)
    cleanup(settings, apply=True)
    assert (d / "results.jsonl").exists() and (d / "manifest.json").exists()


def test_cleanup_lock_sidecars_ignored_for_age_and_deleted(settings):
    d = _run(settings)
    _write(d / ".lock", days=1)
    _write(d / ".worker", days=1)
    cleanup(settings, apply=True)
    assert not d.exists()


@pytest.mark.parametrize("status", ["running", "pending"])
def test_cleanup_skips_running_run(settings, status):
    d = _run(settings, status=status)
    cleanup(settings, apply=True)
    assert (d / "results.jsonl").exists()


def test_cleanup_holds_published_run_and_original(settings):
    d = _run(settings)
    blob = _write(settings.blob_store_dir / "ab" / KEY)
    report = cleanup(settings, apply=True, held_runs={"r1"}, held_keys={KEY})
    assert (d / "results.jsonl").exists() and blob.exists()
    assert "r1" in report.held and KEY in report.held


def test_cleanup_deletes_expired_original(settings):
    blob = _write(settings.blob_store_dir / "ab" / KEY)
    cleanup(settings, apply=True)
    assert not blob.exists() and not blob.parent.exists()


def test_cleanup_never_follows_symlink(settings, tmp_path):
    outside = tmp_path / "outside"
    secret = _write(outside / "secret.txt")
    x = _write(outside / "x")
    _run(settings)
    (settings.runs_dir / "r1" / "link").symlink_to(secret)
    (settings.blob_store_dir / "ab").mkdir(parents=True)
    (settings.blob_store_dir / "ab" / "link").symlink_to(x)
    (settings.runs_dir / "r1" / "dirlink").symlink_to(outside)
    for p in (settings.runs_dir / "r1" / "link", settings.blob_store_dir / "ab" / "link", settings.runs_dir / "r1" / "dirlink"):
        _age(p, 3651)
    cleanup(settings, apply=True)
    assert secret.exists() and x.exists()


def test_policy_floor():
    with pytest.raises(ValidationError):
        Settings(retention_runs_days=30)
