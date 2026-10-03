from __future__ import annotations

import re
import uuid

from arp.schemas.common import CompanyRef

ARP_NAMESPACE = uuid.UUID("6f1d3c52-8a47-4b9e-9c0e-2d5a7b14e6f3")
_LEI_RE = re.compile(r"[A-Z0-9]{20}")


def normalise_lei(raw: str) -> str:
    return "".join(raw.split()).upper()


def lei_is_valid(lei: str) -> bool:
    """ISO 17442: 20 alphanumerics; letters map A=10..Z=35; integer mod 97 == 1."""
    return bool(_LEI_RE.fullmatch(lei)) and int("".join(str(int(c, 36)) for c in lei)) % 97 == 1


def issuer_key(company: CompanyRef) -> tuple[str, str]:
    lei = normalise_lei(company.lei or "")
    if lei_is_valid(lei):
        return lei, "LEI"
    return f"ARP:{uuid.uuid5(ARP_NAMESPACE, company.company_id)}", "ARP_PROVISIONAL"
