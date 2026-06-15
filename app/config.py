import os
from pathlib import Path


def truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def truthy_env(name: str, default: bool = False) -> bool:
    return truthy(os.getenv(name), default)


def int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("APP_DATA_DIR", str(BASE_DIR))).expanduser().resolve()
JOBS_DIR = DATA_DIR / "jobs"
WEB_DIR = BASE_DIR / "web"
DB_PATH = DATA_DIR / "app_data.sqlite3"

SESSION_COOKIE = "vocals_session"
SESSION_DAYS = int_env("SESSION_DAYS", 30)
GUEST_SESSION_HOURS = int_env("GUEST_SESSION_HOURS", 6)


STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").strip().lower()
STORAGE_ENDPOINT = os.getenv("STORAGE_ENDPOINT", "").strip()
STORAGE_ACCESS_KEY = os.getenv("STORAGE_ACCESS_KEY", "stemdeck")
STORAGE_SECRET_KEY = os.getenv("STORAGE_SECRET_KEY", "stemdeck-secret")
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "stemdeck")
STORAGE_SECURE = truthy_env("STORAGE_SECURE", False)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBAPP_BASE_URL = os.getenv("TELEGRAM_WEBAPP_BASE_URL", "http://localhost:8000").rstrip("/")
TELEGRAM_LINK_SECRET = os.getenv(
    "TELEGRAM_LINK_SECRET",
    TELEGRAM_BOT_TOKEN or "stemdeck-default-secret",
)

# Demucs separation: "local" (default) or "replicate" (cjwbw/demucs on Replicate, with local fallback).
DEMUCS_BACKEND = os.getenv("DEMUCS_BACKEND", "local").strip().lower()
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "").strip()
REPLICATE_DEMUCS_MODEL = os.getenv("REPLICATE_DEMUCS_MODEL", "cjwbw/demucs").strip()
