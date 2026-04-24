import os
from datetime import UTC, datetime
from pathlib import Path

from celery import Celery

from app import db
from app.processing import separate_audio

BROKER_URL = os.getenv("CELERY_BROKER_URL", "pyamqp://guest:guest@localhost//")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "rpc://")

celery_app = Celery("vocals", broker=BROKER_URL, backend=RESULT_BACKEND)
celery_app.conf.update(
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    broker_connection_timeout=1,
)


@celery_app.task(name="app.tasks.process_job")
def process_job(job_id: str) -> None:
    db.init_db()
    job = db.get_job(job_id)
    if not job:
        return

    def report(progress: int, message: str) -> None:
        db.update_job(
            job_id,
            status="processing",
            progress=progress,
            message=message,
        )

    try:
        report(5, "Starting")
        result = separate_audio(
            input_path=Path(job["input_path"]),
            job_dir=Path(job["job_dir"]),
            report_progress=report,
        )
        db.update_job(
            job_id,
            status="done",
            progress=100,
            message="Ready",
            duration=result["duration"],
            instrumental_path=result["instrumental_path"],
            vocals_path=result["vocals_path"],
            completed_at=datetime.now(UTC).isoformat(),
        )
    except Exception as exc:
        db.update_job(
            job_id,
            status="failed",
            progress=100,
            message="Failed",
            error=str(exc),
            completed_at=datetime.now(UTC).isoformat(),
        )
