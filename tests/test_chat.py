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
