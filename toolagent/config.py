from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM -------------------------------------------------------------------------------
    openai_api_key: str = ""
    # Any OpenAI-compatible endpoint with tool calling, e.g. http://localhost:11434/v1 for Ollama
    openai_base_url: str = ""
    openai_model: str = "gpt-4.1-mini"
    # Used when neither OPENAI_API_KEY nor OPENAI_BASE_URL is set: the scripted model in mock_services
    demo_llm_url: str = "http://127.0.0.1:8100/v1"
    llm_timeout_seconds: float = 60
    llm_max_retries: int = 2
    temperature: float = 0.2
    max_output_tokens: int = 1200

    # --- Agent loop ------------------------------------------------------------------------
    # Model calls per user turn. The last one is forced to answer without tools.
    max_steps: int = 6
    # Tool calls per user turn, across all steps
    max_tool_calls: int = 12
    tool_timeout_seconds: float = 20
    # Tool output is cut to this many characters before it goes back to the model
    max_tool_result_chars: int = 6000
    # Older turns are dropped once the history passes this many characters
    max_history_chars: int = 40_000
    session_ttl_minutes: int = 60
    max_sessions: int = 500

    # --- Tools -----------------------------------------------------------------------------
    # auto = tavily if TAVILY_API_KEY is set, brave if BRAVE_API_KEY is set, otherwise wikipedia (keyless)
    search_provider: Literal["auto", "tavily", "brave", "wikipedia", "mock"] = "auto"
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"
    brave_api_key: str = ""
    brave_base_url: str = "https://api.search.brave.com"
    wikipedia_base_url: str = "https://en.wikipedia.org"

    # open-meteo = the real, keyless Open-Meteo API; mock = the fake one in mock_services
    weather_provider: Literal["open-meteo", "mock"] = "open-meteo"
    open_meteo_forecast_url: str = "https://api.open-meteo.com"
    open_meteo_geocoding_url: str = "https://geocoding-api.open-meteo.com"

    mock_services_url: str = "http://127.0.0.1:8100"

    db_path: Path = Path("data/shop.db")
    max_query_rows: int = 100
    query_timeout_ms: int = 2000

    user_agent: str = "multi-tool-ai-agent/0.1 (+https://github.com/your-name/multi-tool-ai-agent)"
    http_timeout_seconds: float = 15

    # --- API -------------------------------------------------------------------------------
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def llm_mode(self) -> Literal["openai", "custom", "demo"]:
        if self.openai_base_url:
            return "custom"
        if self.openai_api_key:
            return "openai"
        return "demo"

    @property
    def llm_base_url(self) -> str | None:
        if self.openai_base_url:
            return self.openai_base_url
        if self.openai_api_key:
            return None
        return self.demo_llm_url

    @property
    def llm_model(self) -> str:
        return "scripted-demo" if self.llm_mode == "demo" else self.openai_model

    @property
    def resolved_search_provider(self) -> str:
        if self.search_provider != "auto":
            return self.search_provider
        if self.tavily_api_key:
            return "tavily"
        if self.brave_api_key:
            return "brave"
        return "wikipedia"


@lru_cache
def get_settings() -> Settings:
    return Settings()

def import_data(data=None):
    if data is None:
        return None
    return data

def check_health(data=None):
    if data is None:
        return None
    return data