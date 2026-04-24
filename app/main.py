import threading
import uuid
import shutil
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
from app.tasks import process_job

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
        "separation_mode": job.get("separation_mode", "fast"),
        "queue_position": queue_position,
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "completed_at": job["completed_at"],
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
) -> dict[str, Any]:
    try:
        user = db.create_user(username, password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    token = db.create_session(user["id"])
    response.set_cookie(
        config.SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * config.SESSION_DAYS,
    )
    return {"user": user}


@app.post("/api/login")
def login(
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
) -> dict[str, Any]:
    user = db.authenticate_user(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = db.create_session(user["id"])
    response.set_cookie(
        config.SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * config.SESSION_DAYS,
    )
    return {"user": user}


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
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"user": user}


@app.get("/api/jobs")
def jobs(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"jobs": [serialize_job(job) for job in db.list_jobs(user["id"])]}


@app.get("/api/jobs/{job_id}")
def job_detail(
    job_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    job = db.get_job(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": serialize_job(job)}


@app.get("/api/jobs/{job_id}/files/{stem}")
def job_file(
    job_id: str,
    stem: str,
    range_header: str | None = Header(default=None, alias="Range"),
    user: dict[str, Any] = Depends(current_user),
) -> Response:
    if stem not in {"instrumental", "vocals"}:
        raise HTTPException(status_code=404, detail="File not found")

    job = db.get_job(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    key = job.get(f"{stem}_key")
    filename = "instrumental.wav" if stem == "instrumental" else "vocals.wav"
    if key and storage.is_object_storage_enabled():
        total_size = storage.object_size(key)
        start, length, status_code, headers = parse_byte_range(
            range_header,
            total_size,
            filename,
        )
        return StreamingResponse(
            storage.stream_object(key, offset=start, length=length),
            status_code=status_code,
            media_type="audio/wav",
            headers=headers,
        )

    path = Path(job.get(f"{stem}_path") or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    total_size = path.stat().st_size
    start, length, status_code, headers = parse_byte_range(
        range_header,
        total_size,
        filename,
    )
    return StreamingResponse(
        stream_local_file(path, start, length),
        status_code=status_code,
        media_type="audio/wav",
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


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    fast_mode: bool = Form(True),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing file name")

    job_id = str(uuid.uuid4())
    job_dir = config.JOBS_DIR / job_id
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    original_filename = Path(file.filename).name
    raw_input = input_dir / original_filename
    with raw_input.open("wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)

    input_key = storage.put_file(raw_input, f"{job_id}/input/{original_filename}")
    separation_mode = "fast" if fast_mode else "quality"
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
