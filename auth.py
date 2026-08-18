from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Optional

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

COOKIE = "la_auth"
MAX_AGE = 60 * 60 * 24 * 90
_login_hits: dict[str, list[float]] = {}


def password() -> str:
    return os.environ.get("APP_PASSWORD", "").strip()


def secret() -> bytes:
    raw = os.environ.get("APP_SECRET", "").strip() or "listenalong-dev-secret"
    return raw.encode("utf-8")


def required() -> bool:
    if os.environ.get("RENDER"):
        return True
    return bool(password())


def sign(value: str) -> str:
    digest = hmac.new(secret(), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{value}.{digest}"


def valid_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    value, _, digest = token.rpartition(".")
    expected = hmac.new(secret(), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest) and value == "ok"


def check_password(candidate: str) -> bool:
    expected = password()
    if not expected:
        return not required()
    return hmac.compare_digest(candidate, expected)


def rate_limited(ip: str) -> bool:
    now = time.time()
    window = [t for t in _login_hits.get(ip, []) if now - t < 60]
    _login_hits[ip] = window
    if len(window) >= 12:
        return True
    window.append(now)
    return False


def set_session(response: Response) -> None:
    response.set_cookie(
        COOKIE,
        sign("ok"),
        httponly=True,
        samesite="lax",
        secure=bool(os.environ.get("RENDER")),
        max_age=MAX_AGE,
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def authorized(request: Request) -> bool:
    if not required():
        return True
    return valid_token(request.cookies.get(COOKIE))


PUBLIC_EXACT = {
    "/",
    "/login",
    "/healthz",
    "/manifest.json",
    "/sw.js",
    "/api/login",
    "/api/me",
}


def is_public(path: str) -> bool:
    if path in PUBLIC_EXACT:
        return True
    return path.startswith("/static/")


async def gate(request: Request, call_next):
    if request.method == "OPTIONS" or is_public(request.url.path):
        return await call_next(request)
    if authorized(request):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Sign in required"}, status_code=401)
    return JSONResponse({"detail": "Sign in required"}, status_code=401)


def new_secret() -> str:
    return secrets.token_urlsafe(32)
