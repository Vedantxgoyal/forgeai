"""Tool registry. Add a tool by subclassing ``Tool`` and listing it here."""

from __future__ import annotations

from forgeai.tools.base import CapabilityCard, Tool, ToolContext, ToolInputError, ToolResult
from forgeai.tools.builtin import Calculator, CsvLookup, CurrentDate, Weather

REGISTRY: dict[str, Tool] = {t.name: t for t in (CsvLookup(), Calculator(), Weather(), CurrentDate())}


def get_tools(names: list[str]) -> list[Tool]:
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise KeyError(f"unknown tool(s): {unknown}; registry has {sorted(REGISTRY)}")
    return [REGISTRY[n] for n in names]


def registry_cards(ctx: ToolContext | None = None) -> str:
    """Capability cards for the generator prompt, marking tools unusable for this corpus."""
    lines = []
    for t in REGISTRY.values():
        text = t.card_text()
        if ctx is not None:
            ok, why = t.available(ctx)
            if not ok:
                text += f"\n  UNAVAILABLE for this corpus: {why}"
        lines.append(text)
    return "\n".join(lines)


__all__ = [
    "REGISTRY",
    "Tool",
    "ToolContext",
    "ToolResult",
    "ToolInputError",
    "CapabilityCard",
    "get_tools",
    "registry_cards",
]
