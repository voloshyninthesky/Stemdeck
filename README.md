# Stemdeck

Stemdeck is a regular web app for splitting uploaded audio/video files into instrumental and vocal stems.

Features:

1. Account login with session cookies.
2. Upload history per user.
3. Queued stem separation with friendly status messages and queue position.
4. Synchronized instrumental/vocal playback with volume and mute controls.
5. Delete uploads from your account.
6. Download links for both stems.
7. Fast mode with a UVR MDX-Net model, plus slower Demucs quality mode.

## Stack

- Backend: FastAPI + SQLite + Celery/RabbitMQ + Sherpa-ONNX/UVR + Demucs + Audio Separator
- Frontend: Vanilla HTML/CSS/JS with English/Ukrainian UI strings
- Storage: persistent SQLite sessions/jobs plus MinIO S3-compatible object storage in Docker

## Setup

Install dependencies (pin CPU PyTorch 2.8 — Torchaudio 2.9+ needs `torchcodec`, whose PyPI wheel pulls CUDA libs):

```bash
pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.8.0" "torchaudio==2.8.0"
pip install -r requirements.txt
```

On Linux x86_64 you can use newer versions if you also install CPU `torchcodec` from the same index:

```bash
pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio torchcodec
```

Make sure `ffmpeg` is installed and available in `PATH`.

## Run Locally

### Docker Compose

The easiest way to run the full app is Docker Compose:

```bash
docker compose up --build
```

Open:

```text
http://localhost:8000
```

Run browser E2E smoke tests against the running app:

```bash
npm install
npm run test:e2e
```

The tests use local Chromium by default. Override with `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/path/to/chrome` if needed.

Compose starts:

- `web`: FastAPI web app
- `worker`: Celery worker for fast UVR and quality Demucs processing
- `rabbitmq`: queue broker with management UI at `http://localhost:15672`
- `minio`: lightweight local S3-compatible storage with console at `http://localhost:9001`

Persistent Docker volumes:

- `app_data`: SQLite database and uploaded/generated stems
- `model_cache`: UVR, optional Spleeter, and Demucs model cache
- `minio_data`: uploaded/generated audio objects
- `rabbitmq_data`: RabbitMQ state

### Manual

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

## Ubuntu VPS

Install Docker and Compose plugin:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc >/dev/null
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Deploy:

```bash
git clone <your-repo-url> stemdeck
cd stemdeck
cp .env.example .env
```

For direct public access on port `8000`, keep:

```env
APP_HOST=0.0.0.0
APP_PORT=8000
SESSION_DAYS=30
REUSE_PROCESSED_OUTPUTS=true
```

For Nginx/Caddy reverse proxy, bind the app only to localhost:

```env
APP_HOST=127.0.0.1
APP_PORT=8000
```

Start the stack:

```bash
docker compose up -d --build
```

RabbitMQ management is bound to `127.0.0.1:15672` by default.
MinIO console is bound to `127.0.0.1:9001` by default.
Example Nginx location:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Operational commands:

```bash
docker compose logs -f web worker
docker compose restart worker
docker compose pull && docker compose up -d --build
```

### Native systemd services

If you prefer to run without Docker, systemd service templates are included in `deploy/systemd/`.
They cover:

- `stemdeck-web.service`: FastAPI app on `127.0.0.1:8000` by default
- `stemdeck-worker.service`: Celery audio processing worker
- `stemdeck.target`: starts web and worker together
- `stemdeck-minio.service`: optional local S3-compatible MinIO storage

See `deploy/systemd/README.md` for install commands, environment files, and operational commands.

## API

- `POST /api/register` with `username`, `password`
- `POST /api/login` with `username`, `password`
- `POST /api/logout`
- `GET /api/me`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/files/instrumental`
- `GET /api/jobs/{job_id}/files/vocals`
- `POST /api/jobs` with multipart fields `file` and optional `fast_mode`
- `DELETE /api/jobs/{job_id}`

Job responses include `status`, `progress`, `queue_position`, `separation_mode`, `instrumental_url`, `vocals_url`, and `duration`.

OpenAPI, Swagger UI, and ReDoc are disabled in production routes.

## Notes

- First Demucs run may download model weights.
- First fast-mode run downloads the Sherpa-ONNX `UVR-MDX-NET-Inst_HQ_4.onnx` model into the model cache.
- `FAST_SHERPA_UVR_TARGET_STEM=instrumental` keeps models whose primary output is instrumental mapped to the right player channel.
- Set `FAST_SEPARATOR_BACKEND=spleeter` to use the very fast, lower-quality Spleeter backend.
- Set `FAST_SEPARATOR_BACKEND=uvr` to use the legacy UVR fast model instead.
- Existing completed jobs are reused when `REUSE_PROCESSED_OUTPUTS=true` and both stem files exist in the job export folder.
- Guests can process files without creating an account. Guest sessions use `GUEST_SESSION_HOURS` and are shorter-lived than regular account sessions.
- Runtime data is ignored by git: `app_data.sqlite3`, `jobs/`, `.env`, and logs.
- CPU-only stem separation is heavy. A small VPS works for testing, but real songs need patience or a stronger machine.
