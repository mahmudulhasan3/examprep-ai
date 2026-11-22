import logging

import requests

from app.core.env_utils import env_flag, get_optional_env_variable

logger = logging.getLogger(__name__)

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


class EmailError(Exception):
    """An email could not be sent."""


class EmailNotConfigured(EmailError):
    """Brevo settings are missing, so no email can be sent."""


def email_verification_enabled() -> bool:
    """Whether new accounts must confirm their email with a code (default: yes)."""
    return env_flag("EMAIL_VERIFICATION", True)


def email_is_configured() -> bool:
    if env_flag("EMAIL_DEV_MODE", False):
        return True
    return bool(
        get_optional_env_variable("BREVO_API_KEY")
        and get_optional_env_variable("BREVO_SENDER_EMAIL")
    )


def send_email(to_email: str, subject: str, html_body: str, text_body: str) -> None:
    """Send one transactional email through Brevo.

    With EMAIL_DEV_MODE=true nothing is sent; the message is printed in the server log
    instead, which is handy for local testing without a Brevo account.
    """
    if env_flag("EMAIL_DEV_MODE", False):
        logger.warning(
            "EMAIL_DEV_MODE is on, email not sent.\nTo: %s\nSubject: %s\n\n%s",
            to_email,
            subject,
            text_body,
        )
        return

    api_key = get_optional_env_variable("BREVO_API_KEY")
    sender_email = get_optional_env_variable("BREVO_SENDER_EMAIL")
    if not api_key or not sender_email:
        raise EmailNotConfigured("BREVO_API_KEY or BREVO_SENDER_EMAIL is not set")

    payload = {
        "sender": {
            "name": get_optional_env_variable("BREVO_SENDER_NAME", "ExamPrep AI"),
            "email": sender_email,
        },
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_body,
        "textContent": text_body,
    }
    try:
        response = requests.post(
            BREVO_URL,
            headers={"api-key": api_key, "accept": "application/json"},
            json=payload,
            timeout=10,
        )
    except requests.exceptions.RequestException as error:
        raise EmailError("Could not reach the email service") from error

    if not response.ok:
        # log what Brevo said, but never the API key
        raise EmailError(
            f"Brevo rejected the email (HTTP {response.status_code}): {response.text[:300]}"
        )
