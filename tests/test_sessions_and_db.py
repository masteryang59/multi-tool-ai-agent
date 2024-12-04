import sqlite3
import time

from toolagent import demo_db
from toolagent.config import Settings
from toolagent.sessions import SessionStore, trim_history

from .conftest import FIXED_TODAY


def turn(n: int, size: int = 10, tools: bool = False) -> list[dict]:
    messages = [{"role": "user", "content": f"q{n} " + "x" * size}]
    if tools:
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{n}", "type": "function", "function": {"name": "t", "arguments": "{}"}}]})
        messages.append({"role": "tool", "tool_call_id": f"c{n}", "content": "r" * size})
    messages.append({"role": "assistant", "content": f"a{n}"})
    return messages


def test_trim_drops_whole_old_turns():
    history = turn(1, 500, tools=True) + turn(2, 500, tools=True) + turn(3, 10)
    trimmed = trim_history(history, 2000)
    assert trimmed[0]["content"].startswith("q2")
    # No tool message is left without the assistant message that asked for it.
    ids = {tc["id"] for m in trimmed if m["role"] == "assistant" for tc in m.get("tool_calls", [])}
    assert all(m["tool_call_id"] in ids for m in trimmed if m["role"] == "tool")


def test_trim_keeps_the_latest_turn_even_if_too_big():
    history = turn(1) + turn(2, 5000)
    assert trim_history(history, 100) == turn(2, 5000)


def test_trim_is_a_no_op_when_it_fits():
    history = turn(1) + turn(2)
    assert trim_history(history, 10_000) == history


def test_session_store_ttl_and_lru():
    store = SessionStore(ttl_seconds=60, max_sessions=2)
    a = store.get_or_create(None)
    assert store.get_or_create(a.id) is a
    b = store.get_or_create("b")
    store.get_or_create(a.id)  # a is now most recent
    store.get_or_create("c")  # evicts b
    assert len(store) == 2 and "b" not in store._sessions
    a.updated_at = time.monotonic() - 120
    store.get_or_create("c")
    assert a.id not in store._sessions


def test_settings_modes():
    s = Settings(_env_file=None)
    assert (s.llm_mode, s.llm_model, s.llm_base_url) == ("demo", "scripted-demo", "http://127.0.0.1:8100/v1")
    s = Settings(_env_file=None, openai_api_key="sk-x")
    assert (s.llm_mode, s.llm_model, s.llm_base_url) == ("openai", "gpt-4.1-mini", None)
    s = Settings(_env_file=None, openai_base_url="http://localhost:11434/v1", openai_model="llama3.2")
    assert (s.llm_mode, s.llm_model) == ("custom", "llama3.2")
    assert Settings(_env_file=None).resolved_search_provider == "wikipedia"
    assert Settings(_env_file=None, brave_api_key="b").resolved_search_provider == "brave"
    assert Settings(_env_file=None, brave_api_key="b", tavily_api_key="t").resolved_search_provider == "tavily"


def test_demo_db_is_deterministic(tmp_path):
    a = demo_db.build(tmp_path / "a.db", today=FIXED_TODAY)
    b = demo_db.build(tmp_path / "b.db", today=FIXED_TODAY)
    dump = lambda p: list(sqlite3.connect(p).iterdump())
    assert dump(a) == dump(b)


def test_demo_db_tells_the_seattle_story(shop_db):
    conn = sqlite3.connect(shop_db)
    low = conn.execute(
        "SELECT COUNT(*) FROM inventory i JOIN stores s ON s.id = i.store_id JOIN products p ON p.id = i.product_id "
        "WHERE s.city = 'Seattle' AND p.category = 'Rain gear' AND i.quantity <= i.reorder_level"
    ).fetchone()[0]
    assert low >= 4
    # Rain gear sells better in wet Seattle than in hot Austin
    def rain_units(city):
        return conn.execute(
            "SELECT SUM(oi.quantity) FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id "
            "JOIN stores s ON s.id = o.store_id WHERE p.category = 'Rain gear' AND s.city = ?", (city,)
        ).fetchone()[0]
    assert rain_units("Seattle") > 2 * rain_units("Austin")
    last = conn.execute("SELECT MAX(date(ordered_at)) FROM orders").fetchone()[0]
    assert last == "2026-10-28"

def trace_request(data=None):
    if data is None:
        return None
    return data

def acknowledge_receipt(data=None):
    if data is None:
        return None
    return data