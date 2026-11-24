"""Tool contract.

Each tool carries a *capability card* (what it is for, when it is needed, what
it is NOT for). The agent generator selects tools by reasoning over the cards,
and must quote the requirement that justifies each tool; tools without a quoted
justification are dropped deterministically. ``available`` lets a tool veto
itself (e.g. CSV lookup with no tables in the corpus).

Tools never raise into the agent loop: failures come back as ``ToolResult(ok=False)``
so the agent can say "I couldn't look that up" instead of crashing.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class ToolContext:
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    timezone: str = "UTC"
    http_timeout_s: float = 10.0


@dataclass
class ToolResult:
    ok: bool
    output: Any = None
    error: str | None = None

    def to_text(self, max_chars: int = 3000) -> str:
        if not self.ok:
            return f"TOOL ERROR: {self.error}"
        text = self.output if isinstance(self.output, str) else json.dumps(self.output, default=str, ensure_ascii=False)
        return text if len(text) <= max_chars else text[:max_chars] + " ...[truncated]"


@dataclass(frozen=True)
class CapabilityCard:
    purpose: str
    needed_when: str
    not_for: str


class Tool(ABC):
    name: str
    card: CapabilityCard
    parameters: dict  # JSON schema of arguments

    def available(self, ctx: ToolContext) -> tuple[bool, str]:
        return True, ""

    @abstractmethod
    def _run(self, ctx: ToolContext, **kwargs) -> Any: ...

    def run(self, ctx: ToolContext, **kwargs) -> ToolResult:
        try:
            return ToolResult(ok=True, output=self._run(ctx, **kwargs))
        except ToolInputError as exc:
            return ToolResult(ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - tools must never crash the agent
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}"[:300])

    def spec(self) -> dict:
        """Compact spec shown to the agent model."""
        return {
            "name": self.name,
            "purpose": self.card.purpose,
            "arguments": self.parameters,
        }

    def card_text(self) -> str:
        return (
            f"- {self.name}: {self.card.purpose}\n"
            f"  needed when: {self.card.needed_when}\n"
            f"  NOT for: {self.card.not_for}"
        )


class ToolInputError(ValueError):
    """Bad arguments from the model; reported back instead of raised."""
