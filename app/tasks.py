import os
from datetime import UTC, datetime
from pathlib import Path

from celery import Celery

from app import db
from app import storage
from app.processing import separate_audio, convert_wav_to_mp3

BROKER_URL = os.getenv("CELERY_BROKER_URL", "pyamqp://guest:guest@localhost//")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "rpc://")

celery_app = Celery("vocals", broker=BROKER_URL, backend=RESULT_BACKEND)
celery_app.conf.update(
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    broker_connection_timeout=1,
)


def download_youtube_audio(url: str, job_dir: Path) -> tuple[Path, str]:
    import yt_dlp

    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(input_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "noprogress": True,
        "noplaylist": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = Path(ydl.prepare_filename(info))
        if filepath.exists():
            return filepath, info.get("title", "YouTube Video")

        for p in input_dir.glob("*"):
            if p.is_file() and p.name != ".DS_Store":
                return p, info.get("title", "YouTube Video")

        raise RuntimeError("Failed to download YouTube audio file")


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
        input_path_str = job["input_path"]
        job_dir = Path(job["job_dir"])

        if input_path_str.startswith("http://") or input_path_str.startswith("https://"):
            report(2, "Downloading audio from YouTube")
            local_input_path, title = download_youtube_audio(input_path_str, job_dir)

            input_key = storage.put_file(
                local_input_path, f"{job_id}/input/{local_input_path.name}"
            )

            db.update_job(
                job_id,
                input_key=input_key,
                input_path=str(local_input_path),
                original_filename=title,
            )
            input_path = local_input_path
        else:
            input_path = Path(input_path_str)

        report(5, "Your file is processing. You can close this page.")

        # Guard: check audio duration to avoid OOM on very long tracks.
        # Demucs can be memory-intensive on long audio tracks.
        MAX_DURATION_MINUTES = 15
        try:
            import soundfile as sf
            wav_path = input_path
            # If not a wav, we need to convert first — but convert_to_wav happens
            # inside separate_audio, so just probe the raw input duration with ffprobe.
            import subprocess
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(input_path)],
                capture_output=True, text=True, timeout=30,
            )
            if probe.returncode == 0 and probe.stdout.strip():
                audio_duration = float(probe.stdout.strip())
                if audio_duration > MAX_DURATION_MINUTES * 60:
                    raise RuntimeError(
                        f"Audio is too long ({audio_duration / 60:.0f} min). "
                        f"Maximum supported duration is {MAX_DURATION_MINUTES} minutes "
                        f"to avoid running out of memory."
                    )
        except RuntimeError:
            raise
        except Exception:
            pass  # If probe fails, proceed anyway and let separation try

        result = separate_audio(
            input_path=input_path,
            job_dir=job_dir,
            report_progress=report,
        )
        instrumental_key = storage.put_file(
            Path(result["instrumental_path"]),
            f"{job_id}/exports/instrumental.mp3",
        )
        vocals_key = storage.put_file(
            Path(result["vocals_path"]),
            f"{job_id}/exports/vocals.mp3",
        )
        db.update_job(
            job_id,
            status="done",
            progress=100,
            message="Ready",
            duration=result["duration"],
            instrumental_path=result["instrumental_path"],
            instrumental_key=instrumental_key,
            vocals_path=result["vocals_path"],
            vocals_key=vocals_key,
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
