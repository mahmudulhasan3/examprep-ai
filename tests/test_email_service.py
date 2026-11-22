from types import SimpleNamespace

import pytest
import requests

from app.core import email_service, email_templates, verification
from app.core.email_service import EmailError, EmailNotConfigured, send_email


@pytest.fixture()
def brevo_env(monkeypatch):
    monkeypatch.delenv("EMAIL_DEV_MODE", raising=False)
    monkeypatch.setenv("BREVO_API_KEY", "secret-key-123")
    monkeypatch.setenv("BREVO_SENDER_EMAIL", "sender@example.com")
    monkeypatch.setenv("BREVO_SENDER_NAME", "ExamPrep AI")


def test_send_email_posts_the_documented_brevo_request(monkeypatch, brevo_env):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return SimpleNamespace(ok=True, status_code=201, text="{}")

    monkeypatch.setattr(email_service.requests, "post", fake_post)
    send_email("student@example.com", "Hello", "<p>Hi</p>", "Hi")

    assert captured["url"] == "https://api.brevo.com/v3/smtp/email"
    assert captured["headers"]["api-key"] == "secret-key-123"
    assert captured["json"] == {
        "sender": {"name": "ExamPrep AI", "email": "sender@example.com"},
        "to": [{"email": "student@example.com"}],
        "subject": "Hello",
        "htmlContent": "<p>Hi</p>",
        "textContent": "Hi",
    }
    assert captured["timeout"] > 0


def test_send_email_without_settings_raises_not_configured(monkeypatch):
    monkeypatch.delenv("EMAIL_DEV_MODE", raising=False)
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    monkeypatch.delenv("BREVO_SENDER_EMAIL", raising=False)
    with pytest.raises(EmailNotConfigured):
        send_email("a@example.com", "s", "<p>h</p>", "t")


def test_a_rejected_email_raises_without_leaking_the_key(monkeypatch, brevo_env):
    monkeypatch.setattr(
        email_service.requests,
        "post",
        lambda *a, **k: SimpleNamespace(ok=False, status_code=401, text="unauthorized"),
    )
    with pytest.raises(EmailError) as caught:
        send_email("a@example.com", "s", "<p>h</p>", "t")
    assert "401" in str(caught.value)
    assert "secret-key-123" not in str(caught.value)


def test_a_network_failure_becomes_an_email_error(monkeypatch, brevo_env):
    def boom(*args, **kwargs):
        raise requests.exceptions.ConnectionError("no network")

    monkeypatch.setattr(email_service.requests, "post", boom)
    with pytest.raises(EmailError):
        send_email("a@example.com", "s", "<p>h</p>", "t")


def test_dev_mode_logs_instead_of_sending(monkeypatch, caplog):
    monkeypatch.setenv("EMAIL_DEV_MODE", "true")

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("dev mode must not call Brevo")

    monkeypatch.setattr(email_service.requests, "post", must_not_be_called)
    send_email("a@example.com", "Your code", "<p>h</p>", "code is 123456")
    assert "code is 123456" in caplog.text


@pytest.mark.parametrize(
    "value, expected",
    [
        ("true", True),
        ("TRUE", True),
        ("1", True),
        ("false", False),
        ("off", False),
        ("", True),
    ],
)
def test_email_verification_flag(monkeypatch, value, expected):
    monkeypatch.setenv("EMAIL_VERIFICATION", value)
    assert email_service.email_verification_enabled() is expected


def test_welcome_template_links_the_signature_to_linkedin():
    subject, html_body, text_body = email_templates.welcome_email(
        "https://app.example.com"
    )
    assert "Welcome" in subject
    assert (
        '<a href="https://www.linkedin.com/in/mahmudulhasan03/"' in html_body
        and ">Mahmudul Hasan</a>" in html_body
    )
    assert "Regards,\nMahmudul Hasan" in text_body
    assert 'href="https://app.example.com"' in html_body


def test_otp_template_shows_the_code_and_lifetime():
    subject, html_body, text_body = email_templates.otp_email("042917", 10)
    assert "042917" in html_body and "042917" in text_body
    assert "10 minutes" in html_body


def test_reset_template_escapes_the_link():
    link = "https://app.example.com/?reset_token=abc&x=<b>"
    _, html_body, text_body = email_templates.reset_email(link, 30)
    assert "<b>" not in html_body
    assert "&lt;b&gt;" in html_body
    assert link in text_body


def test_generated_codes_are_six_digits():
    codes = {verification.generate_otp() for _ in range(200)}
    assert all(len(code) == 6 and code.isdigit() for code in codes)
    assert len(codes) > 150


def test_code_hash_depends_on_the_email_and_the_code():
    base = verification.hash_otp("a@example.com", "123456")
    assert verification.verify_otp("a@example.com", "123456", base)
    assert not verification.verify_otp("a@example.com", "123457", base)
    assert not verification.verify_otp("b@example.com", "123456", base)


def test_naive_datetimes_are_treated_as_utc():
    from datetime import datetime, timezone

    naive = datetime(2026, 1, 1, 12, 0)
    assert verification.as_utc(naive).tzinfo == timezone.utc
