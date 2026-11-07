from __future__ import annotations

from collections import OrderedDict

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
MAX_TRACKED_IPS = 4096
_login_hits: OrderedDict[str, list[float]] = OrderedDict()


def password() -> str:
    return os.environ.get("APP_PASSWORD", "").strip()


def secret() -> bytes:
    raw = os.environ.get("APP_SECRET", "").strip()
    if os.environ.get("RENDER") and len(raw) < 32:
        raise RuntimeError("Hosted ListenAlong requires APP_SECRET of at least 32 characters")
    return (raw or "listenalong-dev-secret").encode("utf-8")


def required() -> bool:
    if os.environ.get("RENDER"):
        return True
    return bool(password())


def sign(value: str) -> str:
    # Session tokens are time-bound. Previously issued static "ok" cookies
    # intentionally stop working after this upgrade; users must sign in again.
    if value == "ok":
        value = f"v1:{int(time.time())}"
    digest = hmac.new(secret(), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{value}.{digest}"


def valid_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    value, _, digest = token.rpartition(".")
    if not value.startswith("v1:"):
        return False
    timestamp = value[3:]
    if not timestamp.isascii() or not timestamp.isdecimal() or len(timestamp) > 12:
        return False
    issued_at = int(timestamp)
    now = int(time.time())
    # Bound server-side validity independently of the browser cookie's expiry.
    if issued_at > now + 60 or now - issued_at > MAX_AGE:
        return False
    expected = hmac.new(secret(), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest)


def check_password(candidate: str) -> bool:
    expected = password()
    if not expected:
        return not required()
    return hmac.compare_digest(candidate, expected)


def rate_limited(ip: str) -> bool:
    now = time.time()
    if ip not in _login_hits and len(_login_hits) >= MAX_TRACKED_IPS:
        # Bound process memory under many unique source IPs. This is not a
        # substitute for shared reverse-proxy throttling in multi-worker hosts.
        for key, hits in list(_login_hits.items()):
            if not hits or now - hits[-1] >= 60:
                del _login_hits[key]
        if len(_login_hits) >= MAX_TRACKED_IPS:
            _login_hits.popitem(last=False)
    window = [t for t in _login_hits.get(ip, []) if now - t < 60]
    _login_hits[ip] = window
    _login_hits.move_to_end(ip)
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
