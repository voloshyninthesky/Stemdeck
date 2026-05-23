import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
import contextlib
from typing import Any, Generator


from app import config

config.DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = config.DB_PATH


def _now() -> str:
    return datetime.now(UTC).isoformat()


@contextlib.contextmanager
def _connect() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_guest INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                original_filename TEXT NOT NULL,
                input_path TEXT NOT NULL,
                input_key TEXT,
                job_dir TEXT NOT NULL,
                instrumental_path TEXT,
                instrumental_key TEXT,
                vocals_path TEXT,
                vocals_key TEXT,
                separation_mode TEXT NOT NULL DEFAULT 'fast',
                duration REAL DEFAULT 0,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """
        )
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "is_guest" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN is_guest INTEGER NOT NULL DEFAULT 0")

        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        migrations = {
            "input_key": "ALTER TABLE jobs ADD COLUMN input_key TEXT",
            "instrumental_key": "ALTER TABLE jobs ADD COLUMN instrumental_key TEXT",
            "vocals_key": "ALTER TABLE jobs ADD COLUMN vocals_key TEXT",
            "separation_mode": (
                "ALTER TABLE jobs ADD COLUMN separation_mode TEXT NOT NULL DEFAULT 'fast'"
            ),
            "chords": "ALTER TABLE jobs ADD COLUMN chords TEXT",
        }
        for column, statement in migrations.items():
            if column not in columns:
                conn.execute(statement)


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    salt, _ = password_hash.split("$", 1)
    return secrets.compare_digest(hash_password(password, salt), password_hash)


def create_user(username: str, password: str) -> dict[str, Any]:
    username = username.strip().lower()
    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")

    try:
        with _connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (username, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (username, hash_password(password), _now()),
            )
            user_id = cur.lastrowid
            row = conn.execute(
                "SELECT id, username, is_guest, created_at FROM users WHERE id = ?", (user_id,)
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise ValueError("Username is already taken") from exc

    user = _row_to_dict(row)
    if not user:
        raise ValueError("Failed to create user")
    user["is_guest"] = bool(user["is_guest"])
    return user


def create_guest_user() -> dict[str, Any]:
    now = _now()
    for _ in range(5):
        username = f"guest-{secrets.token_hex(4)}"
        try:
            with _connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO users (username, password_hash, is_guest, created_at)
                    VALUES (?, '', 1, ?)
                    """,
                    (username, now),
                )
                row = conn.execute(
                    "SELECT id, username, is_guest, created_at FROM users WHERE id = ?",
                    (cur.lastrowid,),
                ).fetchone()
            user = _row_to_dict(row)
            if user:
                user["is_guest"] = bool(user["is_guest"])
                return user
        except sqlite3.IntegrityError:
            continue
    raise ValueError("Failed to create guest user")


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND is_guest = 0",
            (username.strip().lower(),),
        ).fetchone()

    user = _row_to_dict(row)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    return {
        "id": user["id"],
        "username": user["username"],
        "is_guest": bool(user["is_guest"]),
        "created_at": user["created_at"],
    }


def create_session(user_id: int, ttl: timedelta | None = None) -> str:
    token = secrets.token_urlsafe(32)
    ttl = ttl or timedelta(days=config.SESSION_DAYS)
    expires_at = (datetime.now(UTC) + ttl).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (token, user_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, expires_at, _now()),
        )
    return token


def delete_session(token: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def get_user_by_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT users.id, users.username, users.created_at
                 , users.is_guest
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at > ?
            """,
            (token, _now()),
        ).fetchone()

    user = _row_to_dict(row)
    if user:
        user["is_guest"] = bool(user["is_guest"])
    return user


def transfer_jobs(from_user_id: int, to_user_id: int) -> None:
    if from_user_id == to_user_id:
        return
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET user_id = ? WHERE user_id = ?",
            (to_user_id, from_user_id),
        )


def create_job(
    job_id: str,
    user_id: int,
    original_filename: str,
    input_path: Path | str,
    job_dir: Path,
    input_key: str = "",
    separation_mode: str = "quality",
) -> dict[str, Any]:
    if separation_mode != "quality":
        raise ValueError("Invalid separation mode")


    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO jobs (
                id, user_id, original_filename, input_path, input_key, job_dir, separation_mode,
                status, progress, message, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, 'Waiting in queue', ?, ?)
            """,
            (
                job_id,
                user_id,
                original_filename,
                str(input_path),
                input_key,
                str(job_dir),
                separation_mode,
                now,
                now,
            ),
        )
    job = get_job(job_id, user_id)
    if not job:
        raise ValueError("Failed to create job")
    return job


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return

    allowed_fields = {
        "input_path",
        "original_filename",
        "input_key",
        "instrumental_path",
        "instrumental_key",
        "vocals_path",
        "vocals_key",
        "duration",
        "status",
        "progress",
        "message",
        "error",
        "completed_at",
        "chords",
    }
    unknown_fields = set(fields) - allowed_fields
    if unknown_fields:
        raise ValueError(f"Unknown job fields: {', '.join(sorted(unknown_fields))}")

    fields["updated_at"] = _now()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values())
    values.append(job_id)

    with _connect() as conn:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)


def get_job(job_id: str, user_id: int | None = None) -> dict[str, Any] | None:
    query = "SELECT * FROM jobs WHERE id = ?"
    params: list[Any] = [job_id]
    if user_id is not None:
        query += " AND user_id = ?"
        params.append(user_id)

    with _connect() as conn:
        row = conn.execute(query, params).fetchone()
    return _row_to_dict(row)


def list_jobs(user_id: int) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM jobs
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def queue_position(job_id: str) -> int | None:
    job = get_job(job_id)
    if not job or job["status"] != "queued":
        return None

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS position
            FROM jobs
            WHERE status = 'queued'
              AND created_at <= ?
            """,
            (job["created_at"],),
        ).fetchone()
    return int(row["position"]) if row else None


def delete_job(job_id: str, user_id: int) -> dict[str, Any] | None:
    job = get_job(job_id, user_id)
    if not job:
        return None

    with _connect() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ? AND user_id = ?", (job_id, user_id))

    return job


def count_user_jobs_since(user_id: int, minutes: int = 5) -> int:
    cutoff = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM jobs WHERE user_id = ? AND created_at >= ?",
            (user_id, cutoff),
        ).fetchone()
    return int(row["cnt"]) if row else 0

