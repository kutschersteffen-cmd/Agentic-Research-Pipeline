"""Infer a taxonomy from a set of stocks."""
from arp.schemas.taxonomy import DerivationMethod

RETIRED = {DerivationMethod.EMPIRICAL, DerivationMethod.ETF_INDEX_HOLDINGS}


def retired_message(m: DerivationMethod) -> str:
    return f"--method {m.value} is replaced by 'arp taxonomy infer start --stocks <file>'."
