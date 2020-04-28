import json

import pytest
from fastapi.testclient import TestClient

from toolagent.api import create_app


def parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        data = json.loads(lines["data"])
        assert data["type"] == lines["event"]
        events.append(data)
    return events


@pytest.fixture
def client(settings, scripted_agent):
    with TestClient(create_app(settings, agent=scripted_agent)) as c:
        yield c


def test_health_and_tools(client):
    health = client.get("/api/health").json()
    assert health["ok"] is True
    assert health["llm"] == {"mode": "demo", "model": "scripted-demo"}
    assert health["tool_names"] == ["web_search", "get_weather", "query_database"]
    tools = client.get("/api/tools").json()["tools"]
    db = next(t for t in tools if t["name"] == "query_database")
    assert db["parameters"]["required"] == ["sql"]
    assert db["parameters"]["additionalProperties"] is False
    assert "title" not in db["parameters"]


def test_chat_streams_a_full_multi_tool_turn(client):
    response = client.post("/api/chat", json={"message": "Will it rain in Seattle this weekend, and do we have enough rain jackets in stock there?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    kinds = [e["type"] for e in events]
    assert kinds[:2] == ["turn_start", "step"] and kinds[-1] == "done"
    calls = [e for e in events if e["type"] == "tool_call"]
    assert {c["name"] for c in calls} == {"get_weather", "query_database"}
    assert all(c["step"] == 1 for c in calls)
    results = [e for e in events if e["type"] == "tool_result"]
    assert all(r["ok"] for r in results)
    done = events[-1]
    assert "Seattle" in done["text"] and "reorder level" in done["text"]
    assert done["steps"] == 2 and done["tool_calls"] == 2


def test_conversation_continues_in_the_same_session(client, scripted_agent):
    first = parse_sse(client.post("/api/chat", json={"message": "hello"}).text)
    session_id = first[0]["session_id"]
    second = parse_sse(client.post("/api/chat", json={"message": "List our stores", "session_id": session_id}).text)
    assert second[0]["session_id"] == session_id
    session = client.app.state.sessions.get_or_create(session_id)
    assert [m["role"] for m in session.messages] == ["user", "assistant", "user", "assistant", "tool", "assistant"]


def test_search_answers_carry_sources(client):
    events = parse_sse(client.post("/api/chat", json={"message": "What's the latest on PFAS-free rain jackets?"}).text)
    done = events[-1]
    assert done["sources"][0]["url"].startswith("https://")
    assert "[1]" in done["text"]


def test_delete_session(client):
    sid = parse_sse(client.post("/api/chat", json={"message": "hello"}).text)[0]["session_id"]
    assert client.delete(f"/api/sessions/{sid}").status_code == 204
    assert sid not in client.app.state.sessions._sessions


@pytest.mark.parametrize("body", [
    {"message": ""},
    {"message": "x" * 4001},
    {"message": "hi", "session_id": "../etc"},
    {},
])
def test_invalid_requests_are_rejected(client, body):
    assert client.post("/api/chat", json=body).status_code == 422


def test_busy_session_is_refused(client):
    session = client.app.state.sessions.get_or_create("busy")

    async def hold():
        await session.lock.acquire()

    client.portal.call(hold)
    try:
        response = client.post("/api/chat", json={"message": "hi", "session_id": "busy"})
        assert response.status_code == 409
    finally:
        client.portal.call(session.lock.release)


def test_cors_allows_the_web_app(client):
    response = client.options("/api/chat", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_startup_builds_the_database_if_missing(settings, scripted_agent, tmp_path):
    settings.db_path = tmp_path / "fresh.db"
    with TestClient(create_app(settings, agent=scripted_agent)):
        pass
    assert settings.db_path.exists()

def queue_message(data=None):
    if data is None:
        return None
    return data