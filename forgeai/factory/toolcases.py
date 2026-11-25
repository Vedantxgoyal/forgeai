"""Tool test cases for corpora that contain tables. No LLM is involved: Python computes the answer.

Why: cases written from one passage never need a tool, so a table agent could score 100% without ever
using csv_lookup or the calculator. These cases force a record lookup, a multiplication, or a comparison,
and the expected value comes straight from the data, so the ground truth cannot be hallucinated.

Nothing here is domain-specific: the key column, label column and numeric columns are inferred.
"""

from __future__ import annotations

import hashlib
import random
import re

import pandas as pd

from forgeai.schemas import EvalCase

MONEY = re.compile(r"price|cost|rate|amount|fee|charge|salary|value|fare", re.I)


def _label(col: str) -> str:
    return col.replace("_", " ").strip()


def _fmt(x: float) -> str:
    x = round(float(x), 2)
    return str(int(x)) if x == int(x) else f"{x:.2f}"


def _columns(df: pd.DataFrame) -> tuple[str | None, str | None, list[str]]:
    """(unique key column, human-readable name column, numeric columns)."""
    numeric = [c for c in df.columns if pd.to_numeric(df[c], errors="coerce").notna().all()]
    text = [c for c in df.columns if c not in numeric]
    key = next(
        (c for c in df.columns if df[c].astype(str).is_unique and re.search(r"id|no|code|key|sku|ref", str(c), re.I)), None
    )
    key = key or next((c for c in text if df[c].astype(str).is_unique), None)
    name = next((c for c in text if c != key and df[c].astype(str).nunique() > len(df) * 0.6), None)
    return key, name, [c for c in numeric if c != key]


def build_tool_cases(tables: dict[str, pd.DataFrame], n: int, seed: int = 7) -> list[EvalCase]:
    rng = random.Random(seed)
    cases: list[EvalCase] = []
    for table, df in sorted(tables.items()):
        key, name, nums = _columns(df)
        if key is None or not nums or len(df) < 2:
            continue
        money = [c for c in nums if MONEY.search(str(c))]
        rows = list(df.index)
        rng.shuffle(rows)

        def who(i) -> str:
            extra = f" ({df.at[i, name]})" if name else ""
            return f"{df.at[i, key]}{extra}"

        def cell(i, col: str) -> dict:
            return {
                "table": table,
                "key_column": str(key),
                "key": str(df.at[i, key]),
                "column": str(col),
                "value": str(df.at[i, col]),
            }

        def add(question: str, facts: list[str], ref: str, evidence: list[dict]) -> None:
            cid = "too-" + hashlib.sha1(question.encode()).hexdigest()[:6]
            cases.append(
                EvalCase(
                    id=cid,
                    type="tool",
                    question=question,
                    reference_answer=ref,
                    key_facts=facts,
                    source_docs=[table],
                    evidence=evidence,
                )
            )

        for k in range(n):
            i, j = rows[(2 * k) % len(rows)], rows[(2 * k + 1) % len(rows)]
            kind = ("multiply", "compare", "lookup")[k % 3]
            if kind == "multiply" and money:
                col, qty = money[0], rng.randint(3, 19)
                total = float(df.at[i, col]) * qty
                add(
                    f"What is the total for {qty} units of {who(i)} based on its {_label(col)}, before any discounts, surcharges or taxes?",
                    [_fmt(total)],
                    f"{qty} x {_fmt(df.at[i, col])} = {_fmt(total)}",
                    [cell(i, col)],
                )
            elif kind == "compare":
                col = money[0] if money else nums[0]
                a, b = float(df.at[i, col]), float(df.at[j, col])
                if a == b:
                    continue
                add(
                    f"What is the exact difference in {_label(col)} between {who(i)} and {who(j)}?",
                    [_fmt(abs(a - b))],
                    f"|{_fmt(a)} - {_fmt(b)}| = {_fmt(abs(a - b))}",
                    [cell(i, col), cell(j, col)],
                )
            else:
                other = [c for c in nums if c not in money] or nums
                c1 = other[k % len(other)]
                add(
                    f"What is the {_label(c1)} recorded for {who(i)}?",
                    [_fmt(df.at[i, c1])],
                    f"{_label(c1)} = {_fmt(df.at[i, c1])}",
                    [cell(i, c1)],
                )
            if len(cases) >= n:
                return cases
    return cases[:n]
