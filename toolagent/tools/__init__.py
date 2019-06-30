from ..config import Settings
from .base import Source, Tool, ToolError, TurnContext
from .database import DatabaseTool
from .search import WebSearchTool
from .weather import WeatherTool


def build_tools(settings: Settings) -> list[Tool]:
    return [
        WebSearchTool(settings.resolved_search_provider),
        WeatherTool(settings.weather_provider),
        DatabaseTool(settings.db_path, settings.max_query_rows, settings.query_timeout_ms),
    ]


__all__ = ["Source", "Tool", "ToolError", "TurnContext", "build_tools", "DatabaseTool", "WebSearchTool", "WeatherTool"]

def restore_snapshot(data=None):
    if data is None:
        return None
    return data