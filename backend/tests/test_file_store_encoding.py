"""Encoding regressions for the file stores: everything written as UTF-8
must read back byte-identical, on every platform.

These stores write through `atomic_write_text`, which specifies
`encoding="utf-8"`. The readers used to call a bare `Path.read_text()`,
which resolves to `locale.getpreferredencoding()` -- UTF-8 on Linux and
macOS, but cp1252 on a German/Western-European Windows install. CI runs
on Linux, where both halves agree and nothing is observable, so this was
invisible there while corrupting data on a developer or deployment
machine.

Two distinct failure modes, which is why the fixtures below use both
`u` and `<=`:

- `Münchener Rück` -- every byte of its UTF-8 form is also a valid cp1252
  character, so the mismatched read *succeeds* and silently yields
  `MÃ¼nchener RÃ¼ck`. No exception, no log line; the corruption only
  surfaces when a person reads the name back in the UI.
- `钢铁` -- U+94C1 encodes a 0x81 byte, which is undefined in cp1252, so
  the mismatched read raises `UnicodeDecodeError` instead. Note that
  `read_jsonl` only skips `json.JSONDecodeError`, so this one would
  propagate out of a batch read.

`<=` (U+2264) matters specifically because Decision Studio puts
comparison operators in rule labels, and `model_dump_json()` -- unlike
`json.dumps()`, which escapes to ASCII -- writes them as raw UTF-8.

Both are regression-tested at the store level rather than against
`atomic_io` directly: the bug was the *pairing* of a UTF-8 writer with a
locale-default reader, so a test that only exercises one half is exactly
the test that passed while the data was being mangled.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arp.schemas.common import JobStatus, RunManifest
from arp.schemas.decision import MechanismConfig
from arp.storage.atomic_io import atomic_write_text, read_text_utf8, write_text_exclusive
from arp.storage.decision_store import DecisionStore
from arp.storage.jsonl_io import append_jsonl, read_jsonl
from arp.storage.run_store import RunStore

# A German issuer name plus a comparison operator: the two things most
# likely to reach a real framework label on a Western-European machine.
AWKWARD = "Münchener Rück: score ≤ 50"
# Raises on a cp1252 read rather than corrupting silently -- see docstring.
AWKWARD_CJK = "钢铁 / 新能源"


@pytest.mark.parametrize("text", [AWKWARD, AWKWARD_CJK, "plain ascii"])
def test_atomic_write_round_trips_through_the_utf8_reader(tmp_path: Path, text: str) -> None:
    path = tmp_path / "record.json"
    atomic_write_text(path, text)
    assert read_text_utf8(path) == text


@pytest.mark.parametrize("text", [AWKWARD, AWKWARD_CJK])
def test_write_text_exclusive_round_trips_through_the_utf8_reader(tmp_path: Path, text: str) -> None:
    path = tmp_path / "once.json"
    write_text_exclusive(path, text)
    assert read_text_utf8(path) == text


def test_read_text_utf8_is_independent_of_the_platform_locale(tmp_path: Path) -> None:
    """The reader must name its encoding rather than inherit the locale's:
    a file written as UTF-8 reads back identically whatever
    `locale.getpreferredencoding()` happens to be."""
    path = tmp_path / "record.json"
    path.write_bytes(AWKWARD.encode("utf-8"))
    assert read_text_utf8(path) == AWKWARD


def test_decision_framework_name_survives_a_save_load_round_trip(tmp_path: Path) -> None:
    """The original report: a framework saved with an umlaut and a `<=` in
    its name came back as mojibake, with no error raised anywhere."""
    store = DecisionStore(tmp_path)
    store.save(MechanismConfig(framework_id="fw_umlaut", version=1, name=AWKWARD))

    loaded = store.get("fw_umlaut", 1)

    assert loaded is not None
    assert loaded.name == AWKWARD


def test_decision_framework_with_cjk_text_is_loadable(tmp_path: Path) -> None:
    store = DecisionStore(tmp_path)
    store.save(MechanismConfig(framework_id="fw_cjk", version=1, name=AWKWARD_CJK))

    loaded = store.get("fw_cjk", 1)

    assert loaded is not None
    assert loaded.name == AWKWARD_CJK


def test_latest_pointer_resolves_for_a_framework_with_non_ascii_content(tmp_path: Path) -> None:
    """`get()` with no version reads the `latest.json` pointer first; that
    read is on the same locale-default path as the record itself."""
    store = DecisionStore(tmp_path)
    store.save(MechanismConfig(framework_id="fw_pointer", version=1, name=AWKWARD))

    loaded = store.get("fw_pointer")

    assert loaded is not None
    assert loaded.version == 1
    assert loaded.name == AWKWARD


def test_run_manifest_round_trips_non_ascii(tmp_path: Path) -> None:
    """A run's `params` carry the universe and theme a person typed, so a
    manifest is as likely to hold an umlaut as a framework name is."""
    store = RunStore(tmp_path)
    store.save_manifest(
        RunManifest(run_id="run-umlaut", run_type="extraction", status=JobStatus.RUNNING, params={"theme": AWKWARD}, company_count=1)
    )

    loaded = store.load_manifest("run-umlaut")

    assert loaded is not None
    assert loaded.params["theme"] == AWKWARD


def test_jsonl_round_trips_non_ascii_written_as_utf8(tmp_path: Path) -> None:
    """`append_jsonl` goes through `json.dumps`, which escapes to ASCII, so
    its own output is safe either way. This pins the reader against a file
    holding raw UTF-8 -- what any other writer of these logs produces, and
    what `read_jsonl` would raise `UnicodeDecodeError` on when it decoded
    as cp1252 (it only tolerates `json.JSONDecodeError`)."""
    path = tmp_path / "items.jsonl"
    path.write_bytes((json.dumps({"name": AWKWARD}, ensure_ascii=False) + "\n").encode("utf-8"))

    assert read_jsonl(path) == [{"name": AWKWARD}]


def test_jsonl_append_then_read_round_trips_non_ascii(tmp_path: Path) -> None:
    path = tmp_path / "items.jsonl"
    append_jsonl(path, {"name": AWKWARD_CJK})

    assert read_jsonl(path) == [{"name": AWKWARD_CJK}]
