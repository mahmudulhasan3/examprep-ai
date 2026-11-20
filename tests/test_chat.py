def get_auth_token(client, email="chatuser@example.com", password="testpass123"):
    client.post("/auth/register", json={"email": email, "password": password})
    response = client.post("/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


def test_guest_chat_new_session(client):
    response = client.post("/chat/guest", json={"message": "Hello"})
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "reply" in data


def test_guest_chat_followup(client):
    first = client.post("/chat/guest", json={"message": "Hello"})
    session_id = first.json()["session_id"]

    second = client.post(
        "/chat/guest",
        json={"message": "Follow up question", "session_id": session_id},
    )
    assert second.status_code == 200
    assert second.json()["session_id"] == session_id


def test_authenticated_chat_no_token(client):
    response = client.post("/chat/authenticated", json={"message": "Hello"})
    assert response.status_code == 401


def test_authenticated_chat_success(client):
    token = get_auth_token(client)
    response = client.post(
        "/chat/authenticated",
        json={"message": "Hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "reply" in data


def test_authenticated_chat_wrong_user_session(client):
    token_a = get_auth_token(client, "usera@example.com")
    first = client.post(
        "/chat/authenticated",
        json={"message": "Hello"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    session_id = first.json()["session_id"]

    token_b = get_auth_token(client, "userb@example.com")
    response = client.post(
        "/chat/authenticated",
        json={"message": "Hello", "session_id": session_id},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 404


def test_gemini_failure_returns_502(client, monkeypatch):
    def boom(history):
        raise RuntimeError("gemini down")

    monkeypatch.setattr("app.routers.chat.generate_chat_response", boom)
    token = get_auth_token(client, "fail@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/chat/authenticated", json={"message": "Hi"}, headers=headers
    )
    assert response.status_code == 502


def test_history_keeps_order(client):
    token = get_auth_token(client, "order@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post("/chat/authenticated", json={"message": "one"}, headers=headers)
    sid = first.json()["session_id"]
    client.post(
        "/chat/authenticated",
        json={"message": "two", "session_id": sid},
        headers=headers,
    )

    from tests.conftest import TestingSessionLocal
    from app.db.models import ChatSession

    with TestingSessionLocal() as db:
        session = db.get(ChatSession, sid)
        assert session is not None
        roles = [m.role for m in session.messages]

    assert roles == ["user", "assistant", "user", "assistant"]


def test_failed_first_message_leaves_no_empty_session(client, monkeypatch):
    def boom(history):
        raise RuntimeError("gemini down")

    monkeypatch.setattr("app.routers.chat.generate_chat_response", boom)
    token = get_auth_token(client, "orphan@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/chat/authenticated", json={"message": "Hi"}, headers=headers)

    sessions = client.get("/chat/sessions", headers=headers)
    assert sessions.status_code == 200
    assert sessions.json() == []


def test_list_sessions_newest_first_with_title(client):
    token = get_auth_token(client, "list@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/chat/authenticated", json={"message": "first chat"}, headers=headers)
    client.post("/chat/authenticated", json={"message": "second chat"}, headers=headers)

    response = client.get("/chat/sessions", headers=headers)
    assert response.status_code == 200
    titles = [s["title"] for s in response.json()]
    assert titles == ["second chat", "first chat"]


def test_get_session_returns_messages_in_order(client):
    token = get_auth_token(client, "detail@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post(
        "/chat/authenticated", json={"message": "hello"}, headers=headers
    )
    sid = first.json()["session_id"]

    response = client.get(f"/chat/sessions/{sid}", headers=headers)
    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "hello"


def test_get_session_of_another_user_is_404(client):
    token_a = get_auth_token(client, "own@example.com")
    first = client.post(
        "/chat/authenticated",
        json={"message": "secret"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    sid = first.json()["session_id"]

    token_b = get_auth_token(client, "intruder@example.com")
    response = client.get(
        f"/chat/sessions/{sid}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert response.status_code == 404


def test_empty_message_rejected(client):
    response = client.post("/chat/guest", json={"message": ""})
    assert response.status_code == 422
