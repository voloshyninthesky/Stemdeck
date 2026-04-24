# Stemdeck

Stemdeck is a regular web app for splitting uploaded audio/video files into instrumental and vocal stems.

Features:

1. Account login with session cookies.
2. Upload history per user.
3. Queued stem separation with progress bars.
4. Synchronized instrumental/vocal playback with volume and mute controls.
5. Download links for both stems.

## Stack

- Backend: FastAPI + SQLite + Celery/RabbitMQ + Demucs
- Frontend: Vanilla HTML/CSS/JS
- Storage: local SQLite database and `jobs/` media folder

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Make sure `ffmpeg` is installed and available in `PATH`.

## Run Locally

Start RabbitMQ:

```bash
docker run --rm -p 5672:5672 rabbitmq:3
```

Start the API server:

```bash
./run_local.sh
```

Start the worker in a second terminal:

```bash
./run_worker.sh
```

Open:

```text
http://localhost:8000
```

If RabbitMQ is not running, the API falls back to an in-process background worker so local testing still works.

## API

- `POST /api/register` with `username`, `password`
- `POST /api/login` with `username`, `password`
- `POST /api/logout`
- `GET /api/me`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs` with multipart field `file`

Job responses include `status`, `progress`, `instrumental_url`, `vocals_url`, and `duration`.

## Notes

- First Demucs run may download model weights.
- Runtime data is ignored by git: `app_data.sqlite3`, `jobs/`, `.env`, and logs.
