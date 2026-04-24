from pathlib import Path
from typing import Iterator

from fastapi import HTTPException


CHUNK_SIZE = 1024 * 1024


def parse_byte_range(
    range_header: str | None,
    total_size: int,
    filename: str,
) -> tuple[int, int, int, dict[str, str]]:
    if total_size <= 0:
        raise HTTPException(status_code=404, detail="File is empty")

    start = 0
    end = total_size - 1
    status_code = 200
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{filename}"',
    }

    if range_header and range_header.lower().startswith("bytes="):
        raw_range = range_header.split("=", 1)[1].split(",", 1)[0]
        raw_start, _, raw_end = raw_range.partition("-")
        try:
            if raw_start:
                start = int(raw_start)
                if raw_end:
                    end = int(raw_end)
            elif raw_end:
                suffix_length = int(raw_end)
                start = max(0, total_size - suffix_length)
            else:
                raise ValueError
        except ValueError as exc:
            raise HTTPException(status_code=416, detail="Range not satisfiable") from exc

        end = min(end, total_size - 1)
        if start > end or start >= total_size:
            raise HTTPException(status_code=416, detail="Range not satisfiable")

        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{total_size}"

    length = end - start + 1
    headers["Content-Length"] = str(length)
    return start, length, status_code, headers


def stream_local_file(path: Path, offset: int, length: int) -> Iterator[bytes]:
    remaining = length
    with path.open("rb") as f:
        f.seek(offset)
        while remaining > 0:
            chunk = f.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
