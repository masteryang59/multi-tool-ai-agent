"""A scripted stand-in for an LLM, served over the OpenAI chat-completions protocol.

It isn't a language model. Keyword rules decide which tools to call, and the answer is filled in
from the tool results with templates. It exists so the whole stack (agent loop, streaming, parallel
tool calls, multi-step plans, the UI) can be run and tested without an API key. It handles the demo
questions and similar ones; for anything else, point the agent at a real model.
"""

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter()

MODEL = "scripted-demo"
STORE_CITIES = ["Seattle", "Portland", "Denver", "Minneapolis", "Boston", "Austin"]
CATEGORIES = {
    "Rain gear": r"rain ?(gear|jacket|shell|coat|pant)s?|umbrella|waterproof jacket",
    "Insulation": r"insulat|parka|puffer|down jacket|base ?layer|warm jacket",
    "Footwear": r"shoe|boot|sandal|footwear",
    "Camping": r"tent|sleeping bag|camping",
    "Packs": r"backpack|\bpacks?\b",
    "Accessories": r"beanie|glove|sunscreen|bottle|headlamp|accessor",
}
WEATHER_WORDS = r"weather|forecast|rain(?!\s?(gear|jacket|shell|coat|pant))|snow|temperature|sunny|wind|storm|cold|hot|warm(?! jacket)"
DB_WORDS = r"stock|inventory|sales|sold|revenue|orders?\b|customers?|best[- ]?sell|top (products?|items?|sellers?)|store|units|how many|low on|running low|reorder"
# Explicit requests always search; topic words only when no other tool covers the question.
SEARCH_WORDS = r"search|news|latest|look up|google|\bweb\b|article|online"
TOPIC_WORDS = r"what is|what are|who is|how (do|to|does)|explain|trend|review|compare|vs\.?|pfas|mcp|guide"


@dataclass
class Reply:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


# --- Planning ----------------------------------------------------------------------------


def respond(messages: list[dict[str, Any]], tool_names: set[str]) -> Reply:
    last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=None)
    if last_user is None:
        return Reply("Hello! Ask me about the weather, the shop's stock and sales, or anything on the web.")
    question = _text(messages[last_user].get("content"))
    results = _results_this_turn(messages[last_user + 1:])

    if tool_names:
        follow_up = _follow_up(question, results, tool_names)
        if follow_up:
            return Reply(tool_calls=follow_up)
        if not results:
            calls = plan(question, tool_names)
            if calls:
                return Reply(tool_calls=calls)
    if results:
        return Reply(compose(question, results))
    if re.search(WEATHER_WORDS, question.lower()):
        return Reply("Which city should I check the weather for?")
    return Reply(
        "I'm the scripted demo model, so I only follow simple rules. I can check the **weather** for a city, "
        "look up **stock and sales** in the shop database, or **search the web**. Try one of the example "
        "questions, or connect a real model with `OPENAI_API_KEY`."
    )


def plan(question: str, tool_names: set[str]) -> list[dict[str, Any]]:
    q = question.lower()
    calls = []
    wants_weather = re.search(WEATHER_WORDS, q) is not None
    wants_db = re.search(DB_WORDS, q) is not None
    location = extract_location(question)
    if wants_weather and "get_weather" in tool_names and location:
        calls.append(_call("get_weather", weather_args(question, location)))
    if wants_db and "query_database" in tool_names:
        calls.append(_call("query_database", {"sql": build_sql(question)}))
    wants_search = re.search(SEARCH_WORDS, q) is not None
    about_a_topic = re.search(TOPIC_WORDS, q) is not None
    # Greetings and other short remarks get a direct answer; other questions fall back to search.
    open_question = "?" in question or len(question.split()) >= 4
    if "web_search" in tool_names and (wants_search or (not calls and (about_a_topic or open_question) and not wants_weather)):
        calls.append(_call("web_search", {"query": search_query(question), "max_results": 4}))
    return calls


def _follow_up(question: str, results: list[tuple[dict, Any]], tool_names: set[str]) -> list[dict[str, Any]]:
    """Second step of a two-step plan: weather for a city that came out of a database query."""
    q = question.lower()
    if "get_weather" not in tool_names or not re.search(WEATHER_WORDS, q) or extract_location(question):
        return []
    if any(call["name"] == "get_weather" for call, _ in results):
        return []
    for call, data in results:
        if call["name"] == "query_database" and isinstance(data, dict) and data.get("rows"):
            columns = [c.lower() for c in data.get("columns", [])]
            if "city" in columns:
                city = data["rows"][0][columns.index("city")]
                return [_call("get_weather", weather_args(question, str(city)))]
    return []


