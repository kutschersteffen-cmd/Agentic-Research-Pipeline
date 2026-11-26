"""The one model call of the risk view (theme-risk-mode A4); risk mode reuses it."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MitigationQuotes(BaseModel):
    quotes: list[str] = Field(default_factory=list)


MITIGATION_SYSTEM = (
    "You read one risk that a company describes in its annual report. List the actions the company says it takes "
    "to reduce or manage this risk, each as an exact quote copied word for word from the text. Do not include "
    "statements that the company cannot or does not mitigate the risk. Return an empty list if it states none."
)


def mitigation_prompt(heading: str, body: str) -> str:
    return f"Risk: {heading}\n\nText:\n{body}"
