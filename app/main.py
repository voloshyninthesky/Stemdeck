import hashlib
import hmac
import threading
import time
import uuid
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app import db
from app import storage
from app.range_response import parse_byte_range, stream_local_file
import json
from app.tasks import process_job
from app.chords import detect_chords
from app.processing import convert_wav_to_mp3


TOKEN_TTL = 24 * 3600  # 24 hours


def generate_mixer_token(job_id: str) -> str:
    """Create a signed token granting access to a job's stems for TOKEN_TTL seconds."""
    ts = str(int(time.time()))
    sig = hmac.new(
        config.TELEGRAM_LINK_SECRET.encode(),
        f"{job_id}:{ts}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{ts}:{sig}"


def verify_mixer_token(job_id: str, token: str) -> bool:
    """Verify a signed mixer token."""
    try:
        ts_str, sig = token.split(":", 1)
    except (ValueError, AttributeError):
        return False
    expected = hmac.new(
        config.TELEGRAM_LINK_SECRET.encode(),
        f"{job_id}:{ts_str}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(sig, expected)

config.JOBS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Vocal Remover App API",
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/assets", StaticFiles(directory=config.WEB_DIR), name="assets")


@app.on_event("startup")
def startup() -> None:
    db.init_db()
    storage.ensure_bucket()


@app.get("/")
def root() -> FileResponse:
    return FileResponse(config.WEB_DIR / "index.html")


@app.get("/mixer")
def mixer_page() -> FileResponse:
    return FileResponse(config.WEB_DIR / "mixer.html")


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(config.WEB_DIR / "manifest.webmanifest")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    return FileResponse(config.WEB_DIR / "sw.js")


@app.get("/icons/{name}")
def icon(name: str) -> FileResponse:
    icon_path = config.WEB_DIR / "icons" / Path(name).name
    if not icon_path.exists():
        raise HTTPException(status_code=404, detail="Icon not found")
    return FileResponse(icon_path)


def current_user(
    vocals_session: str | None = Cookie(default=None, alias=config.SESSION_COOKIE),
) -> dict[str, Any]:
    user = db.get_user_by_session(vocals_session)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def optional_current_user(
    vocals_session: str | None = Cookie(default=None, alias=config.SESSION_COOKIE),
) -> dict[str, Any] | None:
    return db.get_user_by_session(vocals_session)


def guest_session_ttl() -> timedelta:
    return timedelta(hours=max(1, config.GUEST_SESSION_HOURS))


def set_session_cookie(
    response: Response,
    token: str,
    max_age_seconds: int,
) -> None:
    response.set_cookie(
        config.SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=max_age_seconds,
    )


def create_guest_session(response: Response) -> dict[str, Any]:
    user = db.create_guest_user()
    token = db.create_session(user["id"], ttl=guest_session_ttl())
    set_session_cookie(
        response,
        token,
        max_age_seconds=60 * 60 * max(1, config.GUEST_SESSION_HOURS),
    )
    user["is_guest"] = True
    return user


def transfer_guest_jobs(
    vocals_session: str | None,
    target_user_id: int,
) -> None:
    guest = db.get_user_by_session(vocals_session)
    if guest and guest.get("is_guest"):
        db.transfer_jobs(guest["id"], target_user_id)


def serialize_job(job: dict[str, Any]) -> dict[str, Any]:
    queue_position = db.queue_position(job["id"])
    payload = {
        "id": job["id"],
        "filename": job["original_filename"],
        "status": job["status"],
        "progress": job["progress"],
        "message": job["message"],
        "error": job["error"],
        "duration": job["duration"],
        "separation_mode": job.get("separation_mode", "quality"),
        "queue_position": queue_position,
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "completed_at": job["completed_at"],
        "chords": json.loads(job["chords"]) if job.get("chords") else None,
        "instrumental_url": None,
        "vocals_url": None,
    }

    if (job["instrumental_path"] and job["vocals_path"]) or (
        job.get("instrumental_key") and job.get("vocals_key")
    ):
        payload["instrumental_url"] = f"/api/jobs/{job['id']}/files/instrumental"
        payload["vocals_url"] = f"/api/jobs/{job['id']}/files/vocals"

    return payload


def enqueue_job(job_id: str) -> None:
    try:
        process_job.delay(job_id)
    except Exception:
        db.update_job(
            job_id,
            status="processing",
            progress=1,
            message="RabbitMQ unavailable, running locally",
        )
        thread = threading.Thread(target=process_job.run, args=(job_id,), daemon=True)
        thread.start()


@app.post("/api/register")
def register(
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    vocals_session: str | None = Cookie(default=None, alias=config.SESSION_COOKIE),
) -> dict[str, Any]:
    try:
        user = db.create_user(username, password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    transfer_guest_jobs(vocals_session, user["id"])
    token = db.create_session(user["id"])
    set_session_cookie(response, token, max_age_seconds=60 * 60 * 24 * config.SESSION_DAYS)
    user["is_guest"] = False
    return {"user": user}


@app.post("/api/login")
def login(
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    vocals_session: str | None = Cookie(default=None, alias=config.SESSION_COOKIE),
) -> dict[str, Any]:
    user = db.authenticate_user(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    transfer_guest_jobs(vocals_session, user["id"])
    token = db.create_session(user["id"])
    set_session_cookie(response, token, max_age_seconds=60 * 60 * 24 * config.SESSION_DAYS)
    return {"user": user}


@app.post("/api/guest")
def guest(response: Response) -> dict[str, Any]:
    return {
        "user": create_guest_session(response),
        "ttl_hours": max(1, config.GUEST_SESSION_HOURS),
    }


@app.post("/api/logout")
def logout(
    response: Response,
    vocals_session: str | None = Cookie(default=None, alias=config.SESSION_COOKIE),
) -> dict[str, str]:
    if vocals_session:
        db.delete_session(vocals_session)
    response.delete_cookie(config.SESSION_COOKIE)
    return {"status": "ok"}


@app.get("/api/me")
def me(
    response: Response,
    user: dict[str, Any] | None = Depends(optional_current_user),
) -> dict[str, Any]:
    if user:
        return {"user": user}
    return {
        "user": create_guest_session(response),
        "ttl_hours": max(1, config.GUEST_SESSION_HOURS),
    }


@app.get("/api/jobs")
def jobs(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"jobs": [serialize_job(job) for job in db.list_jobs(user["id"])]}


@app.get("/api/jobs/{job_id}")
def job_detail(
    job_id: str,
    token: str | None = Query(default=None),
    user: dict[str, Any] | None = Depends(optional_current_user),
) -> dict[str, Any]:
    # Check token first (so Telegram bot/mixer url works even if web user cookie is set but doesn't own this job)
    if token and verify_mixer_token(job_id, token):
        job = db.get_job(job_id)
    elif user:
        job = db.get_job(job_id, user["id"])
    else:
        raise HTTPException(status_code=401, detail="Login required")

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": serialize_job(job)}


@app.get("/api/jobs/{job_id}/files/{stem}")
def job_file(
    job_id: str,
    stem: str,
    format: str | None = Query(default=None),
    range_header: str | None = Header(default=None, alias="Range"),
    token: str | None = Query(default=None),
    user: dict[str, Any] | None = Depends(optional_current_user),
) -> Response:
    if stem not in {"instrumental", "vocals"}:
        raise HTTPException(status_code=404, detail="File not found")

    # Support token-based auth (for Telegram mixer) or cookie auth
    # Check token first (so Telegram bot/mixer url works even if web user cookie is set but doesn't own this job)
    if token and verify_mixer_token(job_id, token):
        job = db.get_job(job_id)
    elif user:
        job = db.get_job(job_id, user["id"])
    else:
        raise HTTPException(status_code=401, detail="Login required")

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # We want static immutable cache for both wav and mp3 files
    cache_headers = {
        "Cache-Control": "public, max-age=31536000, immutable"
    }

    # Determine paths and keys saved in the database
    db_path = Path(job.get(f"{stem}_path") or "")
    db_key = job.get(f"{stem}_key")

    # Check if the job uses pure MP3 storage
    is_pure_mp3 = (db_path.suffix == ".mp3") or (db_key and db_key.endswith(".mp3"))

    if is_pure_mp3:
        # ─────────────────────────────────────────────────────────────
        # New Pure MP3 storage layout - serve MP3 directly
        # ─────────────────────────────────────────────────────────────
        media_type = "audio/mpeg"
        filename = f"{stem}.mp3"

        if db_key and storage.is_object_storage_enabled():
            total_size = storage.object_size(db_key)
            start, length, status_code, headers = parse_byte_range(
                range_header,
                total_size,
                filename,
            )
            headers.update(cache_headers)
            return StreamingResponse(
                storage.stream_object(db_key, offset=start, length=length),
                status_code=status_code,
                media_type=media_type,
                headers=headers,
            )
        else:
            if not db_path or not db_path.exists():
                raise HTTPException(status_code=404, detail="File not found")
            total_size = db_path.stat().st_size
            start, length, status_code, headers = parse_byte_range(
                range_header,
                total_size,
                filename,
            )
            headers.update(cache_headers)
            return StreamingResponse(
                stream_local_file(db_path, start, length),
                status_code=status_code,
                media_type=media_type,
                headers=headers,
            )

    else:
        # ─────────────────────────────────────────────────────────────
        # Legacy WAV storage layout - serve WAV or convert to MP3 on-demand
        # ─────────────────────────────────────────────────────────────
        wav_path = db_path
        mp3_path = wav_path.with_suffix(".mp3") if wav_path else None

        if format == "mp3":
            media_type = "audio/mpeg"
            filename = f"{stem}.mp3"

            if db_key and storage.is_object_storage_enabled():
                mp3_key = db_key.replace(".wav", ".mp3")
                mp3_exists = False
                try:
                    storage.client().stat_object(config.STORAGE_BUCKET, mp3_key)
                    mp3_exists = True
                except Exception:
                    pass

                if not mp3_exists:
                    if not wav_path.exists():
                        wav_path.parent.mkdir(parents=True, exist_ok=True)
                        storage.client().fget_object(config.STORAGE_BUCKET, db_key, str(wav_path))
                    actual_mp3_path = convert_wav_to_mp3(wav_path)
                    storage.put_file(actual_mp3_path, mp3_key)

                total_size = storage.object_size(mp3_key)
                start, length, status_code, headers = parse_byte_range(
                    range_header,
                    total_size,
                    filename,
                )
                headers.update(cache_headers)
                return StreamingResponse(
                    storage.stream_object(mp3_key, offset=start, length=length),
                    status_code=status_code,
                    media_type=media_type,
                    headers=headers,
                )

            else:
                if not mp3_path or not mp3_path.exists():
                    if not wav_path or not wav_path.exists():
                        raise HTTPException(status_code=404, detail="File not found")
                    actual_mp3_path = convert_wav_to_mp3(wav_path)
                else:
                    actual_mp3_path = mp3_path

                total_size = actual_mp3_path.stat().st_size
                start, length, status_code, headers = parse_byte_range(
                    range_header,
                    total_size,
                    filename,
                )
                headers.update(cache_headers)
                return StreamingResponse(
                    stream_local_file(actual_mp3_path, start, length),
                    status_code=status_code,
                    media_type=media_type,
                    headers=headers,
                )

        else:
            # Default WAV format for legacy layout
            media_type = "audio/wav"
            filename = f"{stem}.wav"

            if db_key and storage.is_object_storage_enabled():
                total_size = storage.object_size(db_key)
                start, length, status_code, headers = parse_byte_range(
                    range_header,
                    total_size,
                    filename,
                )
                headers.update(cache_headers)
                return StreamingResponse(
                    storage.stream_object(db_key, offset=start, length=length),
                    status_code=status_code,
                    media_type=media_type,
                    headers=headers,
                )

            if not wav_path or not wav_path.exists():
                raise HTTPException(status_code=404, detail="File not found")

            total_size = wav_path.stat().st_size
            start, length, status_code, headers = parse_byte_range(
                range_header,
                total_size,
                filename,
            )
            headers.update(cache_headers)
            return StreamingResponse(
                stream_local_file(wav_path, start, length),
                status_code=status_code,
                media_type=media_type,
                headers=headers,
            )


@app.delete("/api/jobs/{job_id}")
def delete_job(
    job_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, str]:
    job = db.delete_job(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = Path(job["job_dir"])
    try:
        inside_jobs = job_dir.resolve().is_relative_to(config.JOBS_DIR)
    except ValueError:
        inside_jobs = False
    if job_dir.exists() and inside_jobs:
        shutil.rmtree(job_dir, ignore_errors=True)
    storage.remove_prefix(f"{job_id}/")

    return {"status": "deleted"}


@app.post("/api/jobs/{job_id}/chords")
def get_or_detect_chords(
    job_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    job = db.get_job(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "done":
        raise HTTPException(
            status_code=400,
            detail=f"Job status is '{job['status']}'. It must be 'done' to detect chords.",
        )

    if job.get("chords"):
        try:
            return {"chords": json.loads(job["chords"])}
        except Exception:
            pass

    instrumental_path = Path(job.get("instrumental_path") or "")
    if not instrumental_path.exists():
        if storage.is_object_storage_enabled() and job.get("instrumental_key"):
            try:
                instrumental_path.parent.mkdir(parents=True, exist_ok=True)
                storage.client().fget_object(
                    config.STORAGE_BUCKET,
                    job["instrumental_key"],
                    str(instrumental_path),
                )
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to retrieve instrumental track from storage: {e}",
                )
        else:
            raise HTTPException(
                status_code=404,
                detail="Instrumental file is missing on local server.",
            )

    try:
        detected = detect_chords(instrumental_path)
        db.update_job(job_id, chords=json.dumps(detected))
        return {"chords": detected}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed during chord detection algorithm execution: {e}",
        )


@app.delete("/api/jobs/{job_id}/chords")
def delete_chords(
    job_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    job = db.get_job(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    db.update_job(job_id, chords=None)
    return {"status": "deleted"}


MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB limit
ALLOWED_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac",
    ".mp4", ".mkv", ".avi", ".mov"
}


@app.post("/api/jobs")
async def create_job(
    file: UploadFile | None = File(None),
    youtube_url: str | None = Form(None),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    has_file = file is not None and bool(file.filename)
    has_url = youtube_url is not None and bool(youtube_url.strip())

    if not has_file and not has_url:
        raise HTTPException(
            status_code=400,
            detail="Either a file upload or a YouTube URL must be provided.",
        )
    if has_file and has_url:
        raise HTTPException(
            status_code=400,
            detail="Cannot provide both a file upload and a YouTube URL simultaneously.",
        )

    separation_mode = "quality"

    if has_url:
        url_val = youtube_url.strip()
        if not ("youtube.com" in url_val or "youtu.be" in url_val):
            raise HTTPException(
                status_code=400,
                detail="Invalid YouTube URL. Only youtube.com and youtu.be links are supported.",
            )

        job_id = str(uuid.uuid4())
        job_dir = config.JOBS_DIR / job_id
        input_dir = job_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        original_filename = "YouTube Video"
        job = db.create_job(
            job_id=job_id,
            user_id=user["id"],
            original_filename=original_filename,
            input_path=url_val,
            job_dir=job_dir,
            input_key="",
            separation_mode=separation_mode,
        )
        enqueue_job(job_id)
        refreshed = db.get_job(job_id, user["id"]) or job
        return {"job": serialize_job(refreshed)}

    # Handle file upload
    original_filename = Path(file.filename).name
    file_ext = Path(original_filename).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{file_ext}'. Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    job_id = str(uuid.uuid4())
    job_dir = config.JOBS_DIR / job_id
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    raw_input = input_dir / original_filename
    total_written = 0
    try:
        with raw_input.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_written += len(chunk)
                if total_written > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="File is too large. Maximum allowed size is 100MB.",
                    )
                f.write(chunk)
    except Exception as exc:
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
        raise exc

    input_key = storage.put_file(raw_input, f"{job_id}/input/{original_filename}")
    job = db.create_job(
        job_id=job_id,
        user_id=user["id"],
        original_filename=original_filename,
        input_path=raw_input,
        job_dir=job_dir,
        input_key=input_key,
        separation_mode=separation_mode,
    )
    enqueue_job(job_id)

    refreshed = db.get_job(job_id, user["id"]) or job
    return {"job": serialize_job(refreshed)}

