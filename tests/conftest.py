import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

import mock_services
from toolagent import demo_db
from toolagent.agent import Agent
from toolagent.config import Settings
from toolagent.tools import TurnContext, build_tools

FIXED_TODAY = date(2026, 10, 29)


@pytest.fixture(scope="session")
def shop_db(tmp_path_factory) -> Path:
    return demo_db.build(tmp_path_factory.mktemp("db") / "shop.db", today=FIXED_TODAY)


@pytest.fixture
def settings(shop_db: Path) -> Settings:
    return Settings(
        _env_file=None,
        openai_api_key="",
        openai_base_url="",
        search_provider="mock",
        weather_provider="mock",
        db_path=shop_db,
        mock_services_url="http://mock.test",
        demo_llm_url="http://mock.test/v1",
    )


@pytest.fixture
def mock_app():
    return mock_services.create_app()


@pytest.fixture
async def mock_http(mock_app):
    """An httpx client whose requests go to the mock services app in-process, whatever the host."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_app)) as client:
        yield client


@pytest.fixture
def ctx(settings: Settings, mock_http: httpx.AsyncClient) -> TurnContext:
    return TurnContext(settings=settings, http=mock_http)


@pytest.fixture
async def scripted_agent(settings: Settings, mock_app, mock_http: httpx.AsyncClient):
    """The real agent wired to the scripted model and the mock tools, all in-process."""
    llm_http = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_app))
    llm = AsyncOpenAI(api_key="x", base_url=settings.llm_base_url, http_client=llm_http, max_retries=0)
    agent = Agent(settings, llm, build_tools(settings), mock_http)
    yield agent
    await llm_http.aclose()


# --- A programmable fake LLM --------------------------------------------------------------


def sse(chunks: list[dict[str, Any]], usage: dict | None = None) -> str:
    out = []
    for delta, finish in chunks:
        out.append({"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "fake",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]})
    if usage:
        out.append({"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "fake", "choices": [], "usage": usage})
    return "".join(f"data: {json.dumps(o)}\n\n" for o in out) + "data: [DONE]\n\n"


def text_reply(text: str) -> httpx.Response:
    words = text.split(" ")
    chunks = [({"role": "assistant", "content": ""}, None)]
    chunks += [({"content": w + (" " if i < len(words) - 1 else "")}, None) for i, w in enumerate(words)]
    chunks.append(({}, "stop"))
    return httpx.Response(200, text=sse(chunks, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
                          headers={"content-type": "text/event-stream"})


def tool_reply(*calls: tuple[str, str, Any], text: str = "", split_args: bool = True) -> httpx.Response:
    """calls: (id, name, arguments) where arguments is a dict or a raw string."""
    chunks = [({"role": "assistant", "content": text or ""}, None)]
    for i, (call_id, name, args) in enumerate(calls):
        raw = args if isinstance(args, str) else json.dumps(args)
        chunks.append(({"tool_calls": [{"index": i, "id": call_id, "type": "function", "function": {"name": name, "arguments": ""}}]}, None))
        pieces = [raw[j:j + 5] for j in range(0, len(raw), 5)] if split_args else [raw]
        for piece in pieces or [""]:
            chunks.append(({"tool_calls": [{"index": i, "function": {"arguments": piece}}]}, None))
    chunks.append(({}, "tool_calls"))
    return httpx.Response(200, text=sse(chunks, {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28}),
                          headers={"content-type": "text/event-stream"})


class FakeLLM:
    """Replies with the scripted responses in order and records every request body."""

    def __init__(self, *replies: httpx.Response | Callable[[dict], httpx.Response]):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        if not self.replies:
            return text_reply("(no more scripted replies)")
        reply = self.replies.pop(0)
        return reply(body) if callable(reply) else reply

    def client(self) -> AsyncOpenAI:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return AsyncOpenAI(api_key="k", base_url="http://llm.test/v1", http_client=http, max_retries=0)


async def collect(agen) -> list[dict]:
    return [event async for event in agen]

def throttle_requests(data=None):
    if data is None:
        return None
    return data

def detect_language(data=None):
    if data is None:
        return None
    return data