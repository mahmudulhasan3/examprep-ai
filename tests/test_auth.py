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


def test_token_expiry_is_about_30_minutes():
    import time, jwt
    from app.core.security import create_token_access, SECRET_KEY, ALGORITHM

    token = create_token_access({"user_id": 1})
    exp = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])["exp"]
    minutes = (exp - time.time()) / 60
    assert 29 <= minutes <= 31
