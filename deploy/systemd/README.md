# Native systemd deployment

These files run Stemdeck on an Ubuntu VPS without Docker.

## 1. Install OS packages

```bash
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3-pip ffmpeg build-essential git libgomp1 libsndfile1 rabbitmq-server
sudo systemctl enable --now rabbitmq-server
```

## 2. Create app user and directories

```bash
sudo useradd --system --home /opt/stemdeck --shell /usr/sbin/nologin stemdeck || true
sudo mkdir -p /opt/stemdeck /etc/stemdeck /var/lib/stemdeck/jobs /var/cache/stemdeck
sudo chown -R stemdeck:stemdeck /opt/stemdeck /var/lib/stemdeck /var/cache/stemdeck
```

## 3. Deploy code

```bash
sudo rsync -a --delete ./ /opt/stemdeck/
sudo chown -R stemdeck:stemdeck /opt/stemdeck
sudo -u stemdeck python3.11 -m venv /opt/stemdeck/.venv
sudo -u stemdeck /opt/stemdeck/.venv/bin/pip install --upgrade pip
sudo -u stemdeck /opt/stemdeck/.venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio torchcodec
sudo -u stemdeck /opt/stemdeck/.venv/bin/pip install -r /opt/stemdeck/requirements.txt
```

## 4. Install config and services

```bash
sudo cp /opt/stemdeck/deploy/systemd/stemdeck.env.example /etc/stemdeck/stemdeck.env
sudo cp /opt/stemdeck/deploy/systemd/stemdeck-web.service /etc/systemd/system/
sudo cp /opt/stemdeck/deploy/systemd/stemdeck-worker.service /etc/systemd/system/
sudo cp /opt/stemdeck/deploy/systemd/stemdeck.target /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stemdeck.target
```

The app listens on `127.0.0.1:8000` by default. Put Nginx or Caddy in front of it for public HTTPS.

## Optional MinIO storage

The default env uses `STORAGE_BACKEND=local`, which is simplest. To use local S3-compatible MinIO storage instead:

```bash
curl -L https://dl.min.io/server/minio/release/linux-amd64/minio -o /tmp/minio
sudo install -m 0755 /tmp/minio /usr/local/bin/minio
sudo mkdir -p /var/lib/stemdeck-minio
sudo chown -R stemdeck:stemdeck /var/lib/stemdeck-minio
sudo cp /opt/stemdeck/deploy/systemd/stemdeck-minio.env.example /etc/stemdeck/minio.env
sudo cp /opt/stemdeck/deploy/systemd/stemdeck-minio.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stemdeck-minio.service
```

Then edit `/etc/stemdeck/stemdeck.env`:

```env
STORAGE_BACKEND=minio
STORAGE_ENDPOINT=127.0.0.1:9000
STORAGE_ACCESS_KEY=stemdeck
STORAGE_SECRET_KEY=change-this-secret
STORAGE_BUCKET=stemdeck
STORAGE_SECURE=false
```

Restart:

```bash
sudo systemctl restart stemdeck-web stemdeck-worker
```

## Operations

```bash
sudo systemctl status stemdeck-web stemdeck-worker
sudo journalctl -u stemdeck-web -f
sudo journalctl -u stemdeck-worker -f
sudo systemctl restart stemdeck-web stemdeck-worker
```
