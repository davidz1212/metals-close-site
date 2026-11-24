"""站点配置：所有密钥只从环境变量读取，不写入代码。"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env", override=False)
except Exception:
    pass

DATA_DIR = BASE_DIR / "data"
WEB_DIR = BASE_DIR / "web"
DB_PATH = Path(os.environ.get("MC_DB_PATH", str(DATA_DIR / "site.db")))


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _secret_key() -> str:
    """生产环境必须显式设置 SECRET_KEY；本地开发自动生成并落盘一次。"""
    key = os.environ.get("SECRET_KEY", "").strip()
    if key:
        return key
    dev_file = DATA_DIR / ".dev_secret"
    if dev_file.exists():
        return dev_file.read_text(encoding="utf-8").strip()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48)
    dev_file.write_text(key, encoding="utf-8")
    return key


SECRET_KEY = _secret_key()
DEV_MODE = _env_flag("MC_DEV_MODE", default=False)
PUBLIC_ACCESS = _env_flag("MC_PUBLIC_ACCESS", default=False)
AUTO_UPDATE = _env_flag("MC_AUTO_UPDATE", default=True)
AUTO_UPDATE_TIMES = [
    t.strip() for t in os.environ.get("MC_AUTO_UPDATE_TIMES", "07:30,17:30").split(",") if t.strip()
]
COOKIE_SECURE = _env_flag("MC_COOKIE_SECURE", default=False)
SESSION_TTL_HOURS = int(os.environ.get("MC_SESSION_TTL_HOURS", "24"))
CODE_TTL_SECONDS = int(os.environ.get("MC_CODE_TTL_SECONDS", "600"))
CODE_MAX_ATTEMPTS = int(os.environ.get("MC_CODE_MAX_ATTEMPTS", "5"))
CODE_COOLDOWN_SECONDS = int(os.environ.get("MC_CODE_COOLDOWN_SECONDS", "60"))

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "").strip()
RESEND_API_URL = os.environ.get("RESEND_API_URL", "https://api.resend.com/emails").strip()

PADDLE_API_KEY = os.environ.get("PADDLE_API_KEY", "").strip()
PADDLE_VENDOR_ID = os.environ.get("PADDLE_VENDOR_ID", "").strip()
PADDLE_ENV = os.environ.get("PADDLE_ENV", "sandbox").strip().lower()
PADDLE_PRICE_ID_CNY = os.environ.get("PADDLE_PRICE_ID_CNY", "").strip()
PADDLE_PRICE_ID_USD = os.environ.get("PADDLE_PRICE_ID_USD", "").strip()
PADDLE_WEBHOOK_SECRET = os.environ.get("PADDLE_WEBHOOK_SECRET", "").strip()
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "http://127.0.0.1:8765").strip().rstrip("/")

PRICE_CNY_PER_YEAR = int(os.environ.get("MC_PRICE_CNY", "99"))
PRICE_USD_PER_YEAR = int(os.environ.get("MC_PRICE_USD", "14"))


def paddle_configured() -> bool:
    return bool(PADDLE_API_KEY and PADDLE_VENDOR_ID and PADDLE_PRICE_ID_CNY)


def resend_configured() -> bool:
    return bool(RESEND_API_KEY and RESEND_FROM_EMAIL)
