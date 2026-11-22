import re
from datetime import timedelta

import pytest

from app.core.email_service import EmailError, EmailNotConfigured
from app.core.verification import utcnow

PASSWORD = "testpass123"


@pytest.fixture(autouse=True)
def verification_on(monkeypatch):
    monkeypatch.setenv("EMAIL_VERIFICATION", "true")
    monkeypatch.setenv("EMAIL_DEV_MODE", "true")  # counts as "email is configured"


@pytest.fixture()
def outbox(monkeypatch):
    """Capture every email instead of sending it."""
    sent = []

    def fake_send(to_email, subject, html_body, text_body):
        sent.append(
            {"to": to_email, "subject": subject, "html": html_body, "text": text_body}
        )

    monkeypatch.setattr("app.routers.auth.send_email", fake_send)
    return sent


def code_from(message) -> str:
    match = re.search(r"\b(\d{6})\b", message["text"])
    assert match, "no 6-digit code in the email"
    return match.group(1)


def register(client, email="new@example.com", password=PASSWORD):
    return client.post("/auth/register", json={"email": email, "password": password})


def verify(client, email, otp):
    return client.post("/auth/verify-email", json={"email": email, "otp": otp})


def login(client, email, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def expire_cooldown(email):
    from tests.conftest import TestingSessionLocal
    from app.db.models import PendingRegistration

    with TestingSessionLocal() as db:
        pending = db.query(PendingRegistration).filter_by(email=email).one()
        pending.last_sent_at = utcnow() - timedelta(minutes=5)
        db.commit()


def test_register_sends_a_code_and_creates_no_user_yet(client, outbox):
    response = register(client)
    assert response.status_code == 202
    assert response.json()["email"] == "new@example.com"
    assert len(outbox) == 1
    assert outbox[0]["to"] == "new@example.com"
    assert "verification code" in outbox[0]["subject"]
    assert re.fullmatch(r"\d{6}", code_from(outbox[0]))
    assert login(client, "new@example.com").status_code == 404


def test_correct_code_creates_the_account_and_sends_the_welcome_mail(client, outbox):
    register(client)
    response = verify(client, "new@example.com", code_from(outbox[0]))
    assert response.status_code == 200
    assert response.json()["email"] == "new@example.com"
    assert login(client, "new@example.com").status_code == 200

    assert len(outbox) == 2
    welcome = outbox[1]
    assert welcome["to"] == "new@example.com"
    assert "Welcome" in welcome["subject"]
    assert "Regards" in welcome["text"]
    assert '<a href="https://www.linkedin.com/in/mahmudulhasan03/"' in welcome["html"]
    assert ">Mahmudul Hasan</a>" in welcome["html"]


def test_a_failing_welcome_mail_does_not_undo_the_account(client, monkeypatch):
    sent = []

    def flaky(to_email, subject, html_body, text_body):
        if "Welcome" in subject:
            raise EmailError("brevo down")
        sent.append(text_body)

    monkeypatch.setattr("app.routers.auth.send_email", flaky)
    register(client)
    match = re.search(r"\b(\d{6})\b", sent[0])
    assert match
    code = match.group(1)
    assert verify(client, "new@example.com", code).status_code == 200
    assert login(client, "new@example.com").status_code == 200


def test_the_code_is_stored_hashed(client, outbox):
    register(client)
    otp = code_from(outbox[0])

    from tests.conftest import TestingSessionLocal
    from app.db.models import PendingRegistration

    with TestingSessionLocal() as db:
        pending = db.query(PendingRegistration).one()
        assert pending.otp_hash != otp
        assert len(pending.otp_hash) == 64
        assert otp not in pending.hashed_password


def test_wrong_code_counts_attempts_then_locks(client, outbox):
    register(client)
    good = code_from(outbox[0])
    bad = "000000" if good != "000000" else "111111"

    first = verify(client, "new@example.com", bad)
    assert first.status_code == 400
    assert "4 attempt(s) left" in first.json()["detail"]

    for _ in range(3):
        verify(client, "new@example.com", bad)
    last = verify(client, "new@example.com", bad)
    assert last.status_code == 400
    assert "Too many wrong attempts" in last.json()["detail"]

    assert verify(client, "new@example.com", good).status_code == 400
    assert login(client, "new@example.com").status_code == 404


def test_expired_code_is_rejected(client, outbox):
    register(client)
    from tests.conftest import TestingSessionLocal
    from app.db.models import PendingRegistration

    with TestingSessionLocal() as db:
        pending = db.query(PendingRegistration).one()
        pending.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

    response = verify(client, "new@example.com", code_from(outbox[0]))
    assert response.status_code == 400
    assert login(client, "new@example.com").status_code == 404


def test_verify_without_registering_is_rejected(client, outbox):
    assert verify(client, "ghost@example.com", "123456").status_code == 400


@pytest.mark.parametrize("otp", ["12345", "1234567", "abcdef", "12 456", ""])
def test_malformed_codes_are_rejected_early(client, outbox, otp):
    assert verify(client, "new@example.com", otp).status_code == 422


def test_registering_again_too_soon_is_rate_limited(client, outbox):
    register(client)
    again = register(client)
    assert again.status_code == 429
    assert "Please wait" in again.json()["detail"]
    assert len(outbox) == 1


def test_registering_again_later_replaces_the_old_code(client, outbox):
    register(client)
    old_code = code_from(outbox[0])
    expire_cooldown("new@example.com")

    assert register(client, password="another-pass-9").status_code == 202
    new_code = code_from(outbox[1])
    if old_code != new_code:
        assert verify(client, "new@example.com", old_code).status_code == 400
    assert verify(client, "new@example.com", new_code).status_code == 200
    assert login(client, "new@example.com", "another-pass-9").status_code == 200


def test_resend_gives_a_fresh_code_after_the_cooldown(client, outbox):
    register(client)
    too_soon = client.post("/auth/resend-otp", json={"email": "new@example.com"})
    assert too_soon.status_code == 429

    expire_cooldown("new@example.com")
    resent = client.post("/auth/resend-otp", json={"email": "new@example.com"})
    assert resent.status_code == 200
    assert len(outbox) == 2
    assert verify(client, "new@example.com", code_from(outbox[1])).status_code == 200


def test_resend_without_a_pending_signup_is_404(client, outbox):
    response = client.post("/auth/resend-otp", json={"email": "ghost@example.com"})
    assert response.status_code == 404


def test_an_already_registered_email_is_conflict(client, outbox):
    register(client)
    verify(client, "new@example.com", code_from(outbox[0]))
    assert register(client).status_code == 409


def test_email_failure_returns_502_and_stores_nothing(client, monkeypatch):
    def boom(*args):
        raise EmailError("brevo down")

    monkeypatch.setattr("app.routers.auth.send_email", boom)
    assert register(client).status_code == 502

    from tests.conftest import TestingSessionLocal
    from app.db.models import PendingRegistration

    with TestingSessionLocal() as db:
        assert db.query(PendingRegistration).count() == 0


def test_missing_email_settings_return_503(client, monkeypatch):
    def not_configured(*args):
        raise EmailNotConfigured("no key")

    monkeypatch.setattr("app.routers.auth.send_email", not_configured)
    assert register(client).status_code == 503


def test_verification_can_be_switched_off_for_local_work(client, monkeypatch):
    monkeypatch.setenv("EMAIL_VERIFICATION", "false")
    response = register(client)
    assert response.status_code == 200
    assert login(client, "new@example.com").status_code == 200
