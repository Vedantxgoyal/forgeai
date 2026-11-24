"""The four registry tools: csv_lookup, calculator, weather, current_date."""

from __future__ import annotations

import ast
import math
import operator
import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
from rapidfuzz import fuzz, process

from forgeai.tools.base import CapabilityCard, Tool, ToolContext, ToolInputError


# --------------------------------------------------------------------------- #
# Calculator - safe AST evaluation (no eval/exec, bounded exponent)
# --------------------------------------------------------------------------- #
_BIN = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    "round": round, "abs": abs, "min": min, "max": max, "sqrt": math.sqrt,
    "ceil": math.ceil, "floor": math.floor, "sum": lambda *a: sum(a),
}
_MAX_EXP = 100
_MAX_LEN = 300


def safe_eval(expr: str) -> float | int:
    if len(expr) > _MAX_LEN:
        raise ToolInputError("expression too long")
    # '^' as power and thousands separators ('1,250.50') are common model habits.
    expr = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", expr.replace("^", "**"))
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ToolInputError(f"invalid expression: {exc.msg}") from exc

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXP:
                raise ToolInputError("exponent too large")
            if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
                raise ToolInputError("division by zero")
            return _BIN[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ToolInputError(f"unsupported syntax: {type(node).__name__}")

    result = ev(tree)
    if isinstance(result, float):
        if math.isinf(result) or math.isnan(result):
            raise ToolInputError("result is not a finite number")
        result = round(result, 10)
        if result.is_integer():
            result = int(result)
    return result


class Calculator(Tool):
    name = "calculator"
    card = CapabilityCard(
        purpose="Exact arithmetic on numbers: totals, unit price x quantity, percentages, discounts, day counts.",
        needed_when="Users ask for computed values (sums, costs, percentages, pro-rata amounts) rather than values stated verbatim in documents.",
        not_for="Looking up facts, dates, or text; answering questions whose numbers are stated directly in the documents.",
    )
    parameters = {
        "type": "object",
        "properties": {"expression": {"type": "string", "description": "e.g. '4 * 1250.50 * (1 - 0.05)'"}},
        "required": ["expression"],
    }

    def _run(self, ctx, expression: str = "", **_):
        if not expression:
            raise ToolInputError("missing 'expression'")
        return {"expression": expression, "result": safe_eval(expression)}


# --------------------------------------------------------------------------- #
# CSV lookup
# --------------------------------------------------------------------------- #
class CsvLookup(Tool):
    name = "csv_lookup"
    card = CapabilityCard(
        purpose="Look up exact rows in the tabular files (CSV/TSV/XLSX) of the knowledge base: filter by column values or fuzzy-search a term.",
        needed_when="The documents include tables (catalogues, price lists, inventories, rosters) and users ask for specific records, codes, prices, stock levels or attributes.",
        not_for="Narrative policy text, or corpora without any tabular files.",
    )
    parameters = {
        "type": "object",
        "properties": {
            "table": {"type": "string", "description": "table id; optional if only one table"},
            "filters": {"type": "object", "description": "column -> value; case-insensitive exact or contains match"},
            "query": {"type": "string", "description": "free-text fuzzy search across text columns"},
            "columns": {"type": "array", "items": {"type": "string"}, "description": "columns to return"},
            "limit": {"type": "integer", "default": 10},
        },
    }

    def available(self, ctx):
        return (bool(ctx.tables), "" if ctx.tables else "no tabular files in the corpus")

    @staticmethod
    def _match_name(name: str, options: list[str], what: str) -> str:
        if name in options:
            return name
        lowered = {o.lower(): o for o in options}
        if name.lower() in lowered:
            return lowered[name.lower()]
        best = process.extractOne(name, options, scorer=fuzz.WRatio)
        if best and best[1] >= 80:
            return best[0]
        raise ToolInputError(f"unknown {what} '{name}'. Available: {options}")

    def _run(self, ctx, table: str | None = None, filters: dict | None = None, query: str | None = None,
             columns: list[str] | None = None, limit: int = 10, **_):
        if not ctx.tables:
            raise ToolInputError("no tables available")
        names = list(ctx.tables)
        if table is None:
            if len(names) > 1:
                raise ToolInputError(f"specify 'table', one of {names}")
            table = names[0]
        table = self._match_name(table, names, "table")
        df: pd.DataFrame = ctx.tables[table]
        cols = list(df.columns)
        mask = pd.Series(True, index=df.index)

        for col, val in (filters or {}).items():
            c = self._match_name(str(col), cols, "column")
            series = df[c].astype(str).str.strip().str.lower()
            v = str(val).strip().lower()
            exact = series == v
            mask &= exact if exact.any() else series.str.contains(v, regex=False)

        out = df[mask]
        if query:
            text_cols = [c for c in cols if df[c].astype(str).str.contains(r"[A-Za-z]", regex=True).any()]
            joined = out[text_cols].astype(str).agg(" ".join, axis=1)
            scores = joined.map(lambda s: fuzz.token_set_ratio(query.lower(), s.lower()))
            out = out.assign(_score=scores)
            out = out[out["_score"] >= 60].sort_values("_score", ascending=False).drop(columns="_score")

        limit = max(1, min(int(limit or 10), 50))
        if columns:
            out = out[[self._match_name(c, cols, "column") for c in columns]]
        return {"table": table, "matched": int(len(out)), "rows": out.head(limit).to_dict(orient="records")}


# --------------------------------------------------------------------------- #
# Weather (open-meteo, keyless)
# --------------------------------------------------------------------------- #
class Weather(Tool):
    name = "weather"
    card = CapabilityCard(
        purpose="Current conditions and a 3-day forecast for a named place or coordinates (open-meteo, live).",
        needed_when="Users ask about present or upcoming weather, wind or sea conditions at a location (e.g. port calls, field work, travel).",
        not_for="Anything answerable from the documents; historical climate; HR, finance, procurement or policy questions.",
    )
    parameters = {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "place name, e.g. 'Rotterdam'"},
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
        },
    }

    def _run(self, ctx, location: str | None = None, latitude: float | None = None, longitude: float | None = None, **_):
        import httpx

        with httpx.Client(timeout=ctx.http_timeout_s) as http:
            place = None
            if latitude is None or longitude is None:
                if not location:
                    raise ToolInputError("give 'location' or both 'latitude' and 'longitude'")
                g = http.get("https://geocoding-api.open-meteo.com/v1/search",
                             params={"name": location, "count": 1, "format": "json"})
                g.raise_for_status()
                results = g.json().get("results") or []
                if not results:
                    raise ToolInputError(f"location not found: {location}")
                r0 = results[0]
                latitude, longitude = r0["latitude"], r0["longitude"]
                place = ", ".join(x for x in (r0.get("name"), r0.get("country")) if x)
            f = http.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": latitude, "longitude": longitude,
                "current": "temperature_2m,wind_speed_10m,wind_gusts_10m,precipitation,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
                "forecast_days": 3, "timezone": "auto",
            })
            f.raise_for_status()
            data = f.json()
        return {
            "place": place or f"{latitude},{longitude}",
            "current": data.get("current", {}),
            "daily": data.get("daily", {}),
            "units": {**data.get("current_units", {}), **data.get("daily_units", {})},
            "source": "open-meteo.com",
        }


# --------------------------------------------------------------------------- #
# Current date
# --------------------------------------------------------------------------- #
class CurrentDate(Tool):
    name = "current_date"
    card = CapabilityCard(
        purpose="Today's date, weekday and time in a timezone.",
        needed_when="Answers depend on 'today': deadlines, notice periods counted from now, eligibility windows, ages of records, 'is X still valid'.",
        not_for="Questions about dates stated in the documents themselves.",
    )
    parameters = {
        "type": "object",
        "properties": {"timezone": {"type": "string", "description": "IANA name, e.g. 'Asia/Kolkata'"}},
    }

    def _run(self, ctx, timezone: str | None = None, **_):
        tzname = timezone or ctx.timezone
        try:
            tz = ZoneInfo(tzname)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ToolInputError(f"unknown timezone '{tzname}'") from exc
        now = datetime.now(tz)
        return {"date": now.date().isoformat(), "weekday": now.strftime("%A"),
                "time": now.strftime("%H:%M"), "timezone": tzname}