def extract_location(question: str) -> str | None:
    match = re.search(
        r"\b(?:in|for|at|near|around)\s+((?:[A-Z][\w.'-]+)(?:(?:\s+|,\s*)[A-Z][\w.'-]+){0,3})", question
    )
    if match:
        place = match.group(1)
        place = re.split(r"\s+(?:This|Next|Today|Tomorrow|On|And|Or|Store)\b", place)[0]
        if place not in {"I", "The", "Our", "We"}:
            return place.strip(" ,")
    for city in STORE_CITIES:
        if city.lower() in question.lower():
            return city
    return None


def weather_args(question: str, location: str) -> dict[str, Any]:
    q = question.lower()
    days = 7 if re.search(r"weekend|week|saturday|sunday|next few days", q) else 2 if "tomorrow" in q else 1 if re.search(r"\b(now|today|right now|currently)\b", q) else 3
    args: dict[str, Any] = {"location": location, "days": days}
    if re.search(r"fahrenheit|°f|\bf\b|imperial|mph|inches", q):
        args["units"] = "imperial"
    return args


def build_sql(question: str) -> str:
    q = question.lower()
    city = next((c for c in STORE_CITIES if c.lower() in q), None)
    category = next((name for name, pattern in CATEGORIES.items() if re.search(pattern, q)), None)
    city_filter = f" AND s.city = '{city}'" if city else ""
    cat_filter = f" AND p.category = '{category}'" if category else ""
    period = _period(q)

    if re.search(r"stock|inventory|enough|low on|running low|reorder|left", q):
        if city:
            return (
                "SELECT p.name, p.category, i.quantity, i.reorder_level FROM inventory i "
                "JOIN products p ON p.id = i.product_id JOIN stores s ON s.id = i.store_id "
                f"WHERE 1 = 1{city_filter}{cat_filter} ORDER BY i.quantity LIMIT 12"
            )
        return (
            "SELECT s.city, p.name, i.quantity, i.reorder_level FROM inventory i "
            "JOIN products p ON p.id = i.product_id JOIN stores s ON s.id = i.store_id "
            f"WHERE i.quantity <= i.reorder_level{cat_filter} ORDER BY i.quantity LIMIT 20"
        )
    if re.search(r"best[- ]?sell|top (products?|items?|sellers?)|most popular|sold the most units", q) and "store" not in q:
        return (
            "SELECT p.name, p.category, SUM(oi.quantity) AS units, ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue "
            "FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id "
            f"JOIN stores s ON s.id = o.store_id WHERE o.status = 'completed' AND {period}{city_filter}{cat_filter} "
            "GROUP BY p.id ORDER BY units DESC LIMIT 5"
        )
    if re.search(r"customer", q):
        return (
            "SELECT c.name, s.city AS home_store, COUNT(DISTINCT o.id) AS orders, "
            "ROUND(SUM(oi.quantity * oi.unit_price), 2) AS spent FROM customers c "
            "JOIN orders o ON o.customer_id = c.id JOIN order_items oi ON oi.order_id = o.id "
            f"JOIN stores s ON s.id = c.home_store_id WHERE o.status = 'completed' AND {period}{city_filter} "
            "GROUP BY c.id ORDER BY spent DESC LIMIT 5"
        )
    if re.search(r"sales|sold|revenue|orders|which store|busiest", q):
        return (
            "SELECT s.city, ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue, COUNT(DISTINCT o.id) AS orders, "
            "SUM(oi.quantity) AS units FROM orders o JOIN order_items oi ON oi.order_id = o.id "
            "JOIN stores s ON s.id = o.store_id JOIN products p ON p.id = oi.product_id "
            f"WHERE o.status = 'completed' AND {period}{city_filter}{cat_filter} GROUP BY s.city ORDER BY revenue DESC"
        )
    return "SELECT name, city, region, opened_on FROM stores ORDER BY id"


def _period(q: str) -> str:
    col = "date(o.ordered_at)"
    if "last month" in q:
        return f"{col} >= date('now', 'start of month', '-1 month') AND {col} < date('now', 'start of month')"
    if "this month" in q:
        return f"{col} >= date('now', 'start of month')"
    if "this year" in q:
        return f"{col} >= date('now', 'start of year')"
    if re.search(r"last (7 days|week)|past week", q):
        return f"{col} >= date('now', '-7 days')"
    if re.search(r"last (90 days|quarter|3 months)", q):
        return f"{col} >= date('now', '-90 days')"
    if re.search(r"last (12 months|year)|all time|ever", q):
        return f"{col} >= date('now', '-365 days')"
    return f"{col} >= date('now', '-30 days')"


