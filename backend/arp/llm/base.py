from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False
    attempts: int = 1


class LLMClient(ABC):
    """Abstraction over the underlying model provider.

    Every agent in this codebase talks to models exclusively through
    `complete_structured`, never free text, so that outputs are always
    schema-validated before anything downstream trusts them.
    """

    @abstractmethod
    async def complete_structured(
        self,
        *,
        system: str,
        prompt: str,
        output_model: type[T],
        max_validation_retries: int = 2,
        temperature: float = 0.0,
        max_tokens: int = 8192,
    ) -> tuple[T, LLMUsage]:
        """Call the model and return a validated instance of `output_model`.

        Implementations must retry (re-prompting with the validation error)
        up to `max_validation_retries` times if the model's output fails
        Pydantic validation, and must separately retry on transient
        network/rate-limit errors.
        """
        raise NotImplementedError
