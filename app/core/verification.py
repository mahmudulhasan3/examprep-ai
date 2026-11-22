import hashlib
import hmac
import math
import secrets
from datetime import datetime, timezone

from app.core.security import SECRET_KEY

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60
RESET_TTL_MINUTES = 30


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC so comparisons work."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def cooldown_remaining(last_sent_at: datetime, now: datetime) -> int:
    """Seconds left before another code or link may be requested (0 when allowed)."""
    elapsed = (now - as_utc(last_sent_at)).total_seconds()
    return max(0, math.ceil(RESEND_COOLDOWN_SECONDS - elapsed))


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(email: str, otp: str) -> str:
    """Keyed hash of the code. A 6-digit code is easy to brute-force if hashed with
    plain SHA-256, so the server's SECRET_KEY is mixed in."""
    message = f"otp:{email}:{otp}".encode()
    return hmac.new(SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def verify_otp(email: str, otp: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(email, otp), stored_hash)


def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Reset tokens are long random strings, so a plain SHA-256 is enough."""
    return hashlib.sha256(token.encode()).hexdigest()
