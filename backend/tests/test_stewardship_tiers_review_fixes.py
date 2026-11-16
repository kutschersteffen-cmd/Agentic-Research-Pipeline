"""Tiers review fixes, PR 1 (spec tiers-review-fixes): damaged log lines, locked check-then-append, map_tier, UTF-8."""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("zen")

from arp.stewardship.policies import PolicyStore  # noqa: E402
from arp.stewardship.process import SAMPLE_PATH  # noqa: E402
from arp.stewardship.tiers import PickStore, TierStore, load_graph, map_tier  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
TORN = '{"issuer_id": "SYN0'


def _pick(issuer_id: str, reason: str) -> str:
    event = {"issuer_id": issuer_id, "event": "picked", "reason": reason, "by": "A", "at": "2026-11-01T00:00:00+00:00"}
    return json.dumps(event, ensure_ascii=False)


def _tier_row(issuer_id: str) -> str:
    row = {
        "issuer_id": issuer_id,
        "name": issuer_id,
        "tier": "bilateral",
        "rule": "top_weight",
        "reason": "",
        "confirmed_by": "A",
        "assigned_at": "2026-11-01T00:00:00+00:00",
    }
    return json.dumps(row, ensure_ascii=False)


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_damaged_picks_line_is_skipped_with_one_warning(tmp_path, caplog):
    # AC-4 (AC-1 at unit level)
    path = tmp_path / "bilateral_picks.jsonl"
    path.write_text("\n".join([_pick("SYN01", "CEO change"), TORN, _pick("SYN02", "Board change")]) + "\n")
    before = path.read_bytes()
    with caplog.at_level(logging.WARNING):
        picks = PickStore(tmp_path).standing()
    assert [(p["issuer_id"], p["reason"]) for p in picks] == [("SYN01", "CEO change"), ("SYN02", "Board change")]
    [warning] = _warnings(caplog)
    assert "bilateral_picks.jsonl" in warning and "line 2" in warning
    assert path.read_bytes() == before


def test_damaged_tiers_line_is_skipped_with_one_warning(tmp_path, caplog):
    # AC-6 (AC-5 at unit level)
    path = tmp_path / "tier_assignments.jsonl"
    path.write_text("\n".join([_tier_row("SYN03"), TORN, _tier_row("SYN07")]) + "\n")
    before = path.read_bytes()
    with caplog.at_level(logging.WARNING):
        latest = TierStore(tmp_path).latest()
    assert sorted(latest) == ["SYN03", "SYN07"]
    [warning] = _warnings(caplog)
    assert "tier_assignments.jsonl" in warning and "line 2" in warning
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "line",
    [
        '{"event": "picked"}',  # AC-7: valid JSON, no issuer_id
        '{"issuer_id": "SYN02", "event": "picked", "by": "A", "at": "x"}',  # a picked event without its reason
        '["SYN02"]',  # not a JSON object
        _pick("SYN02", "Prüfung").encode("utf-8").replace(b"\xc3\xbc", b"\xfc"),  # AC-25: Latin-1 bytes
    ],
)
def test_invalid_picks_line_is_skipped(tmp_path, caplog, line):
    raw = line if isinstance(line, bytes) else line.encode()
    (tmp_path / "bilateral_picks.jsonl").write_bytes(_pick("SYN01", "CEO change").encode() + b"\n" + raw + b"\n")
    with caplog.at_level(logging.WARNING):
        picks = PickStore(tmp_path).standing()
    assert [p["issuer_id"] for p in picks] == ["SYN01"]
    [warning] = _warnings(caplog)
    assert "line 2" in warning


def test_tiers_line_without_assigned_at_is_skipped(tmp_path, caplog):
    row = json.loads(_tier_row("SYN07"))
    del row["assigned_at"]
    (tmp_path / "tier_assignments.jsonl").write_text(_tier_row("SYN03") + "\n" + json.dumps(row) + "\n")
    with caplog.at_level(logging.WARNING):
        assert sorted(TierStore(tmp_path).latest()) == ["SYN03"]
    assert len(_warnings(caplog)) == 1


def _slow_race(root: str, action: str, barrier, results) -> None:
    """One OS process: widens the gap between the check and the append, so an unlocked store loses the race."""
    standing = PickStore.standing

    def slow(self):
        out = standing(self)
        time.sleep(0.3)
        return out

    PickStore.standing = slow
    store = PickStore(Path(root))
    barrier.wait()
    try:
        if action == "pick":
            store.pick("SYN01", "r", "A", {"SYN01"})
        else:
            store.withdraw("SYN01", "A")
        results.put("ok")
    except ValueError as exc:
        results.put(str(exc))


