import html

APP_NAME = "ExamPrep AI"
LINKEDIN_URL = "https://www.linkedin.com/in/mahmudulhasan03/"

TEXT_STYLE = "margin:0 0 14px;font-size:15px;line-height:1.6;color:#374151;"
BUTTON_STYLE = (
    "display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;"
    "font-weight:600;font-size:15px;padding:12px 24px;border-radius:8px;"
)


def _page(heading: str, content: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f4f5f7;font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="520" cellpadding="0" cellspacing="0" style="max-width:520px;width:100%;background:#ffffff;border-radius:12px;">
<tr><td style="padding:32px;">
<h2 style="margin:0 0 18px;font-size:22px;color:#111827;">{heading}</h2>
{content}
</td></tr>
</table>
<p style="margin:16px 0 0;font-size:12px;color:#9ca3af;">{APP_NAME}</p>
</td></tr>
</table>
</body>
</html>"""


def otp_email(otp: str, ttl_minutes: int) -> tuple[str, str, str]:
    """Return (subject, html, text) for the registration code email."""
    subject = f"Your {APP_NAME} verification code"
    content = f"""
<p style="{TEXT_STYLE}">Use this code to finish creating your account:</p>
<p style="margin:20px 0;padding:16px;background:#f3f4f6;border-radius:8px;text-align:center;font-size:34px;font-weight:700;letter-spacing:8px;color:#111827;">{html.escape(otp)}</p>
<p style="{TEXT_STYLE}">The code expires in {ttl_minutes} minutes. If you did not sign up, you can safely ignore this email.</p>
"""
    text = (
        f"Your {APP_NAME} verification code is {otp}\n\n"
        f"It expires in {ttl_minutes} minutes. "
        "If you did not sign up, you can safely ignore this email."
    )
    return subject, _page("Verify your email", content), text


def welcome_email(app_url: str) -> tuple[str, str, str]:
    """Return (subject, html, text) for the welcome email sent after verification."""
    subject = f"Welcome to {APP_NAME}"
    safe_url = html.escape(app_url, quote=True)
    content = f"""
<p style="{TEXT_STYLE}">Hi there,</p>
<p style="{TEXT_STYLE}">Your email is verified and your account is ready. We are really glad to have you with us!</p>
<p style="{TEXT_STYLE}">Here is what you can do right now:</p>
<ul style="margin:0 0 18px;padding-left:20px;font-size:15px;line-height:1.8;color:#374151;">
<li>Chat with an AI study assistant about any subject</li>
<li>Generate practice exams on any topic you choose</li>
<li>Write your answers and get instant AI feedback and scores</li>
<li>Look back at your past exams to see how you are improving</li>
</ul>
<p style="margin:24px 0;"><a href="{safe_url}" style="{BUTTON_STYLE}">Open {APP_NAME}</a></p>
<p style="{TEXT_STYLE}">Good luck with your preparation. You have got this!</p>
<p style="margin:28px 0 0;font-size:15px;line-height:1.6;color:#374151;">Regards,<br><a href="{LINKEDIN_URL}" style="color:#2563eb;font-weight:600;text-decoration:none;">Mahmudul Hasan</a></p>
"""
    text = (
        "Hi there,\n\n"
        "Your email is verified and your account is ready. "
        "We are really glad to have you with us!\n\n"
        "Here is what you can do right now:\n"
        "- Chat with an AI study assistant about any subject\n"
        "- Generate practice exams on any topic you choose\n"
        "- Write your answers and get instant AI feedback and scores\n"
        "- Look back at your past exams to see how you are improving\n\n"
        f"Open {APP_NAME}: {app_url}\n\n"
        "Good luck with your preparation. You have got this!\n\n"
        f"Regards,\nMahmudul Hasan\n{LINKEDIN_URL}"
    )
    return subject, _page(f"Welcome to {APP_NAME}", content), text


def reset_email(reset_link: str, ttl_minutes: int) -> tuple[str, str, str]:
    """Return (subject, html, text) for the password reset email."""
    subject = f"Reset your {APP_NAME} password"
    safe_link = html.escape(reset_link, quote=True)
    content = f"""
<p style="{TEXT_STYLE}">We received a request to reset your password. Click the button below to choose a new one:</p>
<p style="margin:24px 0;"><a href="{safe_link}" style="{BUTTON_STYLE}">Reset password</a></p>
<p style="{TEXT_STYLE}">The link works once and expires in {ttl_minutes} minutes. If the button does not work, copy this address into your browser:</p>
<p style="margin:0 0 14px;font-size:13px;line-height:1.5;word-break:break-all;color:#6b7280;">{html.escape(reset_link)}</p>
<p style="{TEXT_STYLE}">If you did not ask for this, you can safely ignore this email. Your password will not change.</p>
"""
    text = (
        "We received a request to reset your password.\n\n"
        f"Open this link to choose a new one:\n{reset_link}\n\n"
        f"The link works once and expires in {ttl_minutes} minutes. "
        "If you did not ask for this, you can safely ignore this email."
    )
    return subject, _page("Reset your password", content), text
