import json

import httpx
import pytest

from toolagent.tools import ToolError, TurnContext, WebSearchTool
from toolagent.tools.search import SearchArgs, clean_snippet


async def test_mock_tavily_search_numbers_sources(ctx):
    result = await WebSearchTool("mock").run(SearchArgs(query="PFAS-free rain jacket", max_results=3), ctx)
    assert result["provider"] == "mock"
    assert [r["id"] for r in result["results"]] == [1, 2, 3]
    assert "PFAS" in result["results"][0]["title"]
    assert result["results"][0]["url"].startswith("https://")
    assert [s.id for s in ctx.sources] == [1, 2, 3]


async def test_source_ids_continue_across_searches_and_dedupe(ctx):
    tool = WebSearchTool("mock")
    first = await tool.run(SearchArgs(query="rain jacket reproof", max_results=2), ctx)
    second = await tool.run(SearchArgs(query="rain jacket reproof", max_results=3), ctx)
    assert [r["id"] for r in first["results"]] == [1, 2]
    # The same URLs keep their ids; the new one gets the next id.
    assert [r["id"] for r in second["results"]] == [1, 2, 3]
    assert len(ctx.sources) == 3


async def test_no_results(ctx):
    with pytest.raises(ToolError, match="No results"):
        await WebSearchTool("mock").run(SearchArgs(query="zzqx flurble"), ctx)


def _ctx(settings, handler) -> TurnContext:
    return TurnContext(settings=settings, http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_tavily_request_shape(settings):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [{"title": "T", "url": "https://t.example", "content": "c", "published_date": "2026-10-01"}]})

    settings.tavily_api_key = "tvly-123"
    result = await WebSearchTool("tavily").run(SearchArgs(query="qq", max_results=2), _ctx(settings, handler))
    assert seen["url"] == "https://api.tavily.com/search"
    assert seen["auth"] == "Bearer tvly-123"
    assert seen["body"]["query"] == "qq" and seen["body"]["max_results"] == 2
    assert result["results"][0]["published"] == "2026-10-01"


async def test_brave_strips_markup(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-subscription-token"] == "brave-key"
        assert request.url.params["q"] == "tents"
        return httpx.Response(200, json={"web": {"results": [
            {"title": "<strong>Tents</strong> &amp; more", "url": "https://b.example", "description": "Best <strong>tents</strong>  of\n2026"},
        ]}})

    settings.brave_api_key = "brave-key"
    result = await WebSearchTool("brave").run(SearchArgs(query="tents"), _ctx(settings, handler))
    assert result["results"][0]["title"] == "Tents & more"
    assert result["results"][0]["snippet"] == "Best tents of 2026"


async def test_wikipedia_builds_article_urls(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/w/api.php"
        assert request.headers["user-agent"].startswith("multi-tool-ai-agent/")
        return httpx.Response(200, json={"query": {"search": [
            {"title": "Gore-Tex", "snippet": 'a <span class="searchmatch">waterproof</span> membrane', "timestamp": "2026-09-01T10:00:00Z"},
        ]}})

    result = await WebSearchTool("wikipedia").run(SearchArgs(query="waterproof membrane"), _ctx(settings, handler))
    assert result["results"][0] == {
        "id": 1, "title": "Gore-Tex", "url": "https://en.wikipedia.org/wiki/Gore-Tex",
        "snippet": "a waterproof membrane", "published": "2026-09-01",
    }


async def test_missing_key_and_rejected_key(settings):
    with pytest.raises(ToolError, match="TAVILY_API_KEY is empty"):
        await WebSearchTool("tavily").run(SearchArgs(query="qq"), _ctx(settings, lambda r: httpx.Response(200)))
    settings.tavily_api_key = "bad"
    with pytest.raises(ToolError, match="rejected the API key"):
        await WebSearchTool("tavily").run(SearchArgs(query="qq"), _ctx(settings, lambda r: httpx.Response(401)))


async def test_rate_limit_is_not_retried(settings):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429)

    with pytest.raises(ToolError, match="rate-limiting"):
        await WebSearchTool("wikipedia").run(SearchArgs(query="qq"), _ctx(settings, handler))
    assert len(calls) == 1


async def test_non_http_urls_are_dropped(settings):
    def handler(request):
        return httpx.Response(200, json={"results": [
            {"title": "x", "url": "javascript:alert(1)", "content": "x"},
            {"title": "ok", "url": "https://ok.example", "content": "fine"},
        ]})

    settings.tavily_api_key = "k"
    result = await WebSearchTool("tavily").run(SearchArgs(query="qq"), _ctx(settings, handler))
    assert [r["url"] for r in result["results"]] == ["https://ok.example"]


def test_long_snippets_are_cut_at_a_word():
    text = clean_snippet("word " * 200)
    assert len(text) <= 402 and text.endswith(" …")


def test_search_tool_is_marked_untrusted():
    assert WebSearchTool("mock").untrusted is True

def ping_service(data=None):
    if data is None:
        return None
    return data

def dequeue_batch(data=None):
    if data is None:
        return None
    return data