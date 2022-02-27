"""A fake Open-Meteo: same URLs, parameters and response shape, invented but deterministic weather.

Each place has a climate profile, and the weather for a given place and day comes from a seeded
random generator, so tests and screenshots are repeatable. Seattle is reliably wet.
"""

import hashlib
import math
import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

router = APIRouter()

# Fields as returned by the real geocoding API (a subset). utc_offset ignores daylight saving time.
PLACES = [
    {"id": 5809844, "name": "Seattle", "latitude": 47.60621, "longitude": -122.33207, "country_code": "US", "country": "United States", "admin1": "Washington", "timezone": "America/Los_Angeles", "population": 737015, "utc_offset": -7, "climate": "wet"},
    {"id": 5746545, "name": "Portland", "latitude": 45.52345, "longitude": -122.67621, "country_code": "US", "country": "United States", "admin1": "Oregon", "timezone": "America/Los_Angeles", "population": 652503, "utc_offset": -7, "climate": "wet"},
    {"id": 4975802, "name": "Portland", "latitude": 43.65737, "longitude": -70.2589, "country_code": "US", "country": "United States", "admin1": "Maine", "timezone": "America/New_York", "population": 66881, "utc_offset": -4, "climate": "mixed"},
    {"id": 5419384, "name": "Denver", "latitude": 39.73915, "longitude": -104.9847, "country_code": "US", "country": "United States", "admin1": "Colorado", "timezone": "America/Denver", "population": 715522, "utc_offset": -6, "climate": "cold"},
    {"id": 5037649, "name": "Minneapolis", "latitude": 44.97997, "longitude": -93.26384, "country_code": "US", "country": "United States", "admin1": "Minnesota", "timezone": "America/Chicago", "population": 425336, "utc_offset": -5, "climate": "cold"},
    {"id": 4930956, "name": "Boston", "latitude": 42.35843, "longitude": -71.05977, "country_code": "US", "country": "United States", "admin1": "Massachusetts", "timezone": "America/New_York", "population": 675647, "utc_offset": -4, "climate": "mixed"},
    {"id": 4671654, "name": "Austin", "latitude": 30.26715, "longitude": -97.74306, "country_code": "US", "country": "United States", "admin1": "Texas", "timezone": "America/Chicago", "population": 961855, "utc_offset": -5, "climate": "hot"},
    {"id": 2988507, "name": "Paris", "latitude": 48.85341, "longitude": 2.3488, "country_code": "FR", "country": "France", "admin1": "Île-de-France", "timezone": "Europe/Paris", "population": 2138551, "utc_offset": 1, "climate": "mild"},
    {"id": 4717560, "name": "Paris", "latitude": 33.66094, "longitude": -95.55551, "country_code": "US", "country": "United States", "admin1": "Texas", "timezone": "America/Chicago", "population": 24782, "utc_offset": -5, "climate": "hot"},
    {"id": 4250542, "name": "Springfield", "latitude": 39.80172, "longitude": -89.64371, "country_code": "US", "country": "United States", "admin1": "Illinois", "timezone": "America/Chicago", "population": 114230, "utc_offset": -5, "climate": "mixed"},
    {"id": 4409896, "name": "Springfield", "latitude": 37.21533, "longitude": -93.29824, "country_code": "US", "country": "United States", "admin1": "Missouri", "timezone": "America/Chicago", "population": 169176, "utc_offset": -5, "climate": "mixed"},
    {"id": 4951788, "name": "Springfield", "latitude": 42.10148, "longitude": -72.58981, "country_code": "US", "country": "United States", "admin1": "Massachusetts", "timezone": "America/New_York", "population": 155929, "utc_offset": -4, "climate": "mixed"},
    {"id": 2643743, "name": "London", "latitude": 51.50853, "longitude": -0.12574, "country_code": "GB", "country": "United Kingdom", "admin1": "England", "timezone": "Europe/London", "population": 8961989, "utc_offset": 0, "climate": "wet"},
    {"id": 6058560, "name": "London", "latitude": 42.98339, "longitude": -81.23304, "country_code": "CA", "country": "Canada", "admin1": "Ontario", "timezone": "America/Toronto", "population": 346765, "utc_offset": -4, "climate": "mixed"},
    {"id": 1850147, "name": "Tokyo", "latitude": 35.6895, "longitude": 139.69171, "country_code": "JP", "country": "Japan", "admin1": "Tokyo", "timezone": "Asia/Tokyo", "population": 9733276, "utc_offset": 9, "climate": "mild"},
    {"id": 2147714, "name": "Sydney", "latitude": -33.86785, "longitude": 151.20732, "country_code": "AU", "country": "Australia", "admin1": "New South Wales", "timezone": "Australia/Sydney", "population": 4627345, "utc_offset": 11, "climate": "mild"},
]

# climate -> (mean temperature °C in the warmest month, seasonal swing, daily chance of rain)
CLIMATES = {"wet": (19, 8, 0.65), "cold": (23, 15, 0.25), "mixed": (24, 12, 0.35), "hot": (30, 9, 0.2), "mild": (24, 9, 0.3)}
PUBLIC_FIELDS = ("id", "name", "latitude", "longitude", "country_code", "country", "admin1", "timezone", "population")


@router.get("/geocoding/v1/search")
def search(name: str = Query(min_length=1), count: int = 10, language: str = "en", format: str = "json") -> dict:
    needle = name.strip().lower()
    matches = [p for p in PLACES if p["name"].lower().startswith(needle)] if len(needle) >= 2 else []
    matches.sort(key=lambda p: -p["population"])
    result: dict = {"generationtime_ms": 0.2}
    if matches:  # like the real API, no "results" key when nothing matches
        result["results"] = [{k: p[k] for k in PUBLIC_FIELDS} for p in matches[:count]]
    return result


