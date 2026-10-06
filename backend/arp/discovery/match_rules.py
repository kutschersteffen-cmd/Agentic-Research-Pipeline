from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from arp.schemas.common import CompanyRef
from arp.schemas.discovery import IdentityResolutionResult, IdentitySignals
from arp.schemas.issuer import lei_is_valid, normalise_lei
from arp.storage.identifier_map import IdentifierMapStore, normalise_identifier


class MatchRule(StrEnum):
    EXACT_LEI = "exact_lei"
    IDENTIFIER_MAP = "identifier_map"
    SUPPLIED = "supplied"
    NAME_ONLY = "name_only"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class RuleOutcome:
    rule: MatchRule
    resolved: bool
    issuer_key: str | None
    candidates: list[str]


def identifiers_of(company: CompanyRef) -> dict[str, str]:
    raw = {
        "lei": normalise_lei(company.lei or ""),
        "cik": normalise_identifier("CIK", company.cik or ""),
        "isin": normalise_identifier("ISIN", company.isin or ""),
    }
    return {k: v for k, v in raw.items() if v}


def apply_identifier_rules(company: CompanyRef, idmap: IdentifierMapStore | None) -> RuleOutcome | None:
    lei = normalise_lei(company.lei or "")
    ids = identifiers_of(company)
    # The security master (identifier map) is the golden source: an identifier it knows wins, LEI included.
    if idmap is not None:
        for field, scheme in (("lei", "LEI"), ("cik", "CIK"), ("isin", "ISIN")):
            if field not in ids:
                continue
            keys = idmap.resolve(scheme, ids[field])
            if len(keys) == 1:
                return RuleOutcome(MatchRule.IDENTIFIER_MAP, True, keys[0], [])
            if keys:
                return RuleOutcome(MatchRule.AMBIGUOUS, False, None, keys)
    if lei_is_valid(lei):
        return RuleOutcome(MatchRule.EXACT_LEI, True, lei, [])
    if company.website or company.cik:
        return RuleOutcome(MatchRule.SUPPLIED, True, None, [])
    return None


def apply_name_rules(company: CompanyRef, signals: IdentitySignals) -> RuleOutcome | None:
    """Exactly one EDGAR match whose title equals the name. Trusted enough to
    skip the model, not enough to skip review."""
    if len(signals.edgar_matches) != 1:
        return None
    match = signals.edgar_matches[0]
    if match.title.strip().lower() != company.name.strip().lower():
        return None
    return RuleOutcome(MatchRule.NAME_ONLY, False, None, [match.cik])


def needs_recheck(result: IdentityResolutionResult, company: CompanyRef, idmap: IdentifierMapStore | None) -> bool:
    if not result.match_rule:  # legacy row: never reuse, it predates the always-review rule
        return True
    if identifiers_of(company) != result.identifiers:
        return True
    outcome = apply_identifier_rules(company, idmap)
    if outcome is None:
        return result.match_rule in (MatchRule.EXACT_LEI, MatchRule.IDENTIFIER_MAP, MatchRule.SUPPLIED)
    return outcome.issuer_key != result.resolved_issuer_key or outcome.rule != result.match_rule
