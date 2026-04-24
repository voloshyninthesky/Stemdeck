import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.tasks import process_job

BASE_DIR = Path(__file__).resolve().parent.parent
JOBS_DIR = BASE_DIR / "jobs"
WEB_DIR = BASE_DIR / "web"
SESSION_COOKIE = "vocals_session"

JOBS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Vocal Remover App API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=JOBS_DIR), name="media")
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.on_event("startup")
def startup() -> None:
    db.init_db()


@app.get("/")
def root() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(WEB_DIR / "manifest.webmanifest")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    return FileResponse(WEB_DIR / "sw.js")


@app.get("/icons/{name}")
def icon(name: str) -> FileResponse:
    return FileResponse(WEB_DIR / "icons" / name)


def current_user(
    vocals_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    user = db.get_user_by_session(vocals_session)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def serialize_job(job: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": job["id"],
        "filename": job["original_filename"],
        "status": job["status"],
        "progress": job["progress"],
        "message": job["message"],
        "error": job["error"],
        "duration": job["duration"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "completed_at": job["completed_at"],
        "instrumental_url": None,
        "vocals_url": None,
    }

    if job["instrumental_path"] and job["vocals_path"]:
        payload["instrumental_url"] = f"/media/{job['id']}/exports/instrumental.wav"
        payload["vocals_url"] = f"/media/{job['id']}/exports/vocals.wav"

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
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
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
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return {"user": user}


@app.post("/api/logout")
def logout(
    response: Response,
    vocals_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, str]:
    if vocals_session:
        db.delete_session(vocals_session)
    response.delete_cookie(SESSION_COOKIE)
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


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing file name")

    job_id = str(uuid.uuid4())
    job_dir = JOBS_DIR / job_id
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

    job = db.create_job(
        job_id=job_id,
        user_id=user["id"],
        original_filename=original_filename,
        input_path=raw_input,
        job_dir=job_dir,
    )
    enqueue_job(job_id)

    refreshed = db.get_job(job_id, user["id"]) or job
    return {"job": serialize_job(refreshed)}
