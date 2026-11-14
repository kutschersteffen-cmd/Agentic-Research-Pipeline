"""Engagement programmes (spec `stewardship-priority-worklist`): standing, named company lists such as "Climate
engagement programme", not tied to a quarter or a scope.

The log is append-only (`programmes/events.jsonl`): `created`, `proposed`, `removed`, `confirmed` and `ended`
events. Members are proposed, then confirmed by a person, and stay until someone ends them with a reason; an ended
company can be proposed again. Programmes change no score.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

from arp.schemas.engagement import EngagementRecord
from arp.stewardship.tracking import OPEN
from arp.storage.jsonl_io import read_jsonl

BUILT_IN = {
    "climate": "Climate engagement programme",
    "nature": "Nature engagement programme",
    "ai": "AI engagement programme",
    "governance": "Corporate governance engagement programme",
}
THEMES = {
    "climate": "climate_mitigation",
    "nature": "natural_capital",
    "ai": "digital_responsibility",
    "governance": "governance_board_pay",
}
_LOCK = threading.Lock()  # a change reads the log, then appends: one at a time


class UnknownProgramme(KeyError):
    pass


def programme_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class ProgrammeLog:
    def __init__(self, root: Path) -> None:
        self.path = root / "programmes" / "events.jsonl"

    def _fold(self) -> tuple[dict[str, dict], dict[str, dict[str, dict]]]:
        """(programme id -> programme, programme id -> issuer id -> member), built-ins first."""
        progs = {
            pid: {"programme_id": pid, "name": name, "built_in": True, "created_by": None, "created_at": None}
            for pid, name in BUILT_IN.items()
        }
        members: dict[str, dict[str, dict]] = {pid: {} for pid in progs}
        for e in read_jsonl(self.path):
            pid, kind = e["programme_id"], e["event"]
            if kind == "created":
                if pid not in progs:
                    progs[pid] = {
                        "programme_id": pid,
                        "name": e["name"],
                        "built_in": False,
                        "created_by": e["by"],
                        "created_at": e["at"],
                    }
                    members[pid] = {}
                continue
            if pid not in members:
                continue
            iid, m = e["issuer_id"], members[pid].get(e["issuer_id"])
            status = m["status"] if m else None
            if kind == "proposed" and status in (None, "ended"):
                members[pid][iid] = {
                    "issuer_id": iid, "company": e.get("company", iid), "status": "proposed",
                    "proposed_by": e["by"], "proposed_at": e["at"], "confirmed_by": None, "confirmed_at": None,
                    "ended_by": None, "ended_at": None, "end_reason": None,
                }  # fmt: skip
            elif kind == "removed" and status == "proposed":
                del members[pid][iid]
            elif kind == "confirmed" and status == "proposed":
                m.update(status="confirmed", confirmed_by=e["by"], confirmed_at=e["at"])
            elif kind == "ended" and status == "confirmed":
                m.update(status="ended", ended_by=e["by"], ended_at=e["at"], end_reason=e.get("reason"))
        return progs, members

    @staticmethod
    def _summary(prog: dict, members: dict[str, dict]) -> dict:
        statuses = [m["status"] for m in members.values()]
        return {**prog, "confirmed": statuses.count("confirmed"), "proposed": statuses.count("proposed")}

    def programmes(self) -> list[dict]:
        progs, members = self._fold()
        return [self._summary(p, members[pid]) for pid, p in progs.items()]

    def programme(self, pid: str) -> dict:
        progs, members = self._fold()
        if pid not in progs:
            raise UnknownProgramme(pid)
        return {**self._summary(progs[pid], members[pid]), "members": list(members[pid].values())}

    def memberships(self) -> dict[str, list[dict]]:
        """issuer id -> its proposed and confirmed programmes, in programme order (for worklist rows)."""
        progs, members = self._fold()
        out: dict[str, list[dict]] = {}
        for pid, ms in members.items():
            for iid, m in ms.items():
                if m["status"] != "ended":
                    out.setdefault(iid, []).append({"programme_id": pid, "name": progs[pid]["name"], "status": m["status"]})
        return out

    def create(self, name: str, by: str) -> dict:
        name = name.strip()
        if not 1 <= len(name) <= 80:
            raise ValueError("A programme name needs 1 to 80 characters")
        pid = programme_id(name)
        if not pid:
            raise ValueError("A programme name needs a letter or a digit")
        with _LOCK:
            progs, _ = self._fold()
            if any(p["name"].lower() == name.lower() for p in progs.values()):
                raise ValueError(f"A programme named {name} exists")
            if pid in progs:
                raise ValueError(f"A programme with id {pid} exists")
            self._write([{"event": "created", "programme_id": pid, "name": name}], by)
        return self.programme(pid)

    def change(
        self, pid: str, names: dict[str, str], add: list[str], remove: list[str], end: list[str], reason: str | None, by: str
    ) -> None:
        """Proposes `add` (house-universe companies), drops proposed `remove`, ends confirmed `end` with a reason.
        Nothing is written when any part is refused."""
        with _LOCK:
            progs, members = self._fold()
            if pid not in progs:
                raise UnknownProgramme(pid)
            if unknown := [i for i in dict.fromkeys(add) if i not in names]:
                raise ValueError(f"unknown company: {', '.join(unknown)}")
            state = {i: m["status"] for i, m in members[pid].items()}
            if any(state.get(i) == "confirmed" for i in remove):
                raise ValueError("confirmed members are ended, not removed")
            if end and not (reason or "").strip():
                raise ValueError("Ending a membership needs a reason")
            events = [
                {"event": "proposed", "issuer_id": i, "company": names[i]}
                for i in dict.fromkeys(add)
                if state.get(i) in (None, "ended")
            ]
            events += [
                {"event": "removed", "issuer_id": i} for i in dict.fromkeys(remove) if state.get(i) == "proposed" and i not in add
            ]
            events += [
                {"event": "ended", "issuer_id": i, "reason": reason.strip()}
                for i in dict.fromkeys(end)
                if state.get(i) == "confirmed"
            ]
            self._write([{**e, "programme_id": pid} for e in events], by)

    def confirm(self, pid: str, by: str) -> int:
        with _LOCK:
            progs, members = self._fold()
            if pid not in progs:
                raise UnknownProgramme(pid)
            proposed = [i for i, m in members[pid].items() if m["status"] == "proposed"]
            self._write([{"event": "confirmed", "programme_id": pid, "issuer_id": i} for i in proposed], by)
        return len(proposed)

    def suggestions(self, pid: str, names: dict[str, str], records: list[EngagementRecord]) -> list[dict]:
        """House-universe companies with an open or stalled issue whose theme maps to the programme, leaving out
        current proposed or confirmed members. Writes nothing."""
        members = {m["issuer_id"] for m in self.programme(pid)["members"] if m["status"] != "ended"}
        theme = THEMES.get(pid)
        if theme is None:
            return []
        by_company = {r.company_id: r for r in records}
        out = []
        for iid, company in names.items():
            record = by_company.get(iid)
            issues = (
                [{"issue_id": i.issue_id, "fir_theme": theme} for i in record.issues if i.status in OPEN and i.fir_theme == theme]
                if record
                else []
            )
            if issues and iid not in members:
                out.append({"issuer_id": iid, "company": company, "issues": issues})
        return out

    def _write(self, events: list[dict], by: str) -> None:
        if not by.strip():
            raise ValueError("A programme change needs the signed-in user")
        if not events:
            return
        at = datetime.now(UTC).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:  # one write, so a change lands whole or not at all
            f.write("".join(json.dumps({**e, "by": by, "at": at}, ensure_ascii=False) + "\n" for e in events))
