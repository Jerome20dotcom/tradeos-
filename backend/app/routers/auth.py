import hashlib
import logging
import secrets
import smtplib
import time
import uuid
from email.message import EmailMessage
from urllib.parse import quote

import jwt
import psycopg
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pwdlib import PasswordHash

from app.config import get_settings

router = APIRouter(prefix="/v1/auth", tags=["authentication"])
password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash("tradeos-invalid-login-placeholder")
logger = logging.getLogger(__name__)


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class EmailAddress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=200)


class PasswordResetConfirmation(TokenRequest):
    password: str = Field(min_length=12, max_length=128)


def _issue_token(user_id: uuid.UUID, email: str) -> dict:
    settings = get_settings()
    expires_in = 30 * 60
    token = jwt.encode(
        {
            "sub": str(user_id),
            "aud": settings.jwt_audience,
            "exp": int(time.time()) + expires_in,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {
        "user_id": str(user_id),
        "email": email,
        "access_token": token,
        "expires_in": expires_in,
    }


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _email_security_link(email: str, purpose: str, token: str) -> None:
    settings = get_settings()
    if not settings.email_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email delivery is not configured",
        )
    action = "verify" if purpose == "verify_email" else "reset"
    link = f"{settings.public_base_url.rstrip('/')}/?{action}={quote(token)}"
    subject = "Verify your TradeOS email" if purpose == "verify_email" else "Reset your TradeOS password"
    instruction = (
        "Confirm your email address to activate your TradeOS account."
        if purpose == "verify_email"
        else "Use this link to choose a new password."
    )
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_sender
    message["To"] = email
    message.set_content(f"{instruction}\n\n{link}\n\nIf you did not request this, you can ignore this email.")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.exception("Could not deliver a TradeOS account email")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not send account email; check mail delivery configuration",
        )


def _create_email_token(conn, user_id: uuid.UUID, purpose: str, expires_in: str) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        "update auth_tokens set consumed_at = now() "
        "where user_id = %s and purpose = %s and consumed_at is null",
        (user_id, purpose),
    )
    conn.execute(
        "insert into auth_tokens (token_hash, user_id, purpose, expires_at) "
        "values (%s, %s, %s, now() + %s::interval)",
        (_token_digest(token), user_id, purpose, expires_in),
    )
    return token


@router.get("/config")
def auth_config():
    settings = get_settings()
    return {
        "development_login_available": settings.environment == "development",
        "email_password_available": settings.email_configured,
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: Credentials):
    from app.db import connect

    if not get_settings().email_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email delivery must be configured before account registration",
        )
    email = str(body.email).strip().lower()
    encoded_password = password_hash.hash(body.password)
    user_id = uuid.uuid4()
    try:
        with connect() as conn:
            conn.execute(
                "insert into auth_users (id, email, password_hash) values (%s, %s, %s)",
                (user_id, email, encoded_password),
            )
            token = _create_email_token(conn, user_id, "verify_email", "24 hours")
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unable to register with this email address",
        ) from exc
    _email_security_link(email, "verify_email", token)
    return {"message": "Check your email to verify your account"}


@router.post("/login")
def login(body: Credentials):
    from app.db import connect

    email = str(body.email).strip().lower()
    with connect() as conn:
        user = conn.execute(
            "select id, email, password_hash, email_verified_at from auth_users where email = %s",
            (email,),
        ).fetchone()
    stored_hash = user["password_hash"] if user is not None else DUMMY_PASSWORD_HASH
    valid_password = password_hash.verify(body.password, stored_hash)
    if user is None or not valid_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user["email_verified_at"] is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verify your email address before signing in",
        )
    return _issue_token(user["id"], user["email"])


@router.post("/verify-email")
def verify_email(body: TokenRequest):
    from app.db import connect

    with connect() as conn:
        row = conn.execute(
            "select t.user_id, u.email from auth_tokens t "
            "join auth_users u on u.id = t.user_id "
            "where t.token_hash = %s and t.purpose = 'verify_email' "
            "and t.consumed_at is null and t.expires_at > now() for update of t",
            (_token_digest(body.token),),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=400, detail="Verification link is invalid or expired")
        conn.execute("update auth_users set email_verified_at = now() where id = %s", (row["user_id"],))
        conn.execute(
            "update auth_tokens set consumed_at = now() where token_hash = %s",
            (_token_digest(body.token),),
        )
    return _issue_token(row["user_id"], row["email"])


@router.post("/verification/request")
def request_verification(body: EmailAddress):
    from app.db import connect

    if not get_settings().email_configured:
        raise HTTPException(status_code=503, detail="Email delivery is not configured")
    email = str(body.email).strip().lower()
    with connect() as conn:
        user = conn.execute(
            "select id from auth_users where email = %s and email_verified_at is null",
            (email,),
        ).fetchone()
        if user is not None:
            token = _create_email_token(conn, user["id"], "verify_email", "24 hours")
    if user is not None:
        _email_security_link(email, "verify_email", token)
    return {"message": "If the account can be verified, a message will be sent"}


@router.post("/password-reset/request")
def request_password_reset(body: EmailAddress):
    from app.db import connect

    if not get_settings().email_configured:
        raise HTTPException(status_code=503, detail="Email delivery is not configured")
    email = str(body.email).strip().lower()
    with connect() as conn:
        user = conn.execute("select id from auth_users where email = %s", (email,)).fetchone()
        if user is not None:
            token = _create_email_token(conn, user["id"], "reset_password", "1 hour")
    if user is not None:
        _email_security_link(email, "reset_password", token)
    return {"message": "If an account exists for that email, a reset link will be sent"}


@router.post("/password-reset/confirm")
def confirm_password_reset(body: PasswordResetConfirmation):
    from app.db import connect

    with connect() as conn:
        row = conn.execute(
            "select user_id from auth_tokens where token_hash = %s and purpose = 'reset_password' "
            "and consumed_at is null and expires_at > now() for update",
            (_token_digest(body.token),),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=400, detail="Reset link is invalid or expired")
        conn.execute(
            "update auth_users set password_hash = %s where id = %s",
            (password_hash.hash(body.password), row["user_id"]),
        )
        conn.execute(
            "update auth_tokens set consumed_at = now() "
            "where user_id = %s and purpose = 'reset_password' and consumed_at is null",
            (row["user_id"],),
        )
    return {"message": "Password updated. You can now sign in"}
