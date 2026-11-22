import json
from types import SimpleNamespace

import pytest


def get_auth_token(client, email="stream@example.com", password="testpass123"):
    client.post("/auth/register", json={"email": email, "password": password})
    response = client.post("/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def events_of(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def fake_stream(monkeypatch):
    """Replace the Gemini stream with a fake that records the history it receives."""
    calls = []

    def fake(history):
        calls.append(list(history))
        yield "Hello "
        yield "streaming "
        yield "world"

    monkeypatch.setattr("app.routers.chat.stream_chat_response", fake)
    return calls


def failing_before_first_piece(history):
    raise RuntimeError("gemini down")
    yield  # makes this function a generator


def failing_midway(history):
    yield "partial "
    raise RuntimeError("connection dropped")


def empty_stream(history):
    return iter([])


def test_guest_stream_sends_pieces_then_done(client):
    response = client.post("/chat/guest/stream", json={"message": "Hi"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["x-session-id"]
    events = events_of(response)
    assert [e["type"] for e in events] == ["delta", "delta", "delta", "done"]
    assert (
        "".join(e["text"] for e in events if e["type"] == "delta")
        == "Hello streaming world"
    )


def test_guest_stream_remembers_the_conversation(client, fake_stream):
    first = client.post("/chat/guest/stream", json={"message": "first question"})
    session_id = first.headers["x-session-id"]
    client.post(
        "/chat/guest/stream", json={"message": "second", "session_id": session_id}
    )
    history_of_second_call = fake_stream[1]
    assert [m["role"] for m in history_of_second_call] == ["user", "assistant", "user"]
    assert history_of_second_call[1]["content"] == "Hello streaming world"


def test_guest_stream_failure_before_first_piece_is_502(client, monkeypatch):
    monkeypatch.setattr(
        "app.routers.chat.stream_chat_response", failing_before_first_piece
    )
    response = client.post("/chat/guest/stream", json={"message": "Hi"})
    assert response.status_code == 502


def test_guest_stream_empty_reply_is_502(client, monkeypatch):
    monkeypatch.setattr("app.routers.chat.stream_chat_response", empty_stream)
    response = client.post("/chat/guest/stream", json={"message": "Hi"})
    assert response.status_code == 502


def test_guest_stream_midway_failure_sends_error_and_keeps_no_history(
    client, monkeypatch, fake_stream
):
    monkeypatch.setattr("app.routers.chat.stream_chat_response", failing_midway)
    response = client.post("/chat/guest/stream", json={"message": "Hi"})
    events = events_of(response)
    assert [e["type"] for e in events] == ["delta", "error"]
    session_id = response.headers["x-session-id"]

    seen = []
    monkeypatch.setattr(
        "app.routers.chat.stream_chat_response",
        lambda h: (seen.append(list(h)), iter(["ok"]))[1],
    )
    client.post(
        "/chat/guest/stream", json={"message": "again", "session_id": session_id}
    )
    assert [m["content"] for m in seen[0]] == ["again"]


def test_guest_stream_validates_the_message(client):
    assert client.post("/chat/guest/stream", json={"message": ""}).status_code == 422


def test_authenticated_stream_saves_the_conversation(client):
    token = get_auth_token(client)
    response = client.post(
        "/chat/authenticated/stream",
        json={"message": "What is AI?"},
        headers=auth(token),
    )
    assert response.status_code == 200
    assert [e["type"] for e in events_of(response)][-1] == "done"
    session_id = int(response.headers["x-session-id"])

    detail = client.get(f"/chat/sessions/{session_id}", headers=auth(token)).json()
    assert detail["title"] == "What is AI?"
    assert [(m["role"], m["content"]) for m in detail["messages"]] == [
        ("user", "What is AI?"),
        ("assistant", "Hello streaming world"),
    ]


def test_authenticated_stream_continues_an_existing_session(client, fake_stream):
    token = get_auth_token(client)
    first = client.post(
        "/chat/authenticated/stream", json={"message": "one"}, headers=auth(token)
    )
    session_id = int(first.headers["x-session-id"])
    client.post(
        "/chat/authenticated/stream",
        json={"message": "two", "session_id": session_id},
        headers=auth(token),
    )
    assert [m["role"] for m in fake_stream[1]] == ["user", "assistant", "user"]
    detail = client.get(f"/chat/sessions/{session_id}", headers=auth(token)).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"] * 2


def test_authenticated_stream_requires_login(client):
    response = client.post("/chat/authenticated/stream", json={"message": "Hi"})
    assert response.status_code == 401


def test_authenticated_stream_other_users_session_is_404(client):
    token_a = get_auth_token(client, "a-stream@example.com")
    created = client.post(
        "/chat/authenticated/stream", json={"message": "private"}, headers=auth(token_a)
    )
    session_id = int(created.headers["x-session-id"])
    token_b = get_auth_token(client, "b-stream@example.com")
    response = client.post(
        "/chat/authenticated/stream",
        json={"message": "hi", "session_id": session_id},
        headers=auth(token_b),
    )
    assert response.status_code == 404


def test_authenticated_stream_failure_before_first_piece_leaves_nothing(
    client, monkeypatch
):
    monkeypatch.setattr(
        "app.routers.chat.stream_chat_response", failing_before_first_piece
    )
    token = get_auth_token(client)
    response = client.post(
        "/chat/authenticated/stream", json={"message": "Hi"}, headers=auth(token)
    )
    assert response.status_code == 502
    assert client.get("/chat/sessions", headers=auth(token)).json() == []


def test_authenticated_stream_midway_failure_leaves_no_empty_chat(client, monkeypatch):
    monkeypatch.setattr("app.routers.chat.stream_chat_response", failing_midway)
    token = get_auth_token(client)
    response = client.post(
        "/chat/authenticated/stream", json={"message": "Hi"}, headers=auth(token)
    )
    assert [e["type"] for e in events_of(response)] == ["delta", "error"]
    assert client.get("/chat/sessions", headers=auth(token)).json() == []


def test_midway_failure_keeps_an_existing_chat_untouched(client, monkeypatch):
    token = get_auth_token(client)
    first = client.post(
        "/chat/authenticated/stream", json={"message": "keep me"}, headers=auth(token)
    )
    session_id = int(first.headers["x-session-id"])

    monkeypatch.setattr("app.routers.chat.stream_chat_response", failing_midway)
    client.post(
        "/chat/authenticated/stream",
        json={"message": "will fail", "session_id": session_id},
        headers=auth(token),
    )
    detail = client.get(f"/chat/sessions/{session_id}", headers=auth(token)).json()
    assert [m["content"] for m in detail["messages"]] == [
        "keep me",
        "Hello streaming world",
    ]


def test_closing_the_stream_early_removes_the_empty_new_chat(client):
    from app.routers.chat import stream_events

    cleaned = []
    saved = []
    events = stream_events(
        "first ", iter(["second"]), saved.append, lambda: cleaned.append(True)
    )
    next(events)  # the client reads one event, then disconnects
    events.close()
    assert cleaned == [True]
    assert saved == []


def test_stream_chat_response_yields_only_real_text(monkeypatch):
    from app.core import gemini_client

    chunks = [
        SimpleNamespace(text="Hel"),
        SimpleNamespace(text=None),
        SimpleNamespace(text="lo"),
    ]
    captured = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        return iter(chunks)

    monkeypatch.setattr(
        gemini_client,
        "client",
        SimpleNamespace(models=SimpleNamespace(generate_content_stream=fake_stream)),
    )
    result = list(
        gemini_client.stream_chat_response(
            [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
        )
    )
    assert result == ["Hel", "lo"]
    assert [c["role"] for c in captured["contents"]] == ["user", "model"]