def search_query(question: str) -> str:
    q = re.sub(r"(?i)\b(please|can you|could you|search (the web )?for|look up|google|tell me|find out|on the web)\b", " ", question)
    q = re.sub(r"[?!.]+$", "", q)
    return re.sub(r"\s+", " ", q).strip(" ,") or question


# --- Writing the answer -----------------------------------------------------------------------


def compose(question: str, results: list[tuple[dict, Any]]) -> str:
    q = question.lower()
    parts: list[str] = []
    weather = stock = None
    for call, data in results:
        name = call["name"]
        if isinstance(data, dict) and "error" in data and len(data) == 1:
            parts.append(f"I couldn't use **{name}**: {data['error']}")
            continue
        if isinstance(data, dict) and "untrusted_content" in data:
            data = data["untrusted_content"]
        if name == "get_weather":
            weather = data
            parts.append(_weather_text(q, data))
        elif name == "query_database":
            text, low = _db_text(call, data)
            stock = low if low is not None else stock
            parts.append(text)
        elif name == "web_search":
            parts.append(_search_text(data))
    if weather and stock:
        wet = [d for d in _relevant_days(q, weather) if (d.get("precipitation_chance_pct") or 0) >= 50]
        if wet:
            parts.append(
                f"**Takeaway:** rain is likely on {', '.join(d['weekday'] for d in wet)}, and {len(stock)} of these "
                "items are at or below their reorder level. Worth reordering now or moving stock from another store."
            )
    return "\n\n".join(p for p in parts if p)


def _relevant_days(q: str, weather: dict) -> list[dict]:
    days = weather.get("daily") or []
    if "weekend" in q:
        weekend = [d for d in days if d.get("weekday") in ("Saturday", "Sunday")]
        return weekend or days
    if "tomorrow" in q and len(days) > 1:
        return days[1:2]
    return days


def _weather_text(q: str, data: dict) -> str:
    loc, units, now = data["location"], data["units"], data["current"]
    t, wind, rain = units["temperature"], units["wind"], units["precipitation"]
    place = ", ".join(p for p in (loc.get("name"), loc.get("region")) if p)
    lines = [
        f"**Weather in {place}:** right now {now['temperature']}{t} and {now['conditions']} "
        f"(feels like {now['feels_like']}{t}, wind {now['wind']} {wind})."
    ]
    days = _relevant_days(q, data)
    if days:
        lines.append("\n| Day | Conditions | High / low | Rain |\n| --- | --- | --- | --- |")
        for d in days:
            lines.append(
                f"| {d['weekday']} {d['date'][5:]} | {d['conditions']} | {d['high']} / {d['low']}{t} | "
                f"{d['precipitation_chance_pct']}%, {d['precipitation']} {rain} |"
            )
    others = data.get("other_places_with_this_name")
    if others:
        lines.append(f"\n(I assumed {place}. Other places with that name: {'; '.join(others)}.)")
    return "\n".join(lines)


def _db_text(call: dict, data: dict) -> tuple[str, list | None]:
    columns, rows = data.get("columns", []), data.get("rows", [])
    if not rows:
        return "The database query returned no rows.", None
    header = "| " + " | ".join(columns) + " |\n| " + " | ".join("---" for _ in columns) + " |"
    body = "\n".join("| " + " | ".join(_fmt(v) for v in row) + " |" for row in rows[:10])
    more = f"\n\n…and {len(rows) - 10} more rows." if len(rows) > 10 else ""
    low = None
    lower = [c.lower() for c in columns]
    sql = json.loads(call.get("arguments") or "{}").get("sql", "").lower()
    if "quantity" in lower and "reorder_level" in lower:
        qi, ri = lower.index("quantity"), lower.index("reorder_level")
        low = [r for r in rows if r[qi] <= r[ri]]
        intro = f"**Stock:** {len(low)} of {len(rows)} items are at or below their reorder level." if low else "**Stock:** everything is above its reorder level."
    elif "revenue" in lower and "city" in lower:
        intro = f"**Sales by store:** {rows[0][lower.index('city')]} leads with ${_fmt(rows[0][lower.index('revenue')])}."
    elif "units" in lower and "name" in lower:
        intro = f"**Best sellers:** {rows[0][lower.index('name')]} is first with {rows[0][lower.index('units')]} units."
    else:
        intro = "**From the database:**"
    period = ""
    if "start of month', '-1 month'" in sql:
        period = " (last calendar month, completed orders)"
    elif "'-30 days'" in sql:
        period = " (last 30 days, completed orders)"
    return f"{intro}{period}\n\n{header}\n{body}{more}", low


