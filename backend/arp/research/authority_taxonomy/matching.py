from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from arp.llm.base import LLMClient
from arp.schemas.authority_taxonomy import merge_key
from arp.schemas.thematic import ActivityDefinition

IGNORED_WORDS = frozenset(
    ["a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "other", "the", "to", "with", "manufacture", "manufacturing", "manufacturer", "production", "producing", "equipment", "products", "activities", "activity"]
)

_SYSTEM = """\
You decide whether pairs of economic activities, taken from authority sources, describe the same activity.
Scope of the taxonomy: {scope}
For every pair return its left and right index, same_activity (true only when both describe the same activity),
and a one-sentence reason."""


class Match(BaseModel):
    left: int
    right: int
    method: Literal["exact", "model"]
    reason: str


class _PairVerdict(BaseModel):
    left: int
    right: int
    same_activity: bool
    reason: str


class _MatchReviewDraft(BaseModel):
    pairs: list[_PairVerdict] = []


def keywords(activity: ActivityDefinition) -> set[str]:
    words = re.split(r"[^a-z0-9]+", " ".join([activity.name, *activity.seed_keywords]).lower())
    return {w[:6] for w in words if len(w) >= 3 and w not in IGNORED_WORDS}


async def match_activities(
    left: list[ActivityDefinition], right: list[ActivityDefinition], *, scope: str, llm: LLMClient
) -> list[Match]:
    """Exact merge-key matches, plus keyword-candidate pairs the model confirms; each activity matches at most once."""
    lk, rk = [keywords(a) for a in left], [keywords(a) for a in right]
    exact = {(i, j) for i, a in enumerate(left) for j, b in enumerate(right) if merge_key(a.name) == merge_key(b.name)}
    candidates = [(i, j) for i in range(len(left)) for j in range(len(right)) if (i, j) not in exact and lk[i] & rk[j]]
    verdicts: dict[tuple[int, int], str] = {}
    if candidates:
        listing = "\n".join(f"left={i} {left[i].name!r} | right={j} {right[j].name!r}" for i, j in candidates)
        draft, _usage = await llm.complete_structured(
            system=_SYSTEM.format(scope=scope or "(none given)"),
            prompt=f"Scope: {scope or '(none given)'}\n\nPairs:\n{listing}",
            output_model=_MatchReviewDraft,
        )
        verdicts = {(p.left, p.right): p.reason for p in draft.pairs if p.same_activity and (p.left, p.right) in candidates}
    matches: list[Match] = []
    used_l: set[int] = set()
    used_r: set[int] = set()
    for i, j in sorted(exact | verdicts.keys()):
        if i in used_l or j in used_r:
            continue
        used_l.add(i)
        used_r.add(j)
        if (i, j) in exact:
            matches.append(Match(left=i, right=j, method="exact", reason="equal merge key"))
        else:
            matches.append(Match(left=i, right=j, method="model", reason=verdicts[(i, j)]))
    return matches
