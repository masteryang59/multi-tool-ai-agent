import html
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, Field

from .base import Tool, ToolError, TurnContext, request_json

SNIPPET_CHARS = 400


class SearchArgs(BaseModel):
    query: str = Field(
        min_length=2,
        max_length=300,
        description="Search query. Use keywords, not a whole question, and include a year or place if it matters.",
    )
    max_results: int = Field(5, ge=1, le=8, description="How many results to return (1-8).")


@dataclass
class Hit:
    title: str
    url: str
    snippet: str
    published: str | None = None


class WebSearchTool(Tool):
    name = "web_search"
    Args = SearchArgs
    untrusted = True

    def __init__(self, provider: str):
        self.provider = provider

    @property
    def description(self) -> str:
        return (
            "Search the web for current or external information: news, facts, products, people, "
            "documentation. Returns titles, URLs and short snippets, each with a source id. "
            "Cite the ids like [1] in your answer. Don't use it for weather or for the shop's own data."
        )

    async def run(self, args: SearchArgs, ctx: TurnContext) -> dict[str, Any]:
        search = {
            "tavily": _tavily,
            "mock": _tavily,
            "brave": _brave,
            "wikipedia": _wikipedia,
        }[self.provider]
        hits = await search(args, ctx, self.provider)
        results = []
        for hit in hits[: args.max_results]:
            if not hit.url.startswith(("http://", "https://")):
                continue
            result = {
                "id": ctx.add_source(hit.title, hit.url),
                "title": hit.title,
                "url": hit.url,
                "snippet": hit.snippet,
            }
            if hit.published:
                result["published"] = hit.published
            results.append(result)
        if not results:
            raise ToolError(f"No results for {args.query!r}. Try different or fewer keywords.")
        return {"query": args.query, "provider": self.provider, "results": results}


def clean_snippet(text: str | None) -> str:
    """Strip markup from a snippet (Brave and Wikipedia highlight matches with HTML tags)."""
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    if len(text) > SNIPPET_CHARS:
        text = text[:SNIPPET_CHARS].rsplit(" ", 1)[0] + " …"
    return text


async def _tavily(args: SearchArgs, ctx: TurnContext, provider: str) -> list[Hit]:
    settings = ctx.settings
    if provider == "mock":
        base, key = settings.mock_services_url.rstrip("/") + "/tavily", "mock"
    else:
        base, key = settings.tavily_base_url.rstrip("/"), settings.tavily_api_key
        if not key:
            raise ToolError("Web search isn't configured (TAVILY_API_KEY is empty).")
    data = await request_json(
        ctx,
        "POST",
        f"{base}/search",
        service="Tavily search",
        headers={"Authorization": f"Bearer {key}"},
        json={"query": args.query, "max_results": args.max_results, "search_depth": "basic", "include_answer": False},
    )
    return [
        Hit(r.get("title") or r.get("url", ""), r.get("url", ""), clean_snippet(r.get("content")), r.get("published_date"))
        for r in data.get("results", [])
    ]


async def _brave(args: SearchArgs, ctx: TurnContext, provider: str) -> list[Hit]:
    settings = ctx.settings
    if not settings.brave_api_key:
        raise ToolError("Web search isn't configured (BRAVE_API_KEY is empty).")
    data = await request_json(
        ctx,
        "GET",
        f"{settings.brave_base_url.rstrip('/')}/res/v1/web/search",
        service="Brave search",
        headers={"X-Subscription-Token": settings.brave_api_key},
        params={"q": args.query, "count": args.max_results, "text_decorations": "false"},
    )
    return [
        Hit(clean_snippet(r.get("title")), r.get("url", ""), clean_snippet(r.get("description")), r.get("age"))
        for r in (data.get("web") or {}).get("results", [])
    ]


async def _wikipedia(args: SearchArgs, ctx: TurnContext, provider: str) -> list[Hit]:
    base = ctx.settings.wikipedia_base_url.rstrip("/")
    data = await request_json(
        ctx,
        "GET",
        f"{base}/w/api.php",
        service="Wikipedia search",
        params={
            "action": "query",
            "list": "search",
            "srsearch": args.query,
            "srlimit": args.max_results,
            "srprop": "snippet|timestamp",
            "format": "json",
            "formatversion": "2",
        },
    )
    if "error" in data:
        raise ToolError(f"Wikipedia search failed: {data['error'].get('info', 'unknown error')}")
    return [
        Hit(
            r["title"],
            f"{base}/wiki/{quote(r['title'].replace(' ', '_'))}",
            clean_snippet(r.get("snippet")),
            (r.get("timestamp") or "")[:10] or None,
        )
        for r in (data.get("query") or {}).get("search", [])
    ]

def compute_metrics(data=None):
    if data is None:
        return None
    return data

def compute_metrics(data=None):
    if data is None:
        return None
    return data