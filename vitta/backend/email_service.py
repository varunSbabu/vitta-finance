"""Email sending for Vitta — verification links, password resets, etc.

Pluggable backend: set EMAIL_BACKEND in .env to switch providers.
Default is "log" — prints the email to structlog so local dev works
without any external service. When a real provider is configured
(e.g. "resend"), the send function dispatches to that backend.

Every caller uses send_email() and doesn't care about the backend.
"""

from __future__ import annotations

import os

import structlog

log = structlog.get_logger()

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "log").strip().lower()
EMAIL_FROM = os.environ.get("EMAIL_FROM", "Vitta <noreply@vitta.app>")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5757")


def send_email(*, to: str, subject: str, body_text: str, body_html: str | None = None) -> bool:
    """Send an email. Returns True on success, False on failure (logged, never raised)."""
    if EMAIL_BACKEND == "log":
        return _send_log(to=to, subject=subject, body_text=body_text)
    log.error("email.unknown_backend", backend=EMAIL_BACKEND)
    return False


def _send_log(*, to: str, subject: str, body_text: str) -> bool:
    log.info(
        "email.sent",
        backend="log",
        to=to,
        subject=subject,
        body=body_text,
    )
    return True


def send_verification_email(*, to: str, token: str) -> bool:
    link = f"{FRONTEND_URL}/verify-email?token={token}"
    return send_email(
        to=to,
        subject="Verify your Vitta account",
        body_text=f"Click to verify your email: {link}\n\nThis link expires in 24 hours.",
        body_html=None,
    )


def send_password_reset_email(*, to: str, token: str) -> bool:
    link = f"{FRONTEND_URL}/reset-password?token={token}"
    return send_email(
        to=to,
        subject="Reset your Vitta password",
        body_text=f"Click to reset your password: {link}\n\nThis link expires in 1 hour. If you didn't request this, ignore this email.",
        body_html=None,
    )