def _race(root: Path, action: str) -> list[str]:
    ctx = multiprocessing.get_context("fork")
    barrier, results = ctx.Barrier(2), ctx.Queue()
    procs = [ctx.Process(target=_slow_race, args=(str(root), action, barrier, results)) for _ in range(2)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    return sorted(results.get(timeout=5) for _ in procs)


def _events(root: Path) -> list[str]:
    return [json.loads(line)["event"] for line in (root / "bilateral_picks.jsonl").read_text().splitlines()]


def test_simultaneous_picks_from_two_processes(tmp_path):
    # AC-9
    assert _race(tmp_path, "pick") == ["SYN01 is already picked for bilateral", "ok"]
    assert _events(tmp_path) == ["picked"]


def test_simultaneous_withdraws_from_two_processes(tmp_path):
    # AC-10
    PickStore(tmp_path).pick("SYN01", "r", "A", {"SYN01"})
    assert _race(tmp_path, "withdraw") == ["SYN01 has no bilateral pick", "ok"]
    assert _events(tmp_path) == ["picked", "withdrawn"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(["letter"], ["letter"]), ({"t": "letter"}, {"t": "letter"}), (None, None), ("systemic", "monitor"), ("letter", "letter")],
)
def test_map_tier_maps_only_text(value, expected):
    # F4: a list or dict no longer raises TypeError; evaluate() turns it into the "no valid tier" ValueError
    assert map_tier(value) == expected


@pytest.mark.parametrize("cell", ['["letter"]', '{t: "letter"}'])  # AC-11, AC-12
def test_coverage_tier_that_is_not_text_is_rejected(tmp_path, cell):
    graph = load_graph()
    [table] = [n for n in graph["nodes"] if isinstance(n.get("content"), dict) and "rules" in n["content"]]
    next(r for r in table["content"]["rules"] if r["_id"] == "default")["t"] = cell
    sample = json.loads(SAMPLE_PATH.read_text())
    with pytest.raises(ValueError, match="^Coverage rules returned no valid tier for SYN01"):
        PolicyStore(tmp_path).save("coverage_rules", graph, "", "A", sample)
    assert not (tmp_path / "policies" / "coverage_rules").exists() or not list(
        (tmp_path / "policies" / "coverage_rules").glob("v*.json")
    )


_WRITE_UMLAUTS = """
import sys
from pathlib import Path
from arp.stewardship.tiers import PickStore, TierStore
root = Path(sys.argv[1])
PickStore(root).pick("SYN01", "Pr\\u00fcfung Lieferkette", "A", {"SYN01"})
TierStore(root).confirm({"issuer_id": "SYN01", "tier": "bilateral", "rule": "manual"}, "J\\u00fcrgen")  # escaped: the command line is ASCII here
"""


def test_logs_are_utf8_under_a_non_utf8_locale(tmp_path):
    # AC-13, AC-22. No Latin-1 locale is installed on the CI image, so the C locale (ASCII) stands in for one.
    env = {**os.environ, "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"}
    subprocess.run([sys.executable, "-c", _WRITE_UMLAUTS, str(tmp_path)], cwd=BACKEND, env=env, check=True)
    for name in ("bilateral_picks.jsonl", "tier_assignments.jsonl"):
        raw = (tmp_path / name).read_bytes()
        assert b"\xc3\xbc" in raw and raw.count("ü".encode()) == raw.decode("utf-8").count("ü")
    assert PickStore(tmp_path).standing()[0]["reason"] == "Prüfung Lieferkette"
    assert TierStore(tmp_path).latest()["SYN01"]["confirmed_by"] == "Jürgen"


@pytest.fixture
def client(pg, sample_house_universe, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from arp.api.auth import current_user
    from arp.api.deps import get_stream_store
    from arp.api.main import app
    from arp.config import get_settings
    from arp.stewardship.process import StreamStore
    from tests.conftest import PRINCIPAL

    monkeypatch.setenv("ARP_ENGAGEMENTS_DIR", str(tmp_path / "engagements"))
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "postgres")
    get_settings.cache_clear()
    root = get_settings().stewardship_streams_dir
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    app.dependency_overrides[get_stream_store] = lambda: StreamStore(root)
    with TestClient(app) as c:
        c.root = root
        yield c
    app.dependency_overrides.clear()


def test_umlauts_written_by_main_read_back_unchanged(client):
    # AC-26: main wrote UTF-8 under a UTF-8 locale
    root = client.root
    root.mkdir(parents=True, exist_ok=True)
    (root / "bilateral_picks.jsonl").write_bytes((_pick("SYN01", "Prüfung Lieferkette") + "\n").encode())
    row = {**json.loads(_tier_row("SYN03")), "confirmed_by": "Jürgen"}
    (root / "tier_assignments.jsonl").write_bytes((json.dumps(row, ensure_ascii=False) + "\n").encode())
    body = client.get("/api/stewardship/tiers").json()
    assert body["picks"][0]["reason"] == "Prüfung Lieferkette"
    assert next(a for a in body["assignments"] if a["issuer_id"] == "SYN03")["confirmed_by"] == "Jürgen"


def test_simultaneous_requests_append_once(client):
    # AC-8, AC-24 at unit level
    from concurrent.futures import ThreadPoolExecutor

    url = "/api/stewardship/tiers"
    with ThreadPoolExecutor(10) as pool:
        picks = list(
            pool.map(lambda n: client.post(f"{url}/bilateral", json={"issuer_id": "SYN01", "reason": f"r{n}"}), range(10))
        )
    assert sorted(r.status_code for r in picks) == [200] + [422] * 9
    assert {r.json()["detail"] for r in picks if r.status_code == 422} == {"SYN01 is already picked for bilateral"}
    assert len((client.root / "bilateral_picks.jsonl").read_text().splitlines()) == 1

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda _: client.post(f"{url}/confirm", json={}), range(2)))
    lines = (client.root / "tier_assignments.jsonl").read_text().splitlines()
    assert len(lines) == len({json.loads(line)["issuer_id"] for line in lines})
