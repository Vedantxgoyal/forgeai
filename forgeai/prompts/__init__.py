"""Prompt templates live as versioned Markdown files next to this module.

Templates use ``{{name}}`` placeholders (not ``str.format``) so JSON examples
inside prompts never need brace escaping.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent
_VAR = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


@lru_cache(maxsize=None)
def _raw(name: str) -> str:
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def render(name: str, **variables: object) -> str:
    """Render a prompt; every placeholder must be supplied (fail loudly, not silently)."""
    template = _raw(name)
    missing = {m for m in _VAR.findall(template)} - variables.keys()
    if missing:
        raise KeyError(f"prompt '{name}' missing variables: {sorted(missing)}")
    return _VAR.sub(lambda m: str(variables[m.group(1)]), template)