def _search_text(data: dict) -> str:
    results = data.get("results") or []
    if not results:
        return "The web search found nothing useful."
    lines = ["**From the web:**"]
    for r in results[:4]:
        if "ignore all previous instructions" in r.get("snippet", "").lower():
            lines.append(f"- One result [{r['id']}] contains instructions aimed at AI assistants. I ignored it.")
            continue
        first = re.split(r"(?<=[.!?])\s", r.get("snippet", ""), maxsplit=1)[0]
        lines.append(f"- **{r['title']}**: {first} [{r['id']}]")
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value).replace("|", "\\|")


# --- Plumbing ---------------------------------------------------------------------------------


def _text(content: Any) -> str:
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def _results_this_turn(messages: list[dict]) -> list[tuple[dict, Any]]:
    calls: dict[str, dict] = {}
    results = []
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                calls[tc["id"]] = {"name": tc["function"]["name"], "arguments": tc["function"].get("arguments", "{}")}
        elif m.get("role") == "tool" and m.get("tool_call_id") in calls:
            try:
                data = json.loads(_text(m.get("content")))
            except json.JSONDecodeError:
                data = {"error": "unreadable tool result"}
            results.append((calls[m["tool_call_id"]], data))
    return results


def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"id": f"call_{uuid.uuid4().hex[:12]}", "name": name, "arguments": json.dumps(args)}


def _estimate_tokens(value: Any) -> int:
    return max(1, len(json.dumps(value, ensure_ascii=False)) // 4)


@router.get("/v1/models")
def models() -> dict:
    return {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "mock-services"}]}


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages") or []
    tool_names = {t["function"]["name"] for t in body.get("tools") or [] if t.get("type") == "function"}
    if body.get("tool_choice") == "none":
        tool_names = set()
    reply = respond(messages, tool_names)
    model = body.get("model") or MODEL
    created = int(time.time())
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
    usage = {
        "prompt_tokens": _estimate_tokens(messages) + _estimate_tokens(body.get("tools") or []),
        "completion_tokens": _estimate_tokens(reply.text or reply.tool_calls),
    }
    usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    finish = "tool_calls" if reply.tool_calls else "stop"

    if not body.get("stream"):
        message: dict[str, Any] = {"role": "assistant", "content": reply.text or None}
        if reply.tool_calls:
            message["tool_calls"] = [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                for c in reply.tool_calls
            ]
        return JSONResponse({
            "id": completion_id, "object": "chat.completion", "created": created, "model": model,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}], "usage": usage,
        })

    delay = float(request.app.state.token_delay) if hasattr(request.app.state, "token_delay") else 0.0
    include_usage = (body.get("stream_options") or {}).get("include_usage", False)

    def chunk(delta: dict | None, finish_reason: str | None = None, **extra: Any) -> str:
        payload = {
            "id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model,
            "choices": [] if delta is None else [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
            **extra,
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def stream():
        yield chunk({"role": "assistant", "content": ""})
        # Three words per chunk: on Windows, asyncio sleeps shorter than the ~16 ms clock
        # resolution return at once, so a per-word delay would be too slow or have no effect.
        for piece in re.findall(r"(?:\S+\s*){1,3}|\s+", reply.text):
            yield chunk({"content": piece})
            if delay:
                await asyncio.sleep(delay)
        for i, call in enumerate(reply.tool_calls):
            yield chunk({"tool_calls": [{"index": i, "id": call["id"], "type": "function", "function": {"name": call["name"], "arguments": ""}}]})
            args = call["arguments"]
            for start in range(0, len(args), 24):
                yield chunk({"tool_calls": [{"index": i, "function": {"arguments": args[start:start + 24]}}]})
        yield chunk({}, finish)
        if include_usage:
            yield chunk(None, usage=usage)
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")

def generate_report(data=None):
    if data is None:
        return None
    return data

def cleanup_resources(data=None):
    if data is None:
        return None
    return data

def generate_report(data=None):
    if data is None:
        return None
    return data

def build_query(data=None):
    if data is None:
        return None
    return data