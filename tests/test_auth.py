def test_register_success(client):
    response = client.post(
        "/auth/register",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"
    assert "id" in data
    assert "password" not in data
    assert "hashed_password" not in data


def test_register_duplicate_email(client):
    client.post(
        "/auth/register",
        json={"email": "dup@example.com", "password": "testpass123"},
    )
    response = client.post(
        "/auth/register",
        json={"email": "dup@example.com", "password": "anotherpass"},
    )
    assert response.status_code == 409


def test_login_success(client):
    client.post(
        "/auth/register",
        json={"email": "login@example.com", "password": "testpass123"},
    )
    response = client.post(
        "/auth/login",
        json={"email": "login@example.com", "password": "testpass123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client):
    client.post(
        "/auth/register",
        json={"email": "wrongpw@example.com", "password": "testpass123"},
    )
    response = client.post(
        "/auth/login",
        json={"email": "wrongpw@example.com", "password": "incorrectpass"},
    )
    assert response.status_code == 401


def test_login_nonexistent_user(client):
    response = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "testpass123"},
    )
    assert response.status_code == 404
