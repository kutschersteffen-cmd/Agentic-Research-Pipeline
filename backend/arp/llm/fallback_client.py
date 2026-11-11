"""An Anthropic client that moves to Gemini for good once Anthropic refuses a call for credit or auth."""

from __future__ import annotations

import logging
from collections.abc import Callable

import anthropic

from arp.llm.base import LLMClient, LLMUsage, T

log = logging.getLogger(__name__)


def is_credit_or_auth_error(exc: Exception) -> bool:
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return True
    return isinstance(exc, anthropic.BadRequestError) and "credit balance" in str(exc).lower()


class FallbackLLMClient:
    """`warning` is logged once, when the first call moves to Gemini; `make_gemini` builds that client lazily."""

    def __init__(self, primary: LLMClient, make_gemini: Callable[[], LLMClient], warning: str) -> None:
        self._primary, self._make_gemini, self._warning = primary, make_gemini, warning
        self._gemini: LLMClient | None = None

    async def complete_structured(self, **kwargs) -> tuple[T, LLMUsage]:
        if self._gemini is None:
            try:
                return await self._primary.complete_structured(**kwargs)
            except Exception as exc:
                if not is_credit_or_auth_error(exc):
                    raise
                log.warning(self._warning)
                self._gemini = self._make_gemini()
        return await self._gemini.complete_structured(**kwargs)
