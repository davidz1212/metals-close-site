"""Paddle Billing 预留接口：结账会话创建 + Webhook 签名校验与订阅状态回写。

未配置 PADDLE_API_KEY / PADDLE_VENDOR_ID / PADDLE_PRICE_ID_* 时，
所有入口返回 configured=False，前端只展示「订阅通道待配置」，不会产生真实扣款。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException, Request

from . import config, db

log = logging.getLogger("metals-close.paddle")
PADDLE_API = "https://api.paddle.com"
SIGNATURE_TOLERANCE_SECONDS = 300


def plan_info(lang: str = "zh") -> dict:
    if lang == "en":
        return {
            "name": "Annual subscription",
            "price": f"CNY {config.PRICE_CNY_PER_YEAR}/year (approx. US${config.PRICE_USD_PER_YEAR})",
            "note": "Final charged amount and currency are shown on Paddle checkout.",
        }
    return {
        "name": "年度订阅",
        "price": f"{config.PRICE_CNY_PER_YEAR} 元/年（约 US${config.PRICE_USD_PER_YEAR}）",
        "note": "实际币种与金额以 Paddle 结算页为准。",
    }


def create_subscription_checkout(email: str, lang: str = "zh", plan: str = "yearly") -> dict:
    if not config.paddle_configured():
        return {
            "configured": False,
            "reason": "paddle_not_configured",
            "plan": plan_info(lang),
        }
    if plan != "yearly":
        raise HTTPException(status_code=400, detail="unsupported_plan")
    price_id = (
        config.PADDLE_PRICE_ID_USD if lang == "en" and config.PADDLE_PRICE_ID_USD
        else config.PADDLE_PRICE_ID_CNY
    )
    body = {
        "items": [{"price_id": price_id, "quantity": 1}],
        "customer": {"email": email},
        "effective_at": "immediately",
        "return_url": f"{config.SITE_BASE_URL}/?subscribed=1",
        "custom_data": {"subscriber_email": email, "plan": plan},
    }
    try:
        resp = httpx.post(
            f"{PADDLE_API}/subscriptions",
            headers={
                "Authorization": f"Bearer {config.PADDLE_API_KEY}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"paddle_network_error: {type(exc).__name__}") from exc
    if resp.status_code >= 300:
        log.error("Paddle checkout failed: HTTP %s", resp.status_code)
        raise HTTPException(status_code=502, detail="paddle_checkout_failed")
    data = (resp.json() or {}).get("data") or {}
    checkout = data.get("checkout") or {}
    url = checkout.get("url")
    if not url:
        raise HTTPException(status_code=502, detail="paddle_checkout_url_missing")
    return {"configured": True, "checkout_url": url, "subscription_id": data.get("id")}


def _verify_signature(raw: bytes, signature_header: str) -> bool:
    if not config.PADDLE_WEBHOOK_SECRET or not signature_header:
        return False
    parts = dict(
        item.split("=", 1) for item in signature_header.split(";") if "=" in item
    )
    ts, h1 = parts.get("ts"), parts.get("h1")
    if not ts or not h1:
        return False
    try:
        if abs(int(ts) - int(datetime.now(timezone.utc).timestamp())) > SIGNATURE_TOLERANCE_SECONDS:
            return False
    except ValueError:
        return False
    signed = f"{ts}:".encode() + raw
    expected = hmac.new(
        config.PADDLE_WEBHOOK_SECRET.encode(), signed, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, h1)


async def handle_webhook(request: Request) -> dict:
    raw = await request.body()
    if not _verify_signature(raw, request.headers.get("paddle-signature", "")):
        raise HTTPException(status_code=401, detail="invalid_webhook_signature")
    try:
        event = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc

    event_id = str(event.get("event_id") or "")
    event_type = str(event.get("event_type") or "")
    if not event_id or not db.record_webhook_event(event_id, event_type, raw.decode("utf-8", "replace")):
        return {"received": True, "duplicate": True}

    data = event.get("data") or {}
    customer = data.get("customer") or {}
    email = (customer.get("email") or "").lower()
    custom = data.get("custom_data") or {}
    email = email or str(custom.get("subscriber_email") or "").lower()
    subscription_id = data.get("id")

    if event_type in {"subscription.active", "subscription.updated"}:
        if email:
            period = data.get("current_billing_period") or {}
            expires_at = period.get("ends_at") or data.get("next_billing_at")
            db.upsert_subscriber(
                email,
                status="active",
                expires_at=expires_at,
                paddle_subscription_id=subscription_id,
                source="paddle",
                note=f"webhook {event_type}",
            )
    elif event_type in {"subscription.canceled", "subscription.expired"}:
        if email:
            db.upsert_subscriber(
                email,
                status="cancelled" if "canceled" in event_type else "expired",
                paddle_subscription_id=subscription_id,
                source="paddle",
                note=f"webhook {event_type}",
            )
    db.log_event(email or None, f"paddle.{event_type}", event_id)
    return {"received": True, "event_type": event_type, "email_configured": bool(email)}


def demo_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=365)).isoformat(timespec="seconds")
