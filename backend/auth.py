"""无密码登录：邮箱验证码 + HMAC 签名会话 Cookie。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from email.utils import parseaddr

from fastapi import HTTPException, Request

from . import config

COOKIE_NAME = "mc_session"


def normalize_email(raw: str) -> str:
    email = parseaddr((raw or "").strip())[1].lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="invalid_email")
    return email


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def code_digest(email: str, code: str) -> str:
    message = f"{normalize_email(email)}:{code}".encode("utf-8")
    return hmac.new(config.SECRET_KEY.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_session(email: str) -> str:
    payload = {
        "email": normalize_email(email),
        "exp": int(time.time()) + config.SESSION_TTL_HOURS * 3600,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64(
        hmac.new(config.SECRET_KEY.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def parse_session(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = _b64(
        hmac.new(config.SECRET_KEY.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_unb64(body))
    except Exception:
        return None
    if int(payload.get("exp", 0)) <= int(time.time()):
        return None
    return payload.get("email")


def current_email(request: Request) -> str:
    if config.PUBLIC_ACCESS:
        return "public@local"
    email = parse_session(request.cookies.get(COOKIE_NAME))
    if not email:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return email


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=config.SESSION_TTL_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
