# Stemdeck

Stemdeck is a web application for splitting audio/video files or YouTube links into vocal and instrumental stems.

## Features
- Upload audio/video files (up to 100MB) or extract directly from a YouTube URL.
- Two separation modes:
  - **Fast**: CPU-optimized ONNX model separation (Sherpa-ONNX UVR, Spleeter, or local UVR).
  - **Quality**: Local Demucs (`htdemucs`) model.
- Synchronized multi-track HTML5 playback with volume and mute controls, hard-sync, and drift correction.
- Short-lived guest sessions and persistent user accounts.
- Local or S3-compatible (MinIO) storage.
- English and Ukrainian UI translation.

## Stack
- **Backend**: FastAPI, SQLite3, Celery, RabbitMQ
- **Processing**: PyTorch, Torchaudio, Sherpa-ONNX, Demucs, yt-dlp
- **Frontend**: Vanilla HTML/CSS/JS

## Setup & Run

### Docker Compose (Recommended)
```bash
docker compose up -d --build
```
Access the app at `http://localhost:8000`.

Run end-to-end tests:
```bash
npm install
npm run test:e2e
```

### Manual Host Setup
1. Install FFmpeg.
2. Install Python dependencies:
   ```bash
   pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.8.0" "torchaudio==2.8.0"
   pip install -r requirements.txt
   ```
3. Run RabbitMQ:
   ```bash
   docker run --rm -p 5672:5672 rabbitmq:3
   ```
4. Start the API:
   ```bash
   ./run_local.sh
   ```
5. Start the Celery worker:
   ```bash
   ./run_worker.sh
   ```

---

## VPS Deployment

### Automated Script
Sync codebase and rebuild containers on the remote host configured in `deploy.sh`:
```bash
./deploy.sh
```

### Manual Setup
1. Install Docker and Docker Compose on the host.
2. Clone repository, copy `.env.example` to `.env`.
3. Start stack:
   ```bash
   docker compose up -d --build
   ```

---

## API Reference

| Endpoint | Method | Form Parameters / Payload | Description |
| :--- | :--- | :--- | :--- |
| `/api/register` | `POST` | `username`, `password` (Form) | Create user account |
| `/api/login` | `POST` | `username`, `password` (Form) | Log in to account |
| `/api/logout` | `POST` | None | Log out of active session |
| `/api/guest` | `POST` | None | Start temporary guest session |
| `/api/me` | `GET` | None | Get current session user details |
| `/api/jobs` | `GET` | None | List user's separation jobs |
| `/api/jobs` | `POST` | `file` (Upload) OR `youtube_url` (Form), `fast_mode` (Bool Form) | Enqueue separation job |
| `/api/jobs/{job_id}` | `GET` | None | Get job status and metadata |
| `/api/jobs/{job_id}/files/vocals` | `GET` | None (Supports HTTP Range) | Stream/download vocals stem |
| `/api/jobs/{job_id}/files/instrumental` | `GET` | None (Supports HTTP Range) | Stream/download instrumental stem |
| `/api/jobs/{job_id}` | `DELETE` | None | Delete job and files |

---

## Configuration

Set options in a `.env` file:

```env
APP_HOST=0.0.0.0
APP_PORT=8000

SESSION_DAYS=30
GUEST_SESSION_HOURS=6

REUSE_PROCESSED_OUTPUTS=true

# Fast Mode options: sherpa_uvr, spleeter, uvr
FAST_SEPARATOR_BACKEND=sherpa_uvr
FAST_SHERPA_UVR_MODEL=UVR-MDX-NET-Inst_HQ_4.onnx
FAST_SHERPA_UVR_TARGET_STEM=instrumental
FAST_SHERPA_UVR_NUM_THREADS=4

# Storage options: local, s3
STORAGE_BACKEND=local
STORAGE_ENDPOINT=localhost:9000
STORAGE_ACCESS_KEY=stemdeck
STORAGE_SECRET_KEY=stemdeck-secret
STORAGE_BUCKET=stemdeck
STORAGE_SECURE=false
```
