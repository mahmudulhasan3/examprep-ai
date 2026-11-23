import pytest
from fastapi import HTTPException

from app.core import memory_store, rate_limit
from app.core.rate_limit import check_rate_limit, reset_rate_limits


@pytest.fixture(autouse=True)
def limits_on(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("EMAIL_VERIFICATION", "true")
    monkeypatch.setenv("EMAIL_DEV_MODE", "true")
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture()
def fake_clock(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: clock["now"])
    return clock


@pytest.fixture()
def quiet_email(monkeypatch):
    monkeypatch.setattr("app.routers.auth.send_email", lambda *args: None)


def test_requests_up_to_the_limit_pass_then_429(fake_clock):
    for _ in range(3):
        check_rate_limit("demo", "me", 3, 60)
    with pytest.raises(HTTPException) as caught:
        check_rate_limit("demo", "me", 3, 60)
    assert caught.value.status_code == 429
    assert caught.value.headers is not None
    assert caught.value.headers["Retry-After"] == "60"


def test_the_wait_time_shrinks_as_the_window_passes(fake_clock):
    for _ in range(2):
        check_rate_limit("demo", "me", 2, 60)
    fake_clock["now"] += 45
    with pytest.raises(HTTPException) as caught:
        check_rate_limit("demo", "me", 2, 60)
    assert caught.value.headers is not None
    assert caught.value.headers["Retry-After"] == "15"


def test_the_counter_frees_up_after_the_window(fake_clock):
    for _ in range(2):
        check_rate_limit("demo", "me", 2, 60)
    fake_clock["now"] += 61
    check_rate_limit("demo", "me", 2, 60)  # allowed again


def test_keys_and_buckets_are_counted_separately(fake_clock):
    for _ in range(2):
        check_rate_limit("demo", "alice", 2, 60)
    check_rate_limit("demo", "bob", 2, 60)
    check_rate_limit("other", "alice", 2, 60)
    with pytest.raises(HTTPException):
        check_rate_limit("demo", "alice", 2, 60)


def test_limits_can_be_switched_off(monkeypatch, fake_clock):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    for _ in range(100):
        check_rate_limit("demo", "me", 1, 60)


def test_quiet_keys_are_forgotten(fake_clock):
    check_rate_limit("demo", "old", 5, 60)
    fake_clock["now"] += rate_limit.LONGEST_WINDOW_SECONDS + 1
    rate_limit._purge(fake_clock["now"])
    assert ("demo", "old") not in rate_limit._hits


def test_the_log_does_not_contain_the_email(fake_clock, caplog):
    check_rate_limit("login", "secret@example.com", 1, 60)
    with pytest.raises(HTTPException):
        check_rate_limit("login", "secret@example.com", 1, 60)
    assert "Rate limit hit" in caplog.text
    assert "secret@example.com" not in caplog.text


def test_guests_share_one_budget(client, monkeypatch):
    monkeypatch.setattr("app.routers.chat.GUEST_MESSAGES_PER_MINUTE", 3)
    codes = [
        client.post("/chat/guest", json={"message": f"hi {i}"}).status_code
        for i in range(4)
    ]
    assert codes == [200, 200, 200, 429]
    streamed = client.post("/chat/guest/stream", json={"message": "again"})
    assert streamed.status_code == 429
    assert "Retry-After" in streamed.headers


def test_login_attempts_are_limited_per_email(client):
    for _ in range(10):
        assert (
            client.post(
                "/auth/login", json={"email": "victim@example.com", "password": "x"}
            ).status_code
            == 404
        )
    blocked = client.post(
        "/auth/login", json={"email": "victim@example.com", "password": "x"}
    )
    assert blocked.status_code == 429
    other = client.post(
        "/auth/login", json={"email": "someone-else@example.com", "password": "x"}
    )
    assert other.status_code == 404


def test_one_address_cannot_trigger_endless_emails(client, quiet_email):
    first = client.post("/auth/forgot-password", json={"email": "spam@example.com"})
    assert first.status_code == 200
    for _ in range(4):
        client.post("/auth/forgot-password", json={"email": "spam@example.com"})
    sixth = client.post("/auth/forgot-password", json={"email": "spam@example.com"})
    assert sixth.status_code == 429


def test_all_email_endpoints_share_one_overall_cap(client, quiet_email, monkeypatch):
    monkeypatch.setattr("app.routers.auth.EMAIL_SENDS_PER_HOUR", 3)
    codes = [
        client.post(
            "/auth/forgot-password", json={"email": f"user{i}@example.com"}
        ).status_code
        for i in range(4)
    ]
    assert codes == [200, 200, 200, 429]
    register = client.post(
        "/auth/register", json={"email": "late@example.com", "password": "password123"}
    )
    assert register.status_code == 429


def test_forgot_password_answers_alike_even_when_limited(client, quiet_email):
    client.post(
        "/auth/register", json={"email": "real@example.com", "password": "password123"}
    )  # verification is on, so this only creates a pending sign-up
    for _ in range(5):
        client.post("/auth/forgot-password", json={"email": "ghost@example.com"})
    ghost = client.post("/auth/forgot-password", json={"email": "ghost@example.com"})
    for _ in range(5):
        client.post("/auth/forgot-password", json={"email": "other@example.com"})
    other = client.post("/auth/forgot-password", json={"email": "other@example.com"})
    assert ghost.status_code == other.status_code == 429


def test_code_guessing_is_limited_per_email(client):
    codes = [
        client.post(
            "/auth/verify-email", json={"email": "guess@example.com", "otp": "123456"}
        ).status_code
        for _ in range(16)
    ]
    assert codes[:15] == [400] * 15
    assert codes[15] == 429


def history(count: int):
    items = []
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        items.append({"role": role, "content": f"m{i}"})
    return items


@pytest.fixture()
def clean_store():
    memory_store.guest_sessions.clear()
    yield
    memory_store.guest_sessions.clear()


def test_guest_history_keeps_only_the_newest_messages(clean_store):
    memory_store.save_guest_history("s1", history(30))
    saved = memory_store.guest_sessions["s1"]
    assert len(saved) == memory_store.MAX_GUEST_MESSAGES
    assert saved[0]["role"] == "user"
    assert saved[-1]["content"] == "m29"


def test_guest_history_never_starts_with_an_assistant_message(clean_store):
    memory_store.save_guest_history("s1", history(31)[1:])  # begins with assistant
    assert memory_store.guest_sessions["s1"][0]["role"] == "user"


def test_the_oldest_guest_sessions_are_dropped(clean_store, monkeypatch):
    monkeypatch.setattr(memory_store, "MAX_GUEST_SESSIONS", 3)
    for name in ["a", "b", "c"]:
        memory_store.save_guest_history(name, history(2))
    memory_store.save_guest_history("a", history(4))  # "a" is used again, now newest
    memory_store.save_guest_history("d", history(2))
    assert list(memory_store.guest_sessions) == ["c", "a", "d"]
