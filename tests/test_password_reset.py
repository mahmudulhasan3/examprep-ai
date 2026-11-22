import re
from datetime import timedelta

import pytest

from app.core.verification import utcnow

OLD = "old-password-1"
NEW = "brand-new-pass-2"


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("EMAIL_VERIFICATION", "false")
    monkeypatch.setenv("EMAIL_DEV_MODE", "true")
    monkeypatch.setenv("APP_BASE_URL", "https://app.example.com/")


@pytest.fixture()
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.routers.auth.send_email",
        lambda to, subject, html, text: sent.append(
            {"to": to, "subject": subject, "html": html, "text": text}
        ),
    )
    return sent


@pytest.fixture()
def user(client):
    client.post(
        "/auth/register", json={"email": "forgetful@example.com", "password": OLD}
    )
    return "forgetful@example.com"


def forgot(client, email):
    return client.post("/auth/forgot-password", json={"email": email})


def token_from(message) -> str:
    match = re.search(r"reset_token=([A-Za-z0-9_-]+)", message["text"])
    assert match, "no reset link in the email"
    return match.group(1)


def reset(client, token, password=NEW):
    return client.post(
        "/auth/reset-password", json={"token": token, "new_password": password}
    )


def login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def age_tokens(minutes):
    from tests.conftest import TestingSessionLocal
    from app.db.models import PasswordResetToken

    with TestingSessionLocal() as db:
        for record in db.query(PasswordResetToken):
            record.created_at = utcnow() - timedelta(minutes=minutes)
            record.expires_at = record.expires_at - timedelta(minutes=minutes)
        db.commit()


def test_forgot_password_emails_a_reset_link(client, outbox, user):
    response = forgot(client, user)
    assert response.status_code == 200
    assert "If this email is registered" in response.json()["message"]
    assert len(outbox) == 1
    assert outbox[0]["to"] == user
    assert "https://app.example.com/?reset_token=" in outbox[0]["text"]
    assert "https://app.example.com/?reset_token=" in outbox[0]["html"]


def test_unknown_email_gets_the_same_answer_and_no_mail(client, outbox, user):
    known = forgot(client, user)
    unknown = forgot(client, "nobody@example.com")
    assert unknown.status_code == known.status_code == 200
    assert unknown.json() == known.json()
    assert len(outbox) == 1


def test_asking_again_too_soon_sends_nothing_new(client, outbox, user):
    forgot(client, user)
    forgot(client, user)
    assert len(outbox) == 1


def test_forgot_password_needs_email_to_be_configured(client, monkeypatch, user):
    monkeypatch.delenv("EMAIL_DEV_MODE")
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    monkeypatch.delenv("BREVO_SENDER_EMAIL", raising=False)
    assert forgot(client, user).status_code == 503


def test_the_token_is_stored_hashed(client, outbox, user):
    forgot(client, user)
    token = token_from(outbox[0])

    from tests.conftest import TestingSessionLocal
    from app.db.models import PasswordResetToken

    with TestingSessionLocal() as db:
        record = db.query(PasswordResetToken).one()
        assert record.token_hash != token
        assert len(record.token_hash) == 64


def test_the_link_sets_a_new_password(client, outbox, user):
    forgot(client, user)
    response = reset(client, token_from(outbox[0]))
    assert response.status_code == 200
    assert login(client, user, NEW).status_code == 200
    assert login(client, user, OLD).status_code == 401


def test_a_link_works_only_once(client, outbox, user):
    forgot(client, user)
    token = token_from(outbox[0])
    assert reset(client, token).status_code == 200
    assert reset(client, token, "yet-another-pass-3").status_code == 400
    assert login(client, user, NEW).status_code == 200


def test_an_expired_link_is_rejected(client, outbox, user):
    forgot(client, user)
    age_tokens(minutes=31)
    assert reset(client, token_from(outbox[0])).status_code == 400
    assert login(client, user, OLD).status_code == 200


def test_a_made_up_token_is_rejected(client, outbox, user):
    assert reset(client, "x" * 43).status_code == 400


def test_a_new_request_cancels_the_older_link(client, outbox, user):
    forgot(client, user)
    first = token_from(outbox[0])
    age_tokens(minutes=5)  # past the cooldown but still inside the 30 minutes
    forgot(client, user)
    second = token_from(outbox[1])

    assert first != second
    assert reset(client, first).status_code == 400
    assert reset(client, second).status_code == 200


def test_the_new_password_must_be_long_enough(client, outbox, user):
    forgot(client, user)
    assert reset(client, token_from(outbox[0]), "short").status_code == 422
