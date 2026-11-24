"""对外贵金属日报站点：FastAPI 入口。"""
from __future__ import annotations

import datetime as dt
import logging
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, config, db, mailer, paddle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("metals-close")

app = FastAPI(title="Metals Close", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(config.WEB_DIR)), name="static")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CodeRequest(BaseModel):
    email: str = Field(max_length=254)
    lang: str = Field(default="zh", pattern="^(zh|en)$")


class VerifyRequest(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(min_length=4, max_length=10)


class SubscribeRequest(BaseModel):
    email: str = Field(max_length=254)
    lang: str = Field(default="zh", pattern="^(zh|en)$")
    plan: str = Field(default="yearly")


_TZ8 = dt.timezone(dt.timedelta(hours=8))
_AUTO_THREAD_STARTED = False


def _run_auto_update(slot_label: str) -> None:
    cmd = [sys.executable, str(config.BASE_DIR / "tools" / "build_daily_snapshot.py"), "--date", "auto", "--ingest"]
    log_path = config.DATA_DIR / "auto_update.log"
    ts = dt.datetime.now(_TZ8).isoformat(timespec="seconds")
    log.info("auto_update[%s] starting ...", slot_label)
    try:
        proc = subprocess.run(cmd, cwd=str(config.BASE_DIR), capture_output=True, text=True, timeout=180)
        entry = f"\n=== {ts} [{slot_label}] exit={proc.returncode} ===\n{proc.stdout}{proc.stderr}"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(entry)
        if proc.returncode == 0:
            log.info("auto_update[%s] finished OK", slot_label)
        else:
            log.warning("auto_update[%s] exited with code %s", slot_label, proc.returncode)
    except Exception as exc:
        log.error("auto_update[%s] failed: %s", slot_label, exc)


def _cme_pdf_signature() -> tuple:
    cme_dir = config.DATA_DIR / "cme"
    if not cme_dir.is_dir():
        return ()
    return tuple(sorted((p.name, int(p.stat().st_mtime), p.stat().st_size) for p in cme_dir.glob("*.pdf")))


def _auto_update_loop() -> None:
    done_slots: set[str] = set()
    last_cme_sig = _cme_pdf_signature()
    while True:
        try:
            now = dt.datetime.now(_TZ8)
            hhmm = now.strftime("%H:%M")
            day_key = now.strftime("%Y-%m-%d")
            slot_id = f"{day_key} {hhmm}"
            if hhmm in config.AUTO_UPDATE_TIMES and slot_id not in done_slots:
                done_slots.add(slot_id)
                if len(done_slots) > 20:
                    done_slots = {s for s in done_slots if s.startswith(day_key)}
                _run_auto_update(slot_id)
            cur_cme_sig = _cme_pdf_signature()
            if cur_cme_sig and cur_cme_sig != last_cme_sig:
                last_cme_sig = cur_cme_sig
                _run_auto_update("cme-pdf-drop")
        except Exception as exc:
            log.error("auto_update_loop error: %s", exc)
        time.sleep(30)


@app.on_event("startup")
def startup() -> None:
    global _AUTO_THREAD_STARTED
    db.init_db()
    if config.PUBLIC_ACCESS:
        log.info("PUBLIC_ACCESS=on: reports are open without login/subscription (LAN test mode).")
    elif not config.resend_configured() and not config.DEV_MODE:
        log.warning("Resend is not configured and DEV_MODE is off: sign-in emails will be disabled.")
    if config.DEV_MODE and not config.PUBLIC_ACCESS:
        log.warning("DEV_MODE=on: verification codes are returned in API responses. NEVER use in production.")
    if config.AUTO_UPDATE and not _AUTO_THREAD_STARTED:
        _AUTO_THREAD_STARTED = True
        threading.Thread(target=_auto_update_loop, name="auto-update", daemon=True).start()
        log.info("AUTO_UPDATE=on: scheduled daily at %s (Asia/Shanghai)", ",".join(config.AUTO_UPDATE_TIMES))
    log.info("DB=%s reports=%s", config.DB_PATH, db.counts()["reports"])


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(config.WEB_DIR / "index.html"))


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "counts": db.counts(),
        "resend_configured": config.resend_configured(),
        "paddle_configured": config.paddle_configured(),
        "dev_mode": config.DEV_MODE,
        "public_access": config.PUBLIC_ACCESS,
        "auto_update": config.AUTO_UPDATE,
        "auto_update_times": config.AUTO_UPDATE_TIMES,
    }


