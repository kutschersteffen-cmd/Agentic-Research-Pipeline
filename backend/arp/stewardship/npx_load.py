"""Load the committed N-PX vote CSVs (data/voting/npx_urth/) into vote_meetings, vote_items and vote_decisions
with source `npx_urth_demo` (spec "Demo data" step 4). Writes the tables directly, not through intake_votes:
N-PX rows keep the filed vote text, the CSV's for_against_management, and items without a decision."""

from __future__ import annotations

import csv
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import insert, select, update

from arp.db import models as m
from arp.db.company_view import resolve_ref
from arp.db.session import transaction
from arp.errors import ClientInputError
from arp.schemas.common import new_id
from arp.schemas.vote_ledger import VoteValue
from arp.storage.postgres_models import StwCompanyModel, VoteDecisionModel, VoteItemModel, VoteMeetingModel

SOURCE = "npx_urth_demo"
_VOTE = {
    "FOR": VoteValue.FOR, "AGAINST": VoteValue.AGAINST, "ABSTAIN": VoteValue.ABSTAIN, "WITHHOLD": VoteValue.WITHHOLD,
    "DO NOT VOTE": VoteValue.DO_NOT_VOTE, "ONE YEAR": VoteValue.ONE_YEAR, "1 YEAR": VoteValue.ONE_YEAR,
    "TWO YEARS": VoteValue.TWO_YEARS, "2 YEARS": VoteValue.TWO_YEARS, "THREE YEARS": VoteValue.THREE_YEARS,
    "3 YEARS": VoteValue.THREE_YEARS,
}  # fmt: skip
_PROPONENT = {"ISSUER": "issuer", "SECURITY HOLDER": "shareholder"}
_AGAINST = {"AGAINST": True, "FOR": False}


def _cusip(value: str) -> str | None:
    v = value.strip().upper()
    return v.zfill(9) if v.isdigit() and len(v) < 9 else (v or None)  # spreadsheets drop leading zeros


def _number(value: str) -> float | None:
    return float(value) if value.strip() else None  # "508531.000000" and "508531" are the same number


def _rows(path: Path):
    """(line number, row): the physical line the row starts on, header = line 1."""
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        start = 2
        for row in reader:
            yield start, row
            start = reader.line_num + 1


class _Companies:
    """Registry match (spec: ISIN, else CUSIP). A key is used only when its stw_companies row exists, because
    vote_meetings.company_id is a foreign key to stw_companies and vote rows never create one."""

    def __init__(self, s) -> None:
        self.s = s
        self.stw = {c.lower(): c for c in s.scalars(select(StwCompanyModel.company_id))}
        self.cache: dict[tuple[str | None, str | None], str | None] = {}

    def __call__(self, isin: str | None, cusip: str | None) -> str | None:
        if (isin, cusip) not in self.cache:
            self.cache[isin, cusip] = self._match(isin, cusip)
        return self.cache[isin, cusip]

    def _match(self, isin: str | None, cusip: str | None) -> str | None:
        for ref, own in ((isin and f"ISIN:{isin}", isin and f"isin_{isin}"), (cusip and f"CUSIP:{cusip}", None)):
            uid = ref and resolve_ref(self.s, ref)
            if not uid:
                continue
            universe = self.s.scalars(
                select(m.CompanyIdentifier.value).where(
                    m.CompanyIdentifier.company_id == uid,
                    m.CompanyIdentifier.scheme == m.IdScheme.UNIVERSE,
                    m.CompanyIdentifier.valid_to.is_(None),
                )
            ).all()
            # `isin_<ISIN>` is how intake and seed-demo key companies; the registry stores UNIVERSE values upper-cased
            for key in (own, *universe):
                if key and key.lower() in self.stw:
                    return self.stw[key.lower()]
        return None


