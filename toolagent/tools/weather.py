from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from .base import Tool, ToolError, TurnContext, request_json

# WMO weather interpretation codes, as used by Open-Meteo
WMO_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle", 56: "light freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "light freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light rain showers", 81: "rain showers", 82: "violent rain showers",
    85: "light snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with light hail", 99: "thunderstorm with heavy hail",
}

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}
COUNTRY_ALIASES = {"usa": "us", "united states of america": "us", "america": "us", "uk": "gb", "england": "gb", "britain": "gb"}


class WeatherArgs(BaseModel):
    location: str = Field(
        min_length=2,
        max_length=100,
        description='City name, optionally with region or country to disambiguate: "Seattle", "Portland, Maine", "Paris, France".',
    )
    days: int = Field(3, ge=1, le=7, description="Days of daily forecast, starting today (1-7). Use 7 for questions about the weekend.")
    units: Literal["metric", "imperial"] = Field("metric", description="metric = °C, km/h, mm; imperial = °F, mph, inches.")


class WeatherTool(Tool):
    name = "get_weather"
    Args = WeatherArgs

    def __init__(self, provider: str):
        self.provider = provider

    @property
    def description(self) -> str:
        return (
            "Current weather and a daily forecast (up to 7 days) for a city, from Open-Meteo. "
            "Returns temperatures, conditions, precipitation amount and chance, and wind, with dates and weekdays "
            "in the city's local time."
        )

    def _urls(self, ctx: TurnContext) -> tuple[str, str]:
        if self.provider == "mock":
            base = ctx.settings.mock_services_url.rstrip("/") + "/open-meteo"
            return f"{base}/geocoding", f"{base}/forecast"
        return ctx.settings.open_meteo_geocoding_url.rstrip("/"), ctx.settings.open_meteo_forecast_url.rstrip("/")

    async def run(self, args: WeatherArgs, ctx: TurnContext) -> dict[str, Any]:
        geocoding_url, forecast_url = self._urls(ctx)
        place, others = await self._geocode(args.location, geocoding_url, ctx)
        imperial = args.units == "imperial"
        params = {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "timezone": "auto",
            "forecast_days": args.days,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
            "precipitation_probability_max,wind_speed_10m_max",
        }
        if imperial:
            params |= {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch"}
        data = await request_json(ctx, "GET", f"{forecast_url}/v1/forecast", service="Open-Meteo", params=params)

        current = data.get("current") or {}
        daily = data.get("daily") or {}
        days = []
        for i, day in enumerate(daily.get("time", [])):
            def pick(key: str) -> Any:
                values = daily.get(key) or []
                return values[i] if i < len(values) else None

            days.append({
                "date": day,
                "weekday": date.fromisoformat(day).strftime("%A"),
                "conditions": WMO_CODES.get(pick("weather_code"), "unknown"),
                "high": pick("temperature_2m_max"),
                "low": pick("temperature_2m_min"),
                "precipitation": pick("precipitation_sum"),
                "precipitation_chance_pct": pick("precipitation_probability_max"),
                "wind_max": pick("wind_speed_10m_max"),
            })
        result: dict[str, Any] = {
            "location": {
                "name": place.get("name"),
                "region": place.get("admin1"),
                "country": place.get("country"),
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "timezone": data.get("timezone"),
            },
            "units": {
                "temperature": "°F" if imperial else "°C",
                "wind": "mph" if imperial else "km/h",
                "precipitation": "inch" if imperial else "mm",
            },
            "current": {
                "local_time": current.get("time"),
                "temperature": current.get("temperature_2m"),
                "feels_like": current.get("apparent_temperature"),
                "humidity_pct": current.get("relative_humidity_2m"),
                "precipitation": current.get("precipitation"),
                "wind": current.get("wind_speed_10m"),
                "conditions": WMO_CODES.get(current.get("weather_code"), "unknown"),
            },
            "daily": days,
            "source": "Open-Meteo (mock)" if self.provider == "mock" else "Open-Meteo",
        }
        if others:
            result["other_places_with_this_name"] = others
        return result

    async def _geocode(self, location: str, base: str, ctx: TurnContext) -> tuple[dict, list[str]]:
        name, _, qualifier = (part.strip() for part in location.partition(","))
        data = await request_json(
            ctx, "GET", f"{base}/v1/search", service="Open-Meteo geocoding",
            params={"name": name, "count": 10, "language": "en", "format": "json"},
        )
        candidates = data.get("results") or []
        if not candidates:
            raise ToolError(f"No place called {name!r} was found. Check the spelling or try a nearby larger city.")
        if qualifier:
            matching = [c for c in candidates if _matches(c, qualifier)]
            if not matching:
                known = "; ".join(_label(c) for c in candidates[:5])
                raise ToolError(f"No {name!r} in {qualifier!r}. Places with that name: {known}.")
            candidates = matching
        best, rest = candidates[0], candidates[1:4]
        # Only mention alternatives when the user didn't already disambiguate and they're notable.
        others = [] if qualifier else [_label(c) for c in rest if (c.get("population") or 0) >= 50_000]
        return best, others


def _matches(place: dict, qualifier: str) -> bool:
    q = qualifier.strip().lower().rstrip(".")
    q = COUNTRY_ALIASES.get(q, q)
    state = US_STATES.get(q.upper())
    fields = {
        (place.get("country") or "").lower(),
        (place.get("country_code") or "").lower(),
        (place.get("admin1") or "").lower(),
        (place.get("admin2") or "").lower(),
    }
    return q in fields or (state is not None and state.lower() in fields)


def _label(place: dict) -> str:
    return ", ".join(p for p in (place.get("name"), place.get("admin1"), place.get("country")) if p)
