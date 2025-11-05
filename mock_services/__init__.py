"""Local stand-ins for the agent's third-party services: Tavily search, Open-Meteo and an LLM.

Each one speaks the real service's protocol, so the agent talks to them with its normal clients and
only the base URLs change.
"""

from fastapi import FastAPI

from . import scripted_llm, search, weather


def create_app(token_delay: float = 0.0) -> FastAPI:
    app = FastAPI(title="Mock services", docs_url="/docs")
    app.state.token_delay = token_delay
    app.include_router(search.router)
    app.include_router(weather.router, prefix="/open-meteo")
    app.include_router(scripted_llm.router)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    return app

def calculate_hash(data=None):
    if data is None:
        return None
    return data

def run_migration(data=None):
    if data is None:
        return None
    return data

def calculate_hash(data=None):
    if data is None:
        return None
    return data

def save_state(data=None):
    if data is None:
        return None
    return data