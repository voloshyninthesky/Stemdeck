from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from app import config

try:
    from minio import Minio
except ImportError:  # Local-only mode should still boot without MinIO installed.
    Minio = None  # type: ignore[assignment]


class StorageUnavailable(RuntimeError):
    pass


_client: Any | None = None


def is_object_storage_enabled() -> bool:
    return config.STORAGE_BACKEND == "minio" and bool(config.STORAGE_ENDPOINT)


def client() -> Any:
    global _client
    if Minio is None:
        raise StorageUnavailable("MinIO support is not installed")
    if _client is None:
        _client = Minio(
            config.STORAGE_ENDPOINT,
            access_key=config.STORAGE_ACCESS_KEY,
            secret_key=config.STORAGE_SECRET_KEY,
            secure=config.STORAGE_SECURE,
        )
    return _client


def ensure_bucket() -> None:
    if not is_object_storage_enabled():
        return

    c = client()
    if not c.bucket_exists(config.STORAGE_BUCKET):
        c.make_bucket(config.STORAGE_BUCKET)


def put_file(local_path: Path, object_name: str) -> str:
    if not is_object_storage_enabled():
        return ""

    ensure_bucket()
    client().fput_object(config.STORAGE_BUCKET, object_name, str(local_path))
    return object_name


def remove_prefix(prefix: str) -> None:
    if not is_object_storage_enabled():
        return

    c = client()
    try:
        for item in c.list_objects(config.STORAGE_BUCKET, prefix=prefix, recursive=True):
            c.remove_object(config.STORAGE_BUCKET, item.object_name)
    except Exception:
        return


def object_size(object_name: str) -> int:
    return int(client().stat_object(config.STORAGE_BUCKET, object_name).size)


def stream_object(
    object_name: str,
    chunk_size: int = 1024 * 1024,
    offset: int = 0,
    length: int | None = None,
) -> Iterator[bytes]:
    response = client().get_object(
        config.STORAGE_BUCKET,
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
