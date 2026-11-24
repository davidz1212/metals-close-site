"""Resend 邮件发送封装：仅发送登录验证码，密钥只在服务端环境变量中。"""
from __future__ import annotations

import logging

import httpx

from . import config

log = logging.getLogger("metals-close.mailer")

SUBJECTS = {
    "zh": "【贵金属收盘日报】登录验证码",
    "en": "[Metals Close] Your sign-in code",
}


def _content(code: str, lang: str) -> tuple[str, str]:
    if lang == "en":
        text = (
            f"Your sign-in code for Metals Close is {code}.\n"
            "It expires in 10 minutes. If you did not request this, ignore this email.\n"
        )
        html = (
            '<div style="font-family:Arial,sans-serif;color:#222">'
            "<h2>Metals Close</h2>"
            "<p>Your sign-in code is:</p>"
            f'<div style="font-size:34px;letter-spacing:8px;font-weight:700">{code}</div>'
            "<p>This code expires in 10 minutes. If you did not request it, ignore this email.</p>"
            "</div>"
        )
    else:
        text = (
            f"您的贵金属收盘日报登录验证码是 {code}。\n"
            "验证码 10 分钟内有效。若非本人操作，请忽略本邮件。\n"
        )
        html = (
            '<div style="font-family:Arial,sans-serif;color:#222">'
            "<h2>贵金属收盘日报</h2>"
            "<p>您的登录验证码是：</p>"
            f'<div style="font-size:34px;letter-spacing:8px;font-weight:700">{code}</div>'
            "<p>验证码 10 分钟内有效。若非本人操作，请忽略本邮件。</p>"
            "</div>"
        )
    return text, html


def send_login_code(email: str, code: str, lang: str = "zh") -> bool:
    """返回 True 表示已真实发出；开发模式未配置 Resend 时返回 False。"""
    if not config.resend_configured():
        log.warning("Resend not configured; code not sent (dev_mode=%s)", config.DEV_MODE)
        return False
    text, html = _content(code, lang)
    payload = {
        "from": config.RESEND_FROM_EMAIL,
        "to": [email],
        "subject": SUBJECTS.get(lang, SUBJECTS["zh"]),
        "text": text,
        "html": html,
    }
    try:
        resp = httpx.post(
            config.RESEND_API_URL,
            headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
            json=payload,
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"mail_network_error: {type(exc).__name__}") from exc
    if resp.status_code >= 300:
        raise RuntimeError(f"mail_provider_error: HTTP {resp.status_code}")
    return True
