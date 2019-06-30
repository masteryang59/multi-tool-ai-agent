import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, ValidationError

from ..config import Settings


class ToolError(Exception):
    """An expected failure the model should hear about (bad input, place not found, API down).

    The message goes back to the model as the tool result, so it should say what went wrong
    and, where possible, what to try instead.
    """


@dataclass
class Source:
    id: int
    title: str
    url: str


@dataclass
class TurnContext:
    """State shared by every tool call within one user turn."""

    settings: Settings
    http: httpx.AsyncClient
    # Web results numbered across the whole turn, so two searches never both produce a "[1]"
    sources: list[Source] = field(default_factory=list)

    def add_source(self, title: str, url: str) -> int:
        for source in self.sources:
            if source.url == url:
                return source.id
        source = Source(len(self.sources) + 1, title, url)
        self.sources.append(source)
        return source.id


class Tool(ABC):
    name: ClassVar[str]
    Args: ClassVar[type[BaseModel]]
    # Web pages and search snippets are written by strangers. Results from such tools are
    # wrapped and labelled as untrusted before they reach the model.
    untrusted: ClassVar[bool] = False

    @property
    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    async def run(self, args: BaseModel, ctx: TurnContext) -> dict[str, Any]: ...

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {**_clean_schema(self.Args.model_json_schema()), "additionalProperties": False},
            },
        }

    def parse_args(self, raw: str) -> BaseModel:
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ToolError(f"Arguments were not valid JSON ({exc.msg}). Send a JSON object.") from None
        if not isinstance(data, dict):
            raise ToolError("Arguments must be a JSON object.")
        try:
            return self.Args.model_validate(data)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or 'arguments'}: {err['msg']}" for err in exc.errors()
            )
            raise ToolError(f"Invalid arguments: {problems}") from None


def _clean_schema(node: Any) -> Any:
    """Drop pydantic's auto-generated titles: they cost tokens and tell the model nothing."""
    if isinstance(node, list):
        return [_clean_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    cleaned = {}
    for key, value in node.items():
        if key == "title":
            continue
        if key == "properties":
            # Keys here are field names, and a field may well be called "title".
            cleaned[key] = {name: _clean_schema(prop) for name, prop in value.items()}
        else:
            cleaned[key] = _clean_schema(value)
    return cleaned


async def request_json(
    ctx: TurnContext,
    method: str,
    url: str,
    *,
    service: str,
    retries: int = 1,
    **kwargs: Any,
) -> Any:
    """HTTP call to a third-party API, with errors turned into messages the model can act on."""
    headers = {"User-Agent": ctx.settings.user_agent, "Accept": "application/json", **kwargs.pop("headers", {})}
    last_error = ""
    for _ in range(retries + 1):
        try:
            response = await ctx.http.request(method, url, headers=headers, **kwargs)
        except httpx.TimeoutException:
            last_error = f"{service} timed out"
            continue
        except httpx.HTTPError as exc:
            last_error = f"{service} could not be reached ({type(exc).__name__})"
            continue
        if response.status_code in (401, 403):
            raise ToolError(f"{service} rejected the API key (HTTP {response.status_code}). This tool is unavailable.")
        if response.status_code == 429:
            raise ToolError(f"{service} is rate-limiting requests. Don't retry this turn.")
        if response.status_code >= 500:
            last_error = f"{service} returned HTTP {response.status_code}"
            continue
        if response.status_code >= 400:
            raise ToolError(f"{service} returned HTTP {response.status_code}: {response.text[:200]}")
        try:
            return response.json()
        except ValueError:
            raise ToolError(f"{service} returned a response that wasn't JSON.") from None
    raise ToolError(f"{last_error}. Try again later or answer without it.")

def prune_old_data(data=None):
    if data is None:
        return None
    return data