@app.get("/api/public/status")
def public_status() -> dict:
    """登录前可访问：仅暴露默认日期、开放模式和价格，不泄露任何报告数据。"""
    return {
        "default_date": db.default_report_date(),
        "dates_count": len(db.list_report_dates()),
        "plan": paddle.plan_info("zh"),
        "plan_en": paddle.plan_info("en"),
        "paddle_configured": config.paddle_configured(),
        "resend_configured": config.resend_configured(),
        "dev_mode": config.DEV_MODE,
        "public_access": config.PUBLIC_ACCESS,
        "auto_update": config.AUTO_UPDATE,
    }


@app.get("/api/reports/dates")
def report_dates(email: str = Depends(auth.current_email)) -> dict:
    return {"dates": db.list_report_dates(), "default": db.default_report_date()}


@app.get("/api/reports/{report_date}")
def report(report_date: str, email: str = Depends(auth.current_email)) -> dict:
    if not DATE_RE.match(report_date):
        raise HTTPException(status_code=400, detail="invalid_date")
    data = db.get_report(report_date)
    if not data:
        raise HTTPException(status_code=404, detail="report_not_found")
    return data


@app.post("/api/auth/code")
def request_code(body: CodeRequest, request: Request) -> dict:
    email = auth.normalize_email(body.email)
    if not db.is_subscriber_active(email):
        raise HTTPException(status_code=403, detail="no_active_subscription")
    last = db.last_code_request(email)
    if last is not None and int(time.time()) - last < config.CODE_COOLDOWN_SECONDS:
        raise HTTPException(status_code=429, detail="too_many_requests")

    code = auth.new_code()
    db.create_code(email, auth.code_digest(email, code), config.CODE_TTL_SECONDS, request.client.host if request.client else None)
    sent = False
    if config.resend_configured():
        try:
            sent = mailer.send_login_code(email, code, body.lang)
        except RuntimeError as exc:
            log.error("send code failed: %s", exc)
            raise HTTPException(status_code=502, detail="mail_send_failed") from exc

    db.log_event(email, "code_requested", "sent" if sent else "dev_mode" if config.DEV_MODE else "not_sent")
    result = {
        "ok": True,
        "expires_in": config.CODE_TTL_SECONDS,
        "sent": sent,
        "dev_mode": config.DEV_MODE,
    }
    if config.DEV_MODE and not config.resend_configured():
        result["dev_code"] = code
    return result


@app.post("/api/auth/verify")
def verify_code(body: VerifyRequest) -> JSONResponse:
    email = auth.normalize_email(body.email)
    result = db.verify_code(email, auth.code_digest(email, body.code.strip()))
    if result != "ok":
        raise HTTPException(status_code=400, detail=f"code_{result}")
    token = auth.make_session(email)
    db.log_event(email, "login_success")
    response = JSONResponse({"ok": True, "email": email})
    auth.set_session_cookie(response, token)
    return response


@app.post("/api/auth/logout")
def logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    auth.clear_session_cookie(response)
    return response


@app.get("/api/me")
def me(email: str = Depends(auth.current_email)) -> dict:
    if config.PUBLIC_ACCESS:
        return {
            "email": email,
            "subscribed": True,
            "public_access": True,
            "status": "public",
            "expires_at": None,
        }
    sub = db.subscriber_info(email)
    return {
        "email": email,
        "subscribed": db.is_subscriber_active(email),
        "public_access": False,
        "status": sub["status"] if sub else None,
        "expires_at": sub["expires_at"] if sub else None,
    }


@app.post("/api/subscribe/checkout")
def subscribe(body: SubscribeRequest) -> dict:
    email = auth.normalize_email(body.email)
    result = paddle.create_subscription_checkout(email, body.lang, body.plan)
    db.log_event(email, "checkout_attempt", "configured" if result.get("configured") else "not_configured")
    return result


@app.post("/api/webhooks/paddle")
async def paddle_webhook(request: Request) -> dict:
    return await paddle.handle_webhook(request)
