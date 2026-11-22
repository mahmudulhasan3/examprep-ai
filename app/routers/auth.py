import logging
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import email_templates
from app.core.email_service import (
    EmailError,
    EmailNotConfigured,
    email_is_configured,
    email_verification_enabled,
    send_email,
)
from app.core.env_utils import get_optional_env_variable
from app.core.security import hash_password, verify_password, create_token_access
from app.core.verification import (
    OTP_MAX_ATTEMPTS,
    OTP_TTL_MINUTES,
    RESET_TTL_MINUTES,
    as_utc,
    cooldown_remaining,
    generate_otp,
    generate_reset_token,
    hash_otp,
    hash_token,
    utcnow,
    verify_otp,
)
from app.db.database import get_db
from app.db.models import PasswordResetToken, PendingRegistration, User
from app.schemas.user import (
    ForgotPasswordRequest,
    MessageResponse,
    PendingRegistrationResponse,
    ResendOtpRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserRegisterResponse,
    VerifyEmailRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

if not email_verification_enabled():
    logger.warning("EMAIL_VERIFICATION is off: new accounts skip the email code.")


def app_base_url() -> str:
    return get_optional_env_variable("APP_BASE_URL", "http://localhost:8501").rstrip(
        "/"
    )


def send_or_fail(to_email: str, message: tuple[str, str, str]) -> None:
    """Send an email that the request depends on; turn failures into HTTP errors."""
    subject, html_body, text_body = message
    try:
        send_email(to_email, subject, html_body, text_body)
    except EmailNotConfigured:
        logger.error("Email is not configured (set the BREVO_* variables in .env)")
        raise HTTPException(status_code=503, detail="Email service is not configured.")
    except EmailError:
        logger.exception("Sending an email failed")
        raise HTTPException(
            status_code=502, detail="Could not send the email. Please try again."
        )


def send_welcome_email(to_email: str) -> None:
    """Runs after the response; a failure here must never undo a verified account."""
    subject, html_body, text_body = email_templates.welcome_email(app_base_url())
    try:
        send_email(to_email, subject, html_body, text_body)
    except EmailError:
        logger.exception("Could not send the welcome email")


def start_pending(pending: PendingRegistration, now, otp: str) -> None:
    pending.otp_hash = hash_otp(pending.email, otp)
    pending.attempts = 0
    pending.expires_at = now + timedelta(minutes=OTP_TTL_MINUTES)
    pending.last_sent_at = now


@router.post(
    "/register", response_model=UserRegisterResponse | PendingRegistrationResponse
)
def register(
    user_data: UserRegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(status_code=409, detail="User already exists")

    if not email_verification_enabled():
        hashed_pw = hash_password(user_data.password)
        new_user = User(email=user_data.email, hashed_password=hashed_pw)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user

    now = utcnow()
    pending = (
        db.query(PendingRegistration)
        .filter(PendingRegistration.email == user_data.email)
        .first()
    )
    if pending is not None:
        wait = cooldown_remaining(pending.last_sent_at, now)
        if wait > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {wait} seconds before asking for a new code.",
            )
    else:
        pending = PendingRegistration(email=user_data.email)
        db.add(pending)

    otp = generate_otp()
    pending.hashed_password = hash_password(user_data.password)
    start_pending(pending, now, otp)

    # Send first, save second: if the email cannot be sent, nothing is stored.
    send_or_fail(user_data.email, email_templates.otp_email(otp, OTP_TTL_MINUTES))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=429, detail="A code was just sent. Please check your email."
        )

    response.status_code = 202
    return {
        "message": "We sent a 6-digit code to your email.",
        "email": user_data.email,
    }


@router.post("/verify-email", response_model=UserRegisterResponse)
def verify_email(
    data: VerifyEmailRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    pending = (
        db.query(PendingRegistration)
        .filter(PendingRegistration.email == data.email)
        .first()
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="Invalid or expired code.")

    if as_utc(pending.expires_at) < utcnow():
        db.delete(pending)
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired code.")

    if not verify_otp(pending.email, data.otp, pending.otp_hash):
        pending.attempts += 1
        remaining = OTP_MAX_ATTEMPTS - pending.attempts
        if remaining <= 0:
            db.delete(pending)
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="Too many wrong attempts. Please register again.",
            )
        db.commit()
        raise HTTPException(
            status_code=400, detail=f"Incorrect code. {remaining} attempt(s) left."
        )

    if db.query(User).filter(User.email == pending.email).first():
        db.delete(pending)
        db.commit()
        raise HTTPException(status_code=409, detail="User already exists")

    user = User(email=pending.email, hashed_password=pending.hashed_password)
    db.add(user)
    db.delete(pending)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="User already exists")
    db.refresh(user)

    background_tasks.add_task(send_welcome_email, user.email)
    return user


@router.post("/resend-otp", response_model=PendingRegistrationResponse)
def resend_otp(data: ResendOtpRequest, db: Session = Depends(get_db)):
    pending = (
        db.query(PendingRegistration)
        .filter(PendingRegistration.email == data.email)
        .first()
    )
    if pending is None:
        raise HTTPException(
            status_code=404,
            detail="No pending sign-up for this email. Please register again.",
        )

    now = utcnow()
    wait = cooldown_remaining(pending.last_sent_at, now)
    if wait > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Please wait {wait} seconds before asking for a new code.",
        )

    otp = generate_otp()
    start_pending(pending, now, otp)
    send_or_fail(pending.email, email_templates.otp_email(otp, OTP_TTL_MINUTES))
    db.commit()
    return {"message": "We sent a new code to your email.", "email": pending.email}


@router.post("/login", response_model=TokenResponse)
def login(user_data: UserLoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_data.email).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="No account found with this email. Please register first.",
        )
    if not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect password.")
    access_token = create_token_access({"user_id": user.id})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    if not email_is_configured():
        raise HTTPException(status_code=503, detail="Email service is not configured.")

    # The same answer whether or not the email exists, so nobody can probe for accounts.
    generic = {"message": "If this email is registered, a reset link has been sent."}

    user = db.query(User).filter(User.email == data.email).first()
    if user is None:
        return generic

    now = utcnow()
    latest = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user.id)
        .order_by(PasswordResetToken.id.desc())
        .first()
    )
    if latest is not None and cooldown_remaining(latest.created_at, now) > 0:
        return generic

    # A new request cancels every older link.
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).delete()
    token = generate_reset_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=now + timedelta(minutes=RESET_TTL_MINUTES),
            created_at=now,
        )
    )
    db.commit()

    link = f"{app_base_url()}/?reset_token={token}"
    subject, html_body, text_body = email_templates.reset_email(link, RESET_TTL_MINUTES)
    try:
        send_email(user.email, subject, html_body, text_body)
    except EmailError:
        logger.exception("Could not send the password reset email")
    return generic


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    invalid = HTTPException(status_code=400, detail="Invalid or expired reset link.")

    record = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == hash_token(data.token))
        .first()
    )
    now = utcnow()
    if record is None or record.used_at is not None or as_utc(record.expires_at) < now:
        raise invalid

    user = db.get(User, record.user_id)
    if user is None:
        raise invalid

    user.hashed_password = hash_password(data.new_password)
    record.used_at = now
    db.commit()
    return {"message": "Your password has been reset. You can now log in."}
