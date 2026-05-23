"""Stemdeck Telegram Bot.

Accepts audio files or YouTube links, runs stem separation through the existing
Celery pipeline, and sends back the separated tracks with a mixer WebApp button.

Run:  python -m app.telegram_bot
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from pathlib import Path
from typing import BinaryIO

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.helpers import escape_markdown

from app import config, db, storage
from app.tasks import process_job
from app.processing import convert_wav_to_mp3

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("stemdeck.bot")

YOUTUBE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w\-]+",
    re.IGNORECASE,
)

ALLOWED_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac",
    ".mp4", ".mkv", ".avi", ".mov",
}

MAX_TELEGRAM_FILE_SIZE = 20 * 1024 * 1024  # Telegram bot API download limit


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _sanitize_filename(name: str) -> str:
    """Sanitize filename by replacing directory separators and other unsafe characters."""
    # Replace slashes and other unsafe symbols with hyphens
    sanitized = re.sub(r'[\\/*?:"<>|]', "-", name)
    # Remove leading/trailing spaces or dots
    sanitized = sanitized.strip().strip(".")
    return sanitized or "Track"


def _get_or_create_user(chat_id: int) -> dict:
    """Return a DB user for this Telegram chat, creating one if needed."""
    username = f"tg_{chat_id}"
    # Try to find the existing user
    from app.db import _connect, _row_to_dict
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, username, is_guest, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    user = _row_to_dict(row)
    if user:
        return user

    # Create a new bot user
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, is_guest, created_at) VALUES (?, '', 1, ?)",
            (username, now),
        )
        row = conn.execute(
            "SELECT id, username, is_guest, created_at FROM users WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    user = _row_to_dict(row)
    if not user:
        raise RuntimeError("Failed to create Telegram bot user")
    return user


def _build_mixer_url(job_id: str) -> str:
    from app.main import generate_mixer_token
    token = generate_mixer_token(job_id)
    return f"{config.TELEGRAM_WEBAPP_BASE_URL}/mixer?job_id={job_id}&token={token}"


def _enqueue_job(job_id: str) -> None:
    """Enqueue via Celery, fall back to synchronous execution."""
    import threading
    try:
        process_job.delay(job_id)
    except Exception:
        logger.warning("Celery unavailable, running job %s synchronously", job_id)
        thread = threading.Thread(target=process_job.run, args=(job_id,), daemon=True)
        thread.start()


async def _poll_job(status_msg, job_id: str, user_id: int, timeout: int = 600) -> dict:
    """Poll the DB until the job is done or failed, updating the Telegram status message."""
    import html
    elapsed = 0
    interval = 3
    last_text = ""
    while elapsed < timeout:
        await asyncio.sleep(interval)
        elapsed += interval
        job = db.get_job(job_id, user_id)
        if not job:
            raise RuntimeError("Job disappeared from DB")
        if job["status"] == "done":
            return job
        if job["status"] == "failed":
            raise RuntimeError(job.get("error") or "Separation failed")

        # Format status message using HTML
        if job["status"] == "queued":
            pos = db.queue_position(job_id)
            pos_text = f" (Position in queue: #{pos})" if pos else ""
            text = f"⏳ <b>Waiting in queue…</b>{pos_text}"
        else: # processing
            detail = html.escape(job.get("message", "Processing..."))
            text = (
                f"🎶 <b>Separating audio…</b>\n\n"
                f"⏳ <i>{detail}… Please wait.</i>"
            )

        if text != last_text:
            try:
                await status_msg.edit_text(text, parse_mode="HTML")
                last_text = text
            except Exception:
                pass

        # Increase interval after a while to reduce DB load
        if elapsed > 30:
            interval = 5
    raise RuntimeError("Processing timed out after 10 minutes")


async def _send_results(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    job: dict,
) -> None:
    """Send the separated stems and the mixer button."""
    chat_id = update.effective_chat.id

    # Resolve local paths to stem files
    vocals_path = Path(job.get("vocals_path") or "")
    inst_path = Path(job.get("instrumental_path") or "")

    # If local files aren't available but we have object storage keys,
    # download from storage to a temp location
    if not vocals_path.exists() and job.get("vocals_key") and storage.is_object_storage_enabled():
        job_dir = Path(job["job_dir"])
        exports = job_dir / "exports"
        exports.mkdir(parents=True, exist_ok=True)
        vocals_path = exports / "vocals.wav"
        storage.client().fget_object(config.STORAGE_BUCKET, job["vocals_key"], str(vocals_path))

    if not inst_path.exists() and job.get("instrumental_key") and storage.is_object_storage_enabled():
        job_dir = Path(job["job_dir"])
        exports = job_dir / "exports"
        exports.mkdir(parents=True, exist_ok=True)
        inst_path = exports / "instrumental.wav"
        storage.client().fget_object(config.STORAGE_BUCKET, job["instrumental_key"], str(inst_path))

    # Convert to MP3 for compact and native audio Telegram delivery
    try:
        vocals_mp3 = convert_wav_to_mp3(vocals_path)
        inst_mp3 = convert_wav_to_mp3(inst_path)
    except Exception as exc:
        logger.error("MP3 conversion failed: %s", exc)
        # Fall back to WAV
        vocals_mp3 = vocals_path
        inst_mp3 = inst_path

    track_name = job.get("original_filename", "Track")
    safe_track_name = _sanitize_filename(track_name)

    # Send vocals as Document (File)
    vocals_file = open(str(vocals_mp3), "rb")
    await context.bot.send_document(
        chat_id=chat_id,
        document=vocals_file,
        filename=f"{safe_track_name} - Vocals.mp3",
    )

    # Send instrumental as Document (File)
    inst_file = open(str(inst_mp3), "rb")
    await context.bot.send_document(
        chat_id=chat_id,
        document=inst_file,
        filename=f"{safe_track_name} - Instrumental.mp3",
    )

    # Send mixer button
    mixer_url = _build_mixer_url(job["id"])
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🎛 Open Mixer",
            web_app=WebAppInfo(url=mixer_url),
        )]
    ])
    safe_track_name = escape_markdown(track_name, version=2)

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"✅ *{safe_track_name}* — separation complete\\!\n\nUse the mixer to blend vocals and instrumental with volume controls\\.",
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )


# ──────────────────────────────────────────────
# Handlers
# ──────────────────────────────────────────────

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🎵 *Welcome to Stemdeck\\!*\n\n"
        "Send me:\n"
        "• An audio file \\(MP3, WAV, FLAC, OGG, etc\\.\\)\n"
        "• A YouTube link\n\n"
        "I'll separate it into *vocals* and *instrumental* tracks, "
        "and give you a mixer to blend them\\! 🎛",
        parse_mode="MarkdownV2",
    )


async def audio_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle audio files, voice messages, and documents with audio extensions."""
    message = update.message
    chat_id = message.chat_id

    # Determine the file to download
    if message.audio:
        file_id = message.audio.file_id
        file_name = message.audio.file_name or "audio.mp3"
        file_size = message.audio.file_size or 0
    elif message.voice:
        file_id = message.voice.file_id
        file_name = "voice.ogg"
        file_size = message.voice.file_size or 0
    elif message.document:
        doc = message.document
        ext = Path(doc.file_name or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            await message.reply_text(
                f"❌ Unsupported file type `{ext}`.\n"
                f"Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
                parse_mode="Markdown",
            )
            return
        file_id = doc.file_id
        file_name = doc.file_name or "file"
        file_size = doc.file_size or 0
    elif message.video:
        file_id = message.video.file_id
        file_name = message.video.file_name or "video.mp4"
        file_size = message.video.file_size or 0
    else:
        return

    if file_size > MAX_TELEGRAM_FILE_SIZE:
        await message.reply_text(
            "❌ File is too large. Telegram allows bots to download files up to 20 MB.\n"
            "Please use a YouTube link instead, or compress the file."
        )
        return

    status_msg = await message.reply_text("⏳ Downloading your file…")

    try:
        db.init_db()
        user = _get_or_create_user(chat_id)
        import uuid
        job_id = str(uuid.uuid4())
        job_dir = config.JOBS_DIR / job_id
        input_dir = job_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        # Download from Telegram
        tg_file = await context.bot.get_file(file_id)
        local_path = input_dir / Path(file_name).name
        await tg_file.download_to_drive(str(local_path))

        # Store input in object storage
        input_key = storage.put_file(local_path, f"{job_id}/input/{local_path.name}")

        job = db.create_job(
            job_id=job_id,
            user_id=user["id"],
            original_filename=Path(file_name).stem,
            input_path=local_path,
            job_dir=job_dir,
            input_key=input_key,
            separation_mode="quality",
        )

        await status_msg.edit_text("🎶 Separating vocals and instrumental… This may take a minute.")
        _enqueue_job(job_id)

        done_job = await _poll_job(status_msg, job_id, user["id"])
        await status_msg.delete()
        await _send_results(update, context, done_job)

    except Exception as exc:
        logger.exception("Audio processing failed for chat %s", chat_id)
        try:
            await status_msg.edit_text(f"❌ Processing failed: {exc}")
        except Exception:
            await message.reply_text(f"❌ Processing failed: {exc}")


async def youtube_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle messages containing YouTube links."""
    message = update.message
    chat_id = message.chat_id
    text = message.text or ""

    match = YOUTUBE_RE.search(text)
    if not match:
        return

    url = match.group(0)
    if not url.startswith("http"):
        url = "https://" + url

    status_msg = await message.reply_text("⏳ Downloading from YouTube…")

    try:
        db.init_db()
        user = _get_or_create_user(chat_id)
        import uuid
        job_id = str(uuid.uuid4())
        job_dir = config.JOBS_DIR / job_id
        input_dir = job_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        job = db.create_job(
            job_id=job_id,
            user_id=user["id"],
            original_filename="YouTube Video",
            input_path=url,
            job_dir=job_dir,
            input_key="",
            separation_mode="quality",
        )

        await status_msg.edit_text("🎶 Downloading & separating… This may take a few minutes.")
        _enqueue_job(job_id)

        done_job = await _poll_job(status_msg, job_id, user["id"])
        await status_msg.delete()
        await _send_results(update, context, done_job)

    except Exception as exc:
        logger.exception("YouTube processing failed for chat %s", chat_id)
        try:
            await status_msg.edit_text(f"❌ Processing failed: {exc}")
        except Exception:
            await message.reply_text(f"❌ Processing failed: {exc}")


async def unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unrecognized text messages."""
    text = (update.message.text or "").strip()
    if not text:
        return

    # Don't respond to YouTube links (handled by youtube_handler)
    if YOUTUBE_RE.search(text):
        return

    await update.message.reply_text(
        "🤔 I didn't understand that.\n\n"
        "Send me an audio file or a YouTube link, "
        "and I'll separate it into vocal and instrumental tracks!"
    )


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main() -> None:
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Exiting.")
        sys.exit(1)

    db.init_db()
    storage.ensure_bucket()

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", start_handler))

    # Audio files — audio, voice, video, and documents
    app.add_handler(MessageHandler(
        filters.AUDIO | filters.VOICE | filters.VIDEO | filters.Document.ALL,
        audio_handler,
    ))

    # YouTube links in text messages
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(YOUTUBE_RE),
        youtube_handler,
    ))

    # Fallback for unknown text
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        unknown_handler,
    ))

    logger.info("Stemdeck Telegram bot starting…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