def load_npx(directory: Path, dsn: str) -> dict[str, int]:
    """Create the meetings, items and decisions not stored yet; re-running creates nothing and only refreshes a
    meeting's company match. Returns the created counts per table."""
    files = sorted(Path(directory).glob("*.csv"))
    if not files:
        raise ClientInputError(f"no .csv files in {directory}")
    meetings: dict[str, dict] = {}
    items: dict[str, dict] = {}
    decisions: dict[str, dict] = {}
    descriptions: dict[str, dict[str, int]] = {}  # meeting key -> description -> 1-based order of first appearance
    for path in files:
        for line, r in _rows(path):
            cusip = _cusip(r["cusip"])
            date = datetime.strptime(r["meeting_date"], "%m/%d/%Y").replace(tzinfo=UTC)
            # no CUSIP (7 Telstra rows in 2024, filed without any id): the issuer name keeps such meetings apart
            mkey = f"{r['accession']}:{cusip or 'name:' + r['issuer_name']}:{date.date().isoformat()}"
            if mkey not in meetings:
                isin = "".join(r["isin"].split()).upper() or None
                meetings[mkey] = {"issuer_name": r["issuer_name"], "isin": isin, "cusip": cusip, "meeting_date": date}
            desc = r["vote_description"]
            # descriptions run to several KB, too long for the (source, external_id) btree index
            ikey = f"{mkey}:{hashlib.sha1(desc.encode()).hexdigest()[:16]}"
            if ikey not in items:
                order = descriptions.setdefault(mkey, {})
                order.setdefault(desc, len(order) + 1)
                rec = r["management_recommendation"].strip().lower()
                items[ikey] = {
                    "meeting": mkey, "item_number": str(order[desc]), "description": desc,
                    "categories": [c.strip() for c in r["vote_categories"].split(";") if c.strip()],
                    "proponent": _PROPONENT.get(r["vote_source"]), "management_recommendation": None if rec in ("", "none") else rec,
                }  # fmt: skip
            if r["how_voted"]:  # an empty vote leaves the item without a decision
                decisions[f"{path.name}:{line}"] = {
                    "item": ikey, "vote": _VOTE.get(r["how_voted"], VoteValue.OTHER).value, "vote_label": r["how_voted"],
                    "against_management": _AGAINST.get(r["for_against_management"]), "shares_voted": _number(r["record_shares_voted"]),
                }  # fmt: skip

    created = {"meetings": 0, "items": 0, "decisions": 0}
    with transaction(dsn) as s:
        companies = _Companies(s)
        stored = {e: (pk, c) for e, pk, c in s.execute(select(VoteMeetingModel.external_id, VoteMeetingModel.meeting_id, VoteMeetingModel.company_id).where(VoteMeetingModel.source == SOURCE))}  # fmt: skip
        meeting_ids, new = {}, []
        for ext, v in meetings.items():
            company = companies(v["isin"], v["cusip"])
            if ext in stored:
                meeting_ids[ext], was = stored[ext]
                if was != company:
                    s.execute(
                        update(VoteMeetingModel).where(VoteMeetingModel.meeting_id == meeting_ids[ext]).values(company_id=company)
                    )
                continue
            meeting_ids[ext] = new_id("mtg")
            new.append({"meeting_id": meeting_ids[ext], "source": SOURCE, "external_id": ext, "company_id": company, **v})
        created["meetings"] = _insert(s, VoteMeetingModel, new)

        item_ids = dict(
            s.execute(select(VoteItemModel.external_id, VoteItemModel.item_id).where(VoteItemModel.source == SOURCE)).all()
        )
        new = []
        for ext, v in items.items():
            if ext not in item_ids:
                item_ids[ext] = new_id("vitem")
                new.append(
                    {
                        "item_id": item_ids[ext],
                        "source": SOURCE,
                        "external_id": ext,
                        "meeting_id": meeting_ids[v.pop("meeting")],
                        **v,
                    }
                )
        created["items"] = _insert(s, VoteItemModel, new)

        known = set(s.scalars(select(VoteDecisionModel.external_id).where(VoteDecisionModel.source == SOURCE)))
        new = [
            {"decision_id": new_id("vote"), "source": SOURCE, "external_id": ext, "item_id": item_ids[v.pop("item")], **v}
            for ext, v in decisions.items()
            if ext not in known
        ]
        created["decisions"] = _insert(s, VoteDecisionModel, new)
    return created


def _insert(s, model, rows: list[dict]) -> int:
    if rows:
        s.execute(insert(model), rows)
    return len(rows)
