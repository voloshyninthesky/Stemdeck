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

FAST_SEPARATOR_BACKEND = os.getenv("FAST_SEPARATOR_BACKEND", "sherpa_uvr").strip().lower()
FAST_SEPARATOR_MODEL = os.getenv("FAST_SEPARATOR_MODEL", "UVR-MDX-NET-Voc_FT.onnx")
FAST_SEPARATOR_MODEL_DIR = Path(
    os.getenv(
        "FAST_SEPARATOR_MODEL_DIR",
        os.getenv("XDG_CACHE_HOME", str(BASE_DIR / "models")),
    )
).expanduser()
FAST_SPLEETER_MODEL_URL = os.getenv(
    "FAST_SPLEETER_MODEL_URL",
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "source-separation-models/sherpa-onnx-spleeter-2stems-fp16.tar.bz2",
)
FAST_SPLEETER_MODEL_DIR = Path(
    os.getenv(
        "FAST_SPLEETER_MODEL_DIR",
        str(Path(os.getenv("XDG_CACHE_HOME", str(BASE_DIR / "models"))) / "spleeter"),
    )
).expanduser()
FAST_SPLEETER_NUM_THREADS = int_env("FAST_SPLEETER_NUM_THREADS", 4)
FAST_SHERPA_UVR_MODEL = os.getenv("FAST_SHERPA_UVR_MODEL", "UVR-MDX-NET-Inst_HQ_4.onnx")
FAST_SHERPA_UVR_TARGET_STEM = os.getenv(
    "FAST_SHERPA_UVR_TARGET_STEM",
    "instrumental",
).strip().lower()
FAST_SHERPA_UVR_MODEL_URL_BASE = os.getenv(
    "FAST_SHERPA_UVR_MODEL_URL_BASE",
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/source-separation-models",
).rstrip("/")
FAST_SHERPA_UVR_MODEL_DIR = Path(
    os.getenv(
        "FAST_SHERPA_UVR_MODEL_DIR",
        str(Path(os.getenv("XDG_CACHE_HOME", str(BASE_DIR / "models"))) / "sherpa-uvr"),
    )
).expanduser()
FAST_SHERPA_UVR_NUM_THREADS = int_env("FAST_SHERPA_UVR_NUM_THREADS", 4)

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").strip().lower()
STORAGE_ENDPOINT = os.getenv("STORAGE_ENDPOINT", "").strip()
STORAGE_ACCESS_KEY = os.getenv("STORAGE_ACCESS_KEY", "stemdeck")
STORAGE_SECRET_KEY = os.getenv("STORAGE_SECRET_KEY", "stemdeck-secret")
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "stemdeck")
STORAGE_SECURE = truthy_env("STORAGE_SECURE", False)
