"""Spec workbench-review-fixes, robustness PR: the selection, programme and notes logs under damaged lines, refused
changes and more than one writing process. Fixture W: the synthetic sample universe (SYN01..SYN12)."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("zen")

from arp.api.deps import get_stream_store  # noqa: E402
from arp.api.main import app  # noqa: E402
from arp.config import get_settings  # noqa: E402
from arp.stewardship import worklist  # noqa: E402
from arp.stewardship.notes import NoteLog  # noqa: E402
from arp.stewardship.process import StreamStore  # noqa: E402
from arp.stewardship.programmes import ProgrammeLog  # noqa: E402

Q = worklist.cycle_of(datetime.now(UTC).date())
BACKEND = Path(__file__).resolve().parents[1]


def _parallel(*scripts: str, ready: Path | None = None, go: Path | None = None) -> list[str]:
    """Runs each script in its own Python process, all at once; their stdout, in order. With `go`: touches it once
    every script has touched a `ready-*` file in `ready`."""
    procs = [subprocess.Popen([sys.executable, "-c", s], cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for s in scripts]
    if go is not None:
        deadline = time.monotonic() + 60
        while len(list(ready.glob("ready-*"))) < len(scripts) and time.monotonic() < deadline:
            time.sleep(0.01)
        go.touch()
    out = []
    for p in procs:
        stdout, stderr = p.communicate(timeout=120)
        assert p.returncode == 0, stderr
        out.append(stdout)
    return out


def test_confirm_and_remove_in_two_processes_never_lose_a_confirmed_row(tmp_path):
    # AC-15
    names = {f"C{n}": f"C{n}" for n in range(1, 51)}
    log = worklist.SelectionLog(tmp_path)
    today = datetime.now(UTC).date()
    log.change(Q, today, names, list(names), [], "setup", 0)
    path = log._path(Q)
    go = tmp_path / "go"
    head = "import time; from datetime import UTC, datetime; from pathlib import Path; from arp.stewardship.worklist import SelectionLog\n"
    head += f"log, today = SelectionLog(Path({str(tmp_path)!r})), datetime.now(UTC).date()\n"
    head += f"Path({str(tmp_path)!r}, 'ready-' + str(time.time_ns())).touch()\n"
    head += f"while not Path({str(go)!r}).exists(): time.sleep(0.001)\n"  # both start together, after their imports
    confirm = head + (  # confirms once, part-way through the removals
        f"while len(Path({str(path)!r}).read_text().splitlines()) < 60: time.sleep(0.001)\n"
        f"print(log.confirm({Q!r}, today, 'confirmer', 0))"
    )
    remove = head + (  # each removal waits 20 ms between reading the log and appending: a lock must cover that
        "write = SelectionLog._write\n"
        "SelectionLog._write = lambda self, *args: time.sleep(0.02) or write(self, *args)\n"
        "for n in range(1, 51):\n"
        "    try:\n"
        f"        log.change({Q!r}, today, {{f'C{{n}}': f'C{{n}}'}}, [], [f'C{{n}}'], 'remover', 0)\n"
        "    except ValueError as exc:\n"
        "        print(exc)\n"
    )
    _parallel(confirm, remove, ready=tmp_path, go=go)
    assert all(r["status"] == "confirmed" for r in log.rows(Q))
    confirmed: set[str] = set()
    for e in map(json.loads, path.read_text().splitlines()):
        assert not (e["event"] == "removed" and e["issuer_id"] in confirmed), e
        if e["event"] == "confirmed":
            confirmed.add(e["issuer_id"])
    assert confirmed and len(log.rows(Q)) == len(confirmed)


def test_a_removed_line_after_confirmation_is_ignored(tmp_path):
    log = worklist.SelectionLog(tmp_path)
    today = datetime.now(UTC).date()
    log.change(Q, today, {"A": "A"}, ["A"], [], "u", 0)
    log.confirm(Q, today, "v", 0)
    with log._path(Q).open("a") as f:
        f.write(json.dumps({"event": "removed", "issuer_id": "A", "by": "stale", "at": "x", "weights_version": 0}) + "\n")
    assert [(r["issuer_id"], r["status"], r["confirmed_by"]) for r in log.rows(Q)] == [("A", "confirmed", "v")]


def test_a_damaged_line_is_logged_once_per_log(tmp_path, caplog):
    # AC-22
    selection = worklist.SelectionLog(tmp_path)
    programmes = ProgrammeLog(tmp_path)
    good_selection = {"event": "added", "issuer_id": "A", "by": "u", "at": "t", "weights_version": 0}
    good_programme = {"event": "proposed", "programme_id": "climate", "issuer_id": "A", "by": "u", "at": "t"}
    for path, good, damaged in (
        (selection._path(Q), good_selection, {k: v for k, v in good_selection.items() if k != "issuer_id"}),
        (programmes.path, good_programme, {k: v for k, v in good_programme.items() if k != "issuer_id"}),
    ):
        path.parent.mkdir(parents=True)
        path.write_text("not json\n" + json.dumps(good) + "\n" + json.dumps(damaged) + "\n")
    with caplog.at_level(logging.WARNING):
        for _ in range(2):
            assert [r["issuer_id"] for r in selection.rows(Q)] == ["A"]
            assert [m["issuer_id"] for m in programmes.programme("climate")["members"]] == ["A"]
    warnings = sorted(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert warnings == sorted(f"Skipped damaged line 3 in {p}" for p in (selection._path(Q), programmes.path))


def test_parallel_programme_creates_in_two_processes(tmp_path):
    # AC-23
    names = [f"Programme {n}" for n in range(50)]
    script = (
        "from pathlib import Path; from arp.stewardship.programmes import ProgrammeLog\n"
        f"log = ProgrammeLog(Path({str(tmp_path)!r}))\n"
        "import time; write = ProgrammeLog._write\n"  # 5 ms between reading the log and appending: a lock must cover that
        "ProgrammeLog._write = lambda self, *args: time.sleep(0.005) or write(self, *args)\n"
        f"for name in {names!r}:\n"
        "    try:\n"
        "        log.create(name, 'u')\n"
        "    except ValueError as exc:\n"
        "        print(exc)\n"
    )
    refused = [line for out in _parallel(script, script) for line in out.splitlines()]
    created = [e for e in map(json.loads, ProgrammeLog(tmp_path).path.read_text().splitlines()) if e["event"] == "created"]
    assert sorted(e["name"] for e in created) == sorted(names)
    ids = {n: n.lower().replace(" ", "_") for n in names}
    assert sorted(refused) == sorted(
        next(m for m in (f"A programme named {n} exists", f"A programme with id {ids[n]} exists") if m in refused) for n in names
    )


def test_parallel_notes_in_two_processes(tmp_path):
    # AC-24
    script = (
        "from pathlib import Path; from arp.stewardship.notes import NoteLog\n"
        f"log = NoteLog(Path({str(tmp_path)!r}))\n"
        "for n in range(500): log.add('SYN01', 'x' * 1500 + str(n), 'u', 'house')\n"
    )
    _parallel(script, script)
    log = NoteLog(tmp_path)
    assert all(json.loads(line) for line in log.path.read_text().splitlines())
    assert len(log.notes("SYN01")) == 1000


# --- through the API, on Fixture W ---


@pytest.fixture
def root(sample_house_universe, pg):
    return get_settings().stewardship_streams_dir


@pytest.fixture
def client(root, monkeypatch, tmp_path):
    monkeypatch.setenv("ARP_ENGAGEMENTS_DIR", str(tmp_path / "engagements"))
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "postgres")
    get_settings.cache_clear()
    app.dependency_overrides[get_stream_store] = lambda: StreamStore(root)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_stream_store, None)


def _members(client) -> list[tuple[str, str]]:
    return [(m["issuer_id"], m["status"]) for m in client.get("/api/stewardship/programmes/climate").json()["members"]]


def _change(client, **body):
    return client.post("/api/stewardship/programmes/climate/members", json=body)


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"end": ["SYN05"], "reason": "x"}, "not a confirmed member: SYN05"),  # AC-14
        ({"remove": ["SYN05"]}, "not a proposed member: SYN05"),  # AC-16
        ({"add": ["SYN05"], "end": ["SYN05"], "reason": "x"}, "A company can only be in one of add, remove and end: SYN05"),  # AC-17
        ({"end": ["SYN05"]}, "Ending a membership needs a reason"),  # AC-29
        ({"add": ["SYN03"], "remove": ["NOT_A_COMPANY"]}, "not a proposed member: NOT_A_COMPANY"),  # AC-30
        ({"add": ["NOPE", "SYN03"], "remove": ["SYN03"]}, "unknown company: NOPE"),  # check 2 before check 3
        ({"add": ["SYN04", "SYN03"], "remove": ["SYN03", "SYN04"], "end": ["SYN04"]},
         "A company can only be in one of add, remove and end: SYN04, SYN03"),  # each id once, in request order
    ],
)  # fmt: skip
def test_programme_refusals_write_nothing(client, body, detail):
    r = _change(client, **body)
    assert (r.status_code, r.json()["detail"]) == (422, detail)
    assert _members(client) == []


def test_programme_member_states(client):
    # AC-18, AC-19, AC-25, AC-26
    assert _change(client, add=["SYN03"]).status_code == 200
    assert _change(client, end=["SYN03"], reason="x").json()["detail"] == "not a confirmed member: SYN03"
    assert _members(client) == [("SYN03", "proposed")]
    assert _change(client, remove=["SYN03"]).status_code == 200 and _members(client) == []
    assert _change(client, add=["SYN03"]).status_code == 200
    assert client.post("/api/stewardship/programmes/climate/confirm", json={}).status_code == 200
    assert _change(client, remove=["SYN03"]).json()["detail"] == "confirmed members are ended, not removed"
    assert _change(client, add=["SYN03"]).status_code == 200 and _members(client) == [("SYN03", "confirmed")]


def test_selection_keeps_a_confirmed_row_and_skips_damaged_lines(client, root):
    # AC-11, AC-12, AC-20
    assert client.post("/api/stewardship/selection", json={"cycle": Q, "add": ["SYN03"]}).status_code == 200
    assert client.post("/api/stewardship/selection/confirm", json={"cycle": Q}).status_code == 200
    with (root / "selection" / Q / "house.jsonl").open("a") as f:
        stale = {"event": "removed", "issuer_id": "SYN03", "by": "stale", "at": datetime.now(UTC).isoformat(), "weights_version": 0}
        f.write("".join(json.dumps(line) + "\n" for line in (stale, {"event": "added"}, {"issuer_id": "SYN04"}, ["x"])))
    assert client.post("/api/stewardship/selection", json={"cycle": Q, "add": ["SYN03"]}).status_code == 200
    rows = client.get("/api/stewardship/selection", params={"cycle": Q}).json()["rows"]
    assert [(r["issuer_id"], r["status"], r["confirmed_by"]) for r in rows] == [("SYN03", "confirmed", "Test")]
    assert client.get("/api/stewardship/worklist").status_code == 200


def test_programme_log_skips_damaged_lines(client, root):
    # AC-21
    assert _change(client, add=["SYN03"]).status_code == 200
    with (root / "programmes" / "events.jsonl").open("a") as f:
        f.write("".join(json.dumps(line) + "\n" for line in ({"event": "proposed", "programme_id": "climate"}, {"programme_id": "climate"}, ["x"])))
    assert client.get("/api/stewardship/programmes").status_code == 200
    assert _members(client) == [("SYN03", "proposed")]
    assert client.get("/api/stewardship/worklist").status_code == 200


def test_a_line_with_a_wrong_typed_key_is_damaged(tmp_path, caplog):
    # review #548 optional 1: such a line made the fold raise (unhashable id, `None.lower()` on the next create)
    selection, programmes = worklist.SelectionLog(tmp_path), ProgrammeLog(tmp_path)
    for path, lines in (
        (selection._path(Q), [{"event": "added", "issuer_id": ["x"], "by": "u", "at": "t", "weights_version": 0}]),
        (programmes.path, [{"event": "proposed", "programme_id": {"x": 1}, "by": "u", "at": "t", "issuer_id": "S"},
                           {"event": "created", "programme_id": "p", "name": None, "by": "u", "at": "t"}]),
    ):  # fmt: skip
        path.parent.mkdir(parents=True)
        path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    with caplog.at_level(logging.WARNING):
        assert selection.rows(Q) == []
        assert programmes.create("New", "u")["name"] == "New"
    assert len([r for r in caplog.records if r.getMessage().startswith("Skipped damaged line")]) == 3
