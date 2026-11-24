from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """User-facing LLM failure (never contains secrets)."""


@dataclass
class LLMResult:
    output: BaseModel
    input_tokens: int
    output_tokens: int
    model: str


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def structured(self, system: str, user: str, schema: type[T], max_tokens: int = 16000) -> LLMResult:
        """Return an instance of ``schema`` validated against the model's JSON output."""
