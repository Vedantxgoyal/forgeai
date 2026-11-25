from __future__ import annotations

import pandas as pd
import pytest

from forgeai.tools import REGISTRY, ToolContext, get_tools, registry_cards
from forgeai.tools.builtin import safe_eval


@pytest.fixture
def ctx():
    df = pd.DataFrame(
        {
            "part_no": ["MP-1001", "MP-1002", "AB-2207"],
            "description": ["Main engine fuel injector", "Cylinder liner gasket", "Ballast pump impeller"],
            "unit_price_usd": ["1250.50", "85.00", "640.00"],
            "supplier": ["Wartsila Spares", "Marine Parts Co", "Marine Parts Co"],
        }
    )
    return ToolContext(tables={"catalogue": df}, timezone="Asia/Kolkata")


# calculator ------------------------------------------------------------------
@pytest.mark.parametrize(
    "expr, value",
    [
        ("4 * 1250.50", 5002),
        ("(85 + 640) * (1 - 0.05)", 688.75),
        ("2^10", 1024),
        ("round(10/3, 2)", 3.33),
        ("1,250.50 * 2", 2501),
        ("max(3, 9, 4)", 9),
        ("-5 + sqrt(16)", -1),
    ],
)
def test_calculator(expr, value):
    assert safe_eval(expr) == value


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('ls')",
        "open('x')",
        "a + 1",
        "9 ** 999999",
        "1/0",
        "[1,2]",
        "True + 1",
    ],
)
def test_calculator_rejects_unsafe_or_invalid(expr):
    res = REGISTRY["calculator"].run(ToolContext(), expression=expr)
    assert not res.ok and res.error


# csv lookup ------------------------------------------------------------------
def test_csv_filter_exact(ctx):
    res = REGISTRY["csv_lookup"].run(ctx, filters={"part_no": "ab-2207"})
    assert res.ok and res.output["matched"] == 1 and res.output["rows"][0]["unit_price_usd"] == "640.00"


def test_csv_fuzzy_column_and_contains(ctx):
    res = REGISTRY["csv_lookup"].run(ctx, filters={"Supplier": "marine parts"}, columns=["part no"])
    assert res.ok and res.output["matched"] == 2 and list(res.output["rows"][0]) == ["part_no"]


def test_csv_free_text_query(ctx):
    res = REGISTRY["csv_lookup"].run(ctx, query="fuel injector")
    assert res.ok and res.output["rows"][0]["part_no"] == "MP-1001"


def test_csv_unknown_column_is_reported_not_raised(ctx):
    res = REGISTRY["csv_lookup"].run(ctx, filters={"colour": "red"})
    assert not res.ok and "Available" in res.error


def test_csv_unavailable_without_tables():
    ok, why = REGISTRY["csv_lookup"].available(ToolContext())
    assert not ok and "no tabular" in why


# date / weather ---------------------------------------------------------------
def test_current_date(ctx):
    res = REGISTRY["current_date"].run(ctx)
    assert res.ok and res.output["timezone"] == "Asia/Kolkata" and len(res.output["date"]) == 10
    assert not REGISTRY["current_date"].run(ctx, timezone="Mars/Olympus").ok


def test_weather_uses_open_meteo(monkeypatch, ctx):
    import httpx

    def handler(request: httpx.Request):
        if "geocoding" in request.url.host:
            return httpx.Response(
                200, json={"results": [{"name": "Rotterdam", "country": "Netherlands", "latitude": 51.9, "longitude": 4.5}]}
            )
        assert request.url.params["latitude"] == "51.9"
        return httpx.Response(
            200, json={"current": {"temperature_2m": 9.1}, "current_units": {"temperature_2m": "°C"}, "daily": {}}
        )

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    res = REGISTRY["weather"].run(ctx, location="Rotterdam")
    assert res.ok and res.output["place"] == "Rotterdam, Netherlands" and res.output["current"]["temperature_2m"] == 9.1


def test_weather_network_failure_is_contained(monkeypatch, ctx):
    import httpx

    def boom(request):
        raise httpx.ConnectError("offline")

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(boom), **kw))
    res = REGISTRY["weather"].run(ctx, location="Rotterdam")
    assert not res.ok and "ConnectError" in res.error


# registry --------------------------------------------------------------------
def test_registry_and_cards(ctx):
    assert set(REGISTRY) == {"csv_lookup", "calculator", "weather", "current_date"}
    with pytest.raises(KeyError):
        get_tools(["calculator", "email"])
    assert "UNAVAILABLE" in registry_cards(ToolContext()) and "UNAVAILABLE" not in registry_cards(ctx)
