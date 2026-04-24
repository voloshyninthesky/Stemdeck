import os
from pathlib import Path
from typing import Iterator

from minio import Minio
from minio.error import S3Error


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").strip().lower()
STORAGE_ENDPOINT = os.getenv("STORAGE_ENDPOINT", "").strip()
STORAGE_ACCESS_KEY = os.getenv("STORAGE_ACCESS_KEY", "stemdeck")
STORAGE_SECRET_KEY = os.getenv("STORAGE_SECRET_KEY", "stemdeck-secret")
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "stemdeck")
STORAGE_SECURE = _truthy(os.getenv("STORAGE_SECURE"), False)

_client: Minio | None = None


def is_object_storage_enabled() -> bool:
    return STORAGE_BACKEND == "minio" and bool(STORAGE_ENDPOINT)


def client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            STORAGE_ENDPOINT,
            access_key=STORAGE_ACCESS_KEY,
            secret_key=STORAGE_SECRET_KEY,
            secure=STORAGE_SECURE,
        )
    return _client


def ensure_bucket() -> None:
    if not is_object_storage_enabled():
        return

    c = client()
    if not c.bucket_exists(STORAGE_BUCKET):
        c.make_bucket(STORAGE_BUCKET)


def put_file(local_path: Path, object_name: str) -> str:
    if not is_object_storage_enabled():
        return ""

    ensure_bucket()
    client().fput_object(STORAGE_BUCKET, object_name, str(local_path))
    return object_name


def remove_prefix(prefix: str) -> None:
    if not is_object_storage_enabled():
        return

    c = client()
    try:
        for item in c.list_objects(STORAGE_BUCKET, prefix=prefix, recursive=True):
            c.remove_object(STORAGE_BUCKET, item.object_name)
    except S3Error:
        return


def object_size(object_name: str) -> int:
    return int(client().stat_object(STORAGE_BUCKET, object_name).size)


def stream_object(
    object_name: str,
    chunk_size: int = 1024 * 1024,
    offset: int = 0,
    length: int | None = None,
) -> Iterator[bytes]:
    response = client().get_object(
        STORAGE_BUCKET,
        object_name,
        offset=offset,
        length=length,
    )
    try:
        for chunk in response.stream(chunk_size):
            if chunk:
                yield chunk
    finally:
        response.close()
        response.release_conn()
