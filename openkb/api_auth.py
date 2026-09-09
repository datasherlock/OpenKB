"""Identity and authorization helpers for OpenKB REST API.

Supports Google Identity-Aware Proxy (IAP) identity headers:
- ``X-Goog-Authenticated-User-Email``: ``accounts.google.com:<email>``
Enforces role-based permissions:
- Read endpoints: open to authenticated corporate users (or local dev).
- Write endpoints: restricted to configured administrators (``OPENKB_ADMIN_EMAILS``)
  or valid API bearer tokens (``OPENKB_API_TOKEN``).
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)
auth_router = APIRouter()


def get_authenticated_user_email(request: Request) -> str | None:
    """Extract and normalize user email from Google IAP or proxy headers."""
    raw = request.headers.get("x-goog-authenticated-user-email")
    if not raw:
        return None
    raw = raw.strip()
    if ":" in raw:
        # e.g. "accounts.google.com:jeromerajan@google.com" -> "jeromerajan@google.com"
        return raw.split(":", 1)[1].strip().lower()
    return raw.lower()


def get_admin_emails() -> set[str]:
    """Return the configured set of admin email addresses (lowercased)."""
    raw = os.environ.get("OPENKB_ADMIN_EMAILS", "")
    if not raw:
        return set()
    return {email.strip().lower() for email in raw.split(",") if email.strip()}


def is_valid_bearer_token(credentials: HTTPAuthorizationCredentials | None) -> bool:
    """Check if the provided bearer token matches OPENKB_API_TOKEN."""
    expected = os.environ.get("OPENKB_API_TOKEN")
    if not expected or not credentials or credentials.scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(credentials.credentials, expected)


def require_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> None:
    """Classic OpenKB bearer token dependency (backward compatibility)."""
    expected = os.environ.get("OPENKB_API_TOKEN")
    if not expected:
        return
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required.",
        )
    if not hmac.compare_digest(credentials.credentials, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
        )


def require_read_permission(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str | None:
    """Authorize read operations (query, chat, view pages, view graph).

    Allowed if:
    1. A valid bearer token is provided.
    2. An IAP user email is present.
    3. OPENKB_API_TOKEN is unset (local dev or unauthenticated read mode).
    """
    if is_valid_bearer_token(credentials):
        return "bearer-token"

    email = get_authenticated_user_email(request)
    if email:
        return email

    expected_token = os.environ.get("OPENKB_API_TOKEN")
    if expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token or authenticated user identity required.",
        )

    return "anonymous"


def require_write_permission(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str | None:
    """Authorize mutation operations (add, remove, recompile, page edit/delete, config).

    Allowed if:
    1. A valid bearer token is provided (matching OPENKB_API_TOKEN).
    2. OPENKB_ADMIN_EMAILS is set and the IAP user email matches an admin email.
    3. Neither OPENKB_ADMIN_EMAILS nor OPENKB_API_TOKEN is set (local dev mode).
    """
    if is_valid_bearer_token(credentials):
        return "admin-bearer-token"

    admin_emails = get_admin_emails()
    if admin_emails:
        email = get_authenticated_user_email(request)
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required: no verified user email or valid bearer token provided.",
            )
        if email not in admin_emails:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Forbidden: user '{email}' does not have write permissions. "
                    f"Modifications are restricted to administrators."
                ),
            )
        return email

    # If no admin emails are configured, fall back to OPENKB_API_TOKEN requirement
    expected_token = os.environ.get("OPENKB_API_TOKEN")
    if expected_token:
        require_bearer_token(credentials)
        return "bearer-token"

    return "local-dev"


@auth_router.get("/api/v1/auth/whoami")
async def whoami_endpoint(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    """Inspect current caller identity and administrative capabilities."""
    email = get_authenticated_user_email(request)
    admin_emails = get_admin_emails()
    has_token = is_valid_bearer_token(credentials)

    if has_token:
        is_admin = True
    elif admin_emails:
        is_admin = bool(email and email in admin_emails)
    else:
        is_admin = not bool(os.environ.get("OPENKB_API_TOKEN")) or has_token

    return {
        "email": email,
        "is_admin": is_admin,
        "authenticated": bool(email or has_token),
        "admin_enforced": bool(admin_emails),
    }