@router.get("/forecast/v1/forecast")
def forecast(
    latitude: float,
    longitude: float,
    timezone_: str = Query("GMT", alias="timezone"),
    forecast_days: int = Query(7, ge=1, le=16),
    current: str = "",
    daily: str = "",
    temperature_unit: str = "celsius",
    wind_speed_unit: str = "kmh",
    precipitation_unit: str = "mm",
) -> dict:
    place = min(PLACES, key=lambda p: (p["latitude"] - latitude) ** 2 + (p["longitude"] - longitude) ** 2)
    offset = place["utc_offset"]
    now = datetime.now(timezone.utc) + timedelta(hours=offset)
    f = temperature_unit == "fahrenheit"
    mph = wind_speed_unit == "mph"
    inch = precipitation_unit == "inch"

    def temp(c: float) -> float:
        return round(c * 9 / 5 + 32, 1) if f else round(c, 1)

    def wind(k: float) -> float:
        return round(k / 1.609, 1) if mph else round(k, 1)

    def rain(mm: float) -> float:
        return round(mm / 25.4, 3) if inch else round(mm, 2)

    days = [_day(place, (now + timedelta(days=i)).date()) for i in range(forecast_days)]
    today = days[0]
    hour_factor = math.sin((now.hour - 9) / 24 * 2 * math.pi)
    current_values = {
        "temperature_2m": temp(today["low"] + (today["high"] - today["low"]) * (0.5 + 0.5 * hour_factor)),
        "apparent_temperature": temp(today["low"] + (today["high"] - today["low"]) * (0.5 + 0.5 * hour_factor) - 1.8),
        "relative_humidity_2m": 88 if today["precip"] > 0 else 62,
        "precipitation": rain(round(today["precip"] / 12, 2)),
        "weather_code": today["code"],
        "wind_speed_10m": wind(today["wind"] * 0.6),
    }
    daily_values = {
        "weather_code": [d["code"] for d in days],
        "temperature_2m_max": [temp(d["high"]) for d in days],
        "temperature_2m_min": [temp(d["low"]) for d in days],
        "precipitation_sum": [rain(d["precip"]) for d in days],
        "precipitation_probability_max": [d["chance"] for d in days],
        "wind_speed_10m_max": [wind(d["wind"]) for d in days],
    }
    units = {
        "temperature_2m": "°F" if f else "°C", "apparent_temperature": "°F" if f else "°C",
        "relative_humidity_2m": "%", "precipitation": "inch" if inch else "mm", "weather_code": "wmo code",
        "wind_speed_10m": "mp/h" if mph else "km/h", "temperature_2m_max": "°F" if f else "°C",
        "temperature_2m_min": "°F" if f else "°C", "precipitation_sum": "inch" if inch else "mm",
        "precipitation_probability_max": "%", "wind_speed_10m_max": "mp/h" if mph else "km/h",
    }
    wanted_current = [c for c in current.split(",") if c in current_values]
    wanted_daily = [d for d in daily.split(",") if d in daily_values]
    result: dict = {
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "generationtime_ms": 0.3,
        "utc_offset_seconds": offset * 3600,
        "timezone": place["timezone"] if timezone_ == "auto" else timezone_,
        "elevation": 50.0,
    }
    if wanted_current:
        result["current_units"] = {"time": "iso8601", "interval": "seconds", **{k: units[k] for k in wanted_current}}
        result["current"] = {
            "time": now.replace(minute=now.minute // 15 * 15).strftime("%Y-%m-%dT%H:%M"),
            "interval": 900,
            **{k: current_values[k] for k in wanted_current},
        }
    if wanted_daily:
        result["daily_units"] = {"time": "iso8601", **{k: units[k] for k in wanted_daily}}
        result["daily"] = {"time": [d["date"] for d in days], **{k: daily_values[k] for k in wanted_daily}}
    return result


def _day(place: dict, day) -> dict:
    seed = int(hashlib.sha256(f"{place['id']}:{day.isoformat()}".encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    warmest, swing, rain_chance = CLIMATES[place["climate"]]
    # Seasonal cycle peaking in July in the north and January in the south
    peak_month = 7 if place["latitude"] >= 0 else 1
    season = math.cos((day.month - peak_month) / 12 * 2 * math.pi)
    mean = warmest - swing * (1 - season)
    high = mean + 4 + rng.uniform(-3, 3)
    low = high - rng.uniform(5, 10)
    wet = rng.random() < rain_chance
    if wet:
        precip = round(rng.uniform(1.5, 14), 1)
        chance = rng.randint(55, 95)
        if low < 0:
            code = rng.choice((71, 73, 85))
        else:
            code = rng.choice((61, 63, 80, 81)) if precip > 4 else rng.choice((51, 53, 61))
    else:
        precip = round(rng.choice((0, 0, 0, 0.2)), 1)
        chance = rng.randint(0, 30)
        code = rng.choice((0, 1, 2, 2, 3, 3))
    return {
        "date": day.isoformat(), "high": high, "low": low, "precip": precip, "chance": chance, "code": code,
        "wind": rng.uniform(6, 32 if wet else 20),
    }

def cancel_job(data=None):
    if data is None:
        return None
    return data

def cancel_job(data=None):
    if data is None:
        return None
    return data