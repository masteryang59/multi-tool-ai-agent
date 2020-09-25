import httpx
import pytest

from toolagent.tools import ToolError, TurnContext, WeatherTool
from toolagent.tools.weather import WeatherArgs


async def weather(ctx, **kwargs):
    return await WeatherTool("mock").run(WeatherArgs(**kwargs), ctx)


async def test_forecast_for_a_city(ctx):
    result = await weather(ctx, location="Seattle", days=3)
    assert result["location"]["name"] == "Seattle"
    assert result["location"]["region"] == "Washington"
    assert result["location"]["timezone"] == "America/Los_Angeles"
    assert len(result["daily"]) == 3
    day = result["daily"][0]
    assert set(day) >= {"date", "weekday", "conditions", "high", "low", "precipitation", "precipitation_chance_pct"}
    assert day["high"] >= day["low"]
    assert result["units"]["temperature"] == "°C"
    assert result["current"]["conditions"] != "unknown"


async def test_ambiguous_name_picks_the_biggest_and_lists_others(ctx):
    result = await weather(ctx, location="Portland")
    assert result["location"]["region"] == "Oregon"
    assert result["other_places_with_this_name"] == ["Portland, Maine, United States"]


@pytest.mark.parametrize("location, region", [
    ("Portland, Maine", "Maine"),
    ("Portland, ME", "Maine"),
    ("Paris, TX", "Texas"),
    ("Paris, France", "Île-de-France"),
    ("London, Canada", "Ontario"),
    ("London, UK", "England"),
    ("Springfield, MO", "Missouri"),
])
async def test_qualifiers_disambiguate(ctx, location, region):
    result = await weather(ctx, location=location)
    assert result["location"]["region"] == region
    assert "other_places_with_this_name" not in result


async def test_wrong_qualifier_lists_the_real_options(ctx):
    with pytest.raises(ToolError, match=r"No 'Paris' in 'Germany'.*Paris, Texas"):
        await weather(ctx, location="Paris, Germany")


async def test_unknown_place(ctx):
    with pytest.raises(ToolError, match="No place called 'Atlantis'"):
        await weather(ctx, location="Atlantis")


async def test_imperial_units(ctx):
    metric = await weather(ctx, location="Austin", days=1)
    imperial = await weather(ctx, location="Austin", days=1, units="imperial")
    assert imperial["units"] == {"temperature": "°F", "wind": "mph", "precipitation": "inch"}
    assert imperial["daily"][0]["high"] == pytest.approx(metric["daily"][0]["high"] * 9 / 5 + 32, abs=0.2)


def test_args_are_validated():
    with pytest.raises(ValueError):
        WeatherArgs(location="Seattle", days=30)


async def test_upstream_errors_become_tool_errors(settings):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(503, text="maintenance")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        ctx = TurnContext(settings=settings, http=http)
        with pytest.raises(ToolError, match="Open-Meteo geocoding returned HTTP 503"):
            await WeatherTool("open-meteo").run(WeatherArgs(location="Seattle"), ctx)
    assert len(calls) == 2  # one retry on 5xx


async def test_real_provider_uses_the_real_urls_and_parameters(settings):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if request.url.host == "geocoding-api.open-meteo.com":
            return httpx.Response(200, json={"results": [{"name": "Oslo", "latitude": 59.9, "longitude": 10.7, "country": "Norway", "admin1": "Oslo"}]})
        return httpx.Response(200, json={
            "timezone": "Europe/Oslo",
            "current": {"time": "2026-10-29T12:00", "temperature_2m": 4.1, "weather_code": 71},
            "daily": {"time": ["2026-10-29"], "weather_code": [73], "temperature_2m_max": [5.0], "temperature_2m_min": [-1.0],
                      "precipitation_sum": [3.2], "precipitation_probability_max": [80], "wind_speed_10m_max": [20.0]},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await WeatherTool("open-meteo").run(WeatherArgs(location="Oslo", days=1, units="imperial"), TurnContext(settings=settings, http=http))
    geo, forecast = seen
    assert str(geo).startswith("https://geocoding-api.open-meteo.com/v1/search?name=Oslo")
    assert forecast.host == "api.open-meteo.com" and forecast.path == "/v1/forecast"
    assert forecast.params["temperature_unit"] == "fahrenheit" and forecast.params["forecast_days"] == "1"
    assert result["daily"][0] == {
        "date": "2026-10-29", "weekday": "Thursday", "conditions": "snow", "high": 5.0, "low": -1.0,
        "precipitation": 3.2, "precipitation_chance_pct": 80, "wind_max": 20.0,
    }
    assert result["current"]["conditions"] == "light snow"

def span_context(data=None):
    if data is None:
        return None
    return